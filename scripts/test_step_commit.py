#!/usr/bin/env python3
"""Tests for step-commit.py — a scratch git repo and plan file per case, run as a
subprocess.

The events a step asks for are recorded at the event writer's seam, because the writer is
a separate module; the commit, the checklist and `progress.json` are exercised through the
subprocess.
"""

import argparse
import contextlib
import importlib.util
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import progress
import settings

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "step-commit.py")
PROGRESS_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plan-progress.py")
RUN_ID = "01JAB3K9V6T2Q8M4ZC7XWYN5RD"

PLAN_TEMPLATE = """\
# Some plan

## Goal

Do the thing.

## Progress

- [ ] 1. First step
- [ ] 2. Second step

## Steps

### 1. First step

- Files: `a.py`
- Change: do the first thing.

### 2. Second step

- Files: `b.py`
- Change: do the second thing.
"""

VALID_MESSAGE = (
    "Fix the widget rendering glitch.\n"
    "\n"
    "* Correct the off-by-one in the loop.\n"
    "* Add a regression test for the glitch.\n"
)


def load_step_commit():
    spec = importlib.util.spec_from_file_location("step_commit", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RecordingEvents:
    """The event writer's seam, recording what a step asks it to append instead of
    writing the run's `events.jsonl`."""

    def __init__(self):
        self.events = []

    def emit(self, root, run_id, type_, payload):
        if not run_id:
            return None
        self.events.append({"run_id": run_id, "type": type_, "payload": payload})
        return self.events[-1]

    def types(self):
        return [event["type"] for event in self.events]

    def payloads(self, type_):
        return [event["payload"] for event in self.events if event["type"] == type_]


class StubSettings:
    """The settings a step reads, pinned so a developer's own hoko.json cannot decide an
    in-process case. The model keys still follow the environment, which is the layer a
    case sets to name a stage's model."""

    VALUES = {"loopLimit": 3, "journalPath": "", "analyticsPath": ""}
    MODEL_KEYS = ("executorModel", "qaModel", "finalReview")

    def get(self, key):
        if key in self.MODEL_KEYS:
            return os.environ.get(settings.env_name(key)) or None
        return self.VALUES.get(key)


class StepCommitTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.isolate_models()
        self.env = dict(os.environ)
        self.env["TMPDIR"] = self.tmpdir.name
        self.env["HOME"] = self.tmpdir.name
        self.env["GIT_AUTHOR_NAME"] = "Test"
        self.env["GIT_AUTHOR_EMAIL"] = "test@example.com"
        self.env["GIT_COMMITTER_NAME"] = "Test"
        self.env["GIT_COMMITTER_EMAIL"] = "test@example.com"

    def isolate_models(self):
        """No developer's own `HOKO_*_MODEL` decides a case that runs in this process."""
        patch = mock.patch.dict(os.environ)
        patch.start()
        self.addCleanup(patch.stop)
        for name in ("HOKO_EXECUTOR_MODEL", "HOKO_QA_MODEL", "HOKO_FINAL_REVIEW"):
            os.environ.pop(name, None)

    def git(self, root, *args):
        result = subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, env=self.env,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def repo(self, name="repo", branch="feature/step-commit-test"):
        path = os.path.join(self.tmpdir.name, name)
        os.makedirs(path, exist_ok=True)
        self.git(path, "init", "-q")
        self.git(path, "checkout", "-q", "-b", branch)
        self.write(path, ".gitkeep", "")
        self.git(path, "add", ".gitkeep")
        self.git(path, "commit", "-q", "-m", "initial")
        return path

    def write(self, root, relpath, text):
        path = os.path.join(root, relpath)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def commit(self, root, message="commit"):
        self.git(root, "add", "-A")
        self.git(root, "commit", "-q", "-m", message)

    def makefile(self, root, analyse="true", unit="true"):
        lines = [f"analyse:\n\t{analyse}\n", f"unit:\n\t{unit}\n"]
        self.write(root, "Makefile", "\n".join(lines))
        self.commit(root, "add makefile")

    def plan(self, name="plan.md", text=PLAN_TEMPLATE):
        path = os.path.join(self.tmpdir.name, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def plan_text(self, plan_path):
        with open(plan_path, encoding="utf-8") as f:
            return f.read()

    def box_checked(self, plan_path, step):
        for line in self.plan_text(plan_path).splitlines():
            stripped = line.strip()
            if stripped.startswith(f"- [x] {step}.") or stripped.startswith(f"- [ ] {step}."):
                return stripped.startswith(f"- [x] {step}.")
        raise AssertionError(f"no progress box for step {step}")

    def progress_path(self, plan):
        return os.path.splitext(plan)[0] + ".progress.json"

    def step_entry(self, plan, step):
        with open(self.progress_path(plan), encoding="utf-8") as f:
            document = json.load(f)
        return next(s for s in document["rounds"][0]["steps"] if s["n"] == step)

    def head(self, root):
        return self.git(root, "rev-parse", "HEAD").strip()

    def run_step_commit(self, root, plan, step, message=None, no_op=None, env=None):
        args = [sys.executable, SCRIPT, "--plan", plan, "--step", str(step), "--root", root]
        if message is not None:
            args += ["--message-file", "-"]
        else:
            args += ["--no-op", no_op]
        return subprocess.run(
            args, capture_output=True, text=True, env=env or self.env, input=message,
        )

    def open_run(self, plan):
        """Opens the run the way the conductor does, then gives it the id the event
        writer assigns on first use, because that writer lands after this step."""
        proc = subprocess.run(
            [sys.executable, PROGRESS_SCRIPT, "init", "--plan", plan],
            capture_output=True, text=True, env=self.env,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        path = self.progress_path(plan)
        with open(path, encoding="utf-8") as f:
            document = json.load(f)
        document["run_id"] = RUN_ID
        with open(path, "w", encoding="utf-8") as f:
            json.dump(document, f, indent=2)

    def run_in_process(self, root, plan, step, message=None, no_op=None):
        """Runs one step in this process, with the environment the subprocess cases pass:
        git needs an identity, and settings must not read the developer's own config."""
        args = argparse.Namespace(
            plan=plan, step=step, root=root,
            message_file="-" if message is not None else None, no_op=no_op,
        )
        inherited = {key: self.env[key] for key in (
            "HOME", "TMPDIR", "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL",
            "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL")}
        with mock.patch.dict(os.environ, inherited), \
                mock.patch.object(sys, "stdin", io.StringIO(message or "")), \
                contextlib.redirect_stdout(io.StringIO()):
            return self.module.run(args)


class TestGreenCommit(StepCommitTestCase):
    def test_a_green_commit_lands_with_the_exact_message_and_every_change_staged(self):
        root = self.repo()
        self.makefile(root)
        plan = self.plan()
        self.write(root, "a.py", "changed content\n")
        self.write(root, "src/New.php", "<?php\n")
        proc = self.run_step_commit(root, plan, 1, message=VALID_MESSAGE)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.git(root, "status", "--short").strip(), "")
        logged = self.git(root, "log", "-1", "--pretty=%B")
        self.assertEqual(logged.rstrip("\n"), VALID_MESSAGE.rstrip("\n"))

    def test_the_box_is_ticked_after_the_commit(self):
        root = self.repo()
        self.makefile(root)
        plan = self.plan()
        self.write(root, "a.py", "changed content\n")
        proc = self.run_step_commit(root, plan, 1, message=VALID_MESSAGE)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue(self.box_checked(plan, 1))

    def test_a_step_commit_is_exactly_one_commit_holding_only_the_step_files(self):
        root = self.repo()
        self.makefile(root)
        plan = self.plan()
        self.write(root, "a.py", "changed content\n")
        before = int(self.git(root, "rev-list", "--count", "HEAD").strip())
        self.run_step_commit(root, plan, 1, message=VALID_MESSAGE)
        self.assertEqual(int(self.git(root, "rev-list", "--count", "HEAD").strip()), before + 1)
        self.assertEqual(self.git(root, "show", "--name-only", "--pretty=format:").split(),
                         ["a.py"])


class TestProgressJson(StepCommitTestCase):
    def test_exit_0_sets_the_step_done_with_the_commit_sha_in_progress_json(self):
        root = self.repo()
        self.makefile(root)
        plan = self.plan()
        self.write(root, "a.py", "changed content\n")
        proc = self.run_step_commit(root, plan, 1, message=VALID_MESSAGE)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

        entry = self.step_entry(plan, 1)
        self.assertEqual(entry["status"], "done")
        self.assertEqual(entry["commit"], self.head(root)[:len(entry["commit"])])
        self.assertEqual(self.step_entry(plan, 2)["status"], "pending")

    def test_a_no_op_sets_the_step_done_with_its_reason_and_no_commit(self):
        root = self.repo()
        self.makefile(root)
        plan = self.plan()
        proc = self.run_step_commit(root, plan, 1, no_op="nothing needed for this step")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

        entry = self.step_entry(plan, 1)
        self.assertEqual(entry["status"], "done")
        self.assertIsNone(entry["commit"])
        self.assertEqual(entry["note"], "nothing needed for this step")

    def test_a_red_gate_leaves_the_step_out_of_progress_json(self):
        root = self.repo()
        self.makefile(root, unit="false")
        plan = self.plan()
        self.write(root, "a.py", "changed content\n")
        proc = self.run_step_commit(root, plan, 1, message=VALID_MESSAGE)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertFalse(os.path.exists(self.progress_path(plan)))


class TestEvents(StepCommitTestCase):
    """The events a step asks the writer for, recorded at its seam."""

    def setUp(self):
        super().setUp()
        self.module = load_step_commit()
        self.recorder = RecordingEvents()
        for patcher in (mock.patch.object(progress, "events", self.recorder),
                        mock.patch.object(settings, "get", StubSettings().get)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_running_the_fast_gate_writes_one_fast_gate_check_result(self):
        root = self.repo()
        self.makefile(root)
        plan = self.plan()
        self.open_run(plan)
        self.write(root, "a.py", "changed content\n")
        code = self.run_in_process(root, plan, 1, message=VALID_MESSAGE)
        self.assertEqual(code, 0)

        checks = self.recorder.payloads("check.result")
        self.assertEqual(len(checks), 1)
        self.assertEqual({k: checks[0][k] for k in
                          ("stage", "cycle", "check", "status", "exit_code", "step")},
                         {"stage": "Implement", "cycle": 1, "check": "fast-gate",
                          "status": "passed", "exit_code": 0, "step": 1})
        self.assertGreaterEqual(checks[0]["duration_ms"], 0)

    def test_a_red_gate_writes_a_failed_check_result_and_no_stage_completed(self):
        root = self.repo()
        self.makefile(root, unit="false")
        plan = self.plan()
        self.open_run(plan)
        self.write(root, "a.py", "changed content\n")
        code = self.run_in_process(root, plan, 1, message=VALID_MESSAGE)
        self.assertEqual(code, 1)

        self.assertEqual(self.recorder.types()[-1], "check.result")
        self.assertEqual(self.recorder.payloads("check.result")[0]["status"], "failed")
        self.assertNotIn("stage.completed", self.recorder.types())

    def test_a_gate_with_nothing_to_check_is_a_skipped_check_result(self):
        root = self.repo()
        plan = self.plan()
        self.open_run(plan)
        self.write(root, "a.py", "changed content\n")
        code = self.run_in_process(root, plan, 1, message=VALID_MESSAGE)
        self.assertEqual(code, 0)
        check = self.recorder.payloads("check.result")[0]
        self.assertEqual((check["status"], check["exit_code"]), ("skipped", 2))

    def test_a_commit_writes_a_stage_completed_with_the_sha_and_the_step_fields(self):
        root = self.repo()
        self.makefile(root)
        plan = self.plan()
        self.open_run(plan)
        self.write(root, "a.py", "changed content\n")
        self.run_in_process(root, plan, 1, message=VALID_MESSAGE)

        self.assertEqual(self.recorder.types()[-1], "stage.completed")
        payload = self.recorder.payloads("stage.completed")[-1]
        self.assertEqual({k: payload[k] for k in
                          ("stage", "cycle", "outcome", "step", "steps", "title", "round", "no_op")},
                         {"stage": "Implement", "cycle": 1, "outcome": "done", "step": 1,
                          "steps": 2, "title": "First step", "round": 1, "no_op": False})
        self.assertEqual(payload["commit"], self.head(root)[:len(payload["commit"])])

    def test_a_no_op_writes_a_stage_completed_flagged_no_op_with_no_commit(self):
        root = self.repo()
        self.makefile(root)
        plan = self.plan()
        self.open_run(plan)
        self.run_in_process(root, plan, 1, no_op="nothing needed")
        payload = self.recorder.payloads("stage.completed")[-1]
        self.assertEqual((payload["no_op"], payload["commit"]), (True, None))

    def test_a_stage_completed_names_the_executor_model_hoko_env_sets(self):
        root = self.repo()
        self.makefile(root)
        plan = self.plan()
        self.open_run(plan)
        self.write(root, "a.py", "changed content\n")
        os.environ["HOKO_EXECUTOR_MODEL"] = "opencode-go/deepseek-v4-flash"

        self.run_in_process(root, plan, 1, message=VALID_MESSAGE)

        self.assertEqual(self.recorder.payloads("stage.completed")[-1]["model"],
                         "opencode-go/deepseek-v4-flash")

    def test_a_plan_without_a_run_writes_no_events(self):
        root = self.repo()
        self.makefile(root)
        plan = self.plan()
        self.write(root, "a.py", "changed content\n")
        code = self.run_in_process(root, plan, 1, message=VALID_MESSAGE)
        self.assertEqual(code, 0)
        self.assertEqual(self.recorder.events, [])


class TestRedGate(StepCommitTestCase):
    def test_a_red_unit_target_leaves_git_status_unchanged_and_head_unmoved(self):
        root = self.repo()
        self.makefile(root, unit="false")
        plan = self.plan()
        self.write(root, "a.py", "changed content\n")
        status_before = self.git(root, "status", "--short")
        head_before = self.head(root)
        proc = self.run_step_commit(root, plan, 1, message=VALID_MESSAGE)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertEqual(self.git(root, "status", "--short"), status_before)
        self.assertEqual(self.head(root), head_before)
        self.assertFalse(self.box_checked(plan, 1))


class TestUncheckedGate(StepCommitTestCase):
    def test_no_makefile_gives_a_commit_plus_a_gate_unchecked_line(self):
        root = self.repo()
        plan = self.plan()
        self.write(root, "a.py", "changed content\n")
        head_before = self.head(root)
        proc = self.run_step_commit(root, plan, 1, message=VALID_MESSAGE)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("gate: unchecked", proc.stdout)
        self.assertNotEqual(self.head(root), head_before)

    def test_an_unchecked_gate_still_commits_and_ticks_the_step(self):
        root = self.repo()
        plan = self.plan()
        self.write(root, "a.py", "changed content\n")
        proc = self.run_step_commit(root, plan, 1, message=VALID_MESSAGE)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue(self.box_checked(plan, 1))
        self.assertEqual(self.step_entry(plan, 1)["status"], "done")


class TestProtectedBranch(StepCommitTestCase):
    def test_a_main_branch_exits_non_zero_with_the_gate_never_run_and_head_unmoved(self):
        root = self.repo(branch="main")
        self.makefile(root, analyse="false")
        plan = self.plan()
        self.write(root, "a.py", "changed content\n")
        head_before = self.head(root)
        proc = self.run_step_commit(root, plan, 1, message=VALID_MESSAGE)
        self.assertEqual(proc.returncode, 3, proc.stdout + proc.stderr)
        self.assertNotIn("analyse:", proc.stdout)
        self.assertEqual(self.head(root), head_before)
        self.assertFalse(self.box_checked(plan, 1))

    def test_a_protected_branch_leaves_the_box_unticked_even_with_no_op(self):
        for branch in ("main", "master", "staging", "develop"):
            with self.subTest(branch=branch):
                root = self.repo(name=f"repo-{branch}", branch=branch)
                self.makefile(root)
                plan = self.plan(name=f"plan-{branch}.md")
                head_before = self.head(root)
                proc = self.run_step_commit(root, plan, 1, no_op="nothing needed")
                self.assertEqual(proc.returncode, 3, proc.stdout + proc.stderr)
                self.assertEqual(self.head(root), head_before)
                self.assertFalse(self.box_checked(plan, 1))
                self.assertFalse(os.path.exists(self.progress_path(plan)))


class TestMessageValidation(StepCommitTestCase):
    def test_a_bad_message_fails_each_broken_rule_by_name(self):
        root = self.repo()
        self.makefile(root)
        plan = self.plan()
        self.write(root, "a.py", "changed content\n")
        bad_message = (
            "Fix a bug without a full stop\n"
            "\n"
            "* " + ("y" * 71) + "\n"
            "Co-Authored-By: Someone <someone@example.com>\n"
        )
        proc = self.run_step_commit(root, plan, 1, message=bad_message)
        self.assertEqual(proc.returncode, 5, proc.stdout + proc.stderr)
        self.assertIn("summary", proc.stdout)
        self.assertIn("73 characters", proc.stdout)
        self.assertIn("trailer", proc.stdout)
        self.assertEqual(self.git(root, "status", "--short").strip(), "?? a.py")
        self.assertFalse(self.box_checked(plan, 1))


class TestTicketKey(StepCommitTestCase):
    def test_a_ticket_branch_gives_a_message_ending_in_the_ticket_key(self):
        root = self.repo(branch="feature/ABC-123-x")
        self.makefile(root)
        plan = self.plan()
        self.write(root, "a.py", "changed content\n")
        proc = self.run_step_commit(root, plan, 1, message=VALID_MESSAGE)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        logged = self.git(root, "log", "-1", "--pretty=%B")
        self.assertEqual(logged.rstrip("\n").splitlines()[-1], "ABC-123")

    def test_a_message_already_ending_in_the_ticket_key_is_not_given_it_twice(self):
        root = self.repo(branch="feature/ABC-123-x")
        self.makefile(root)
        plan = self.plan()
        self.write(root, "a.py", "changed content\n")
        message = VALID_MESSAGE + "\nABC-123\n"
        proc = self.run_step_commit(root, plan, 1, message=message)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        logged = self.git(root, "log", "-1", "--pretty=%B")
        self.assertEqual(logged.count("ABC-123"), 1)
        self.assertEqual(logged.rstrip("\n").splitlines()[-1], "ABC-123")


class TestNoOp(StepCommitTestCase):
    def test_no_op_on_a_clean_tree_ticks_with_head_unmoved(self):
        root = self.repo()
        self.makefile(root)
        plan = self.plan()
        head_before = self.head(root)
        proc = self.run_step_commit(root, plan, 1, no_op="nothing needed for this step")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("no-op: nothing needed for this step", proc.stdout)
        self.assertIn("tick: step 1", proc.stdout)
        self.assertEqual(self.head(root), head_before)
        self.assertTrue(self.box_checked(plan, 1))


class TestTreeModeMismatch(StepCommitTestCase):
    def test_a_clean_tree_in_message_mode_exits_non_zero_with_no_tick(self):
        root = self.repo()
        self.makefile(root)
        plan = self.plan()
        head_before = self.head(root)
        proc = self.run_step_commit(root, plan, 1, message=VALID_MESSAGE)
        self.assertEqual(proc.returncode, 4, proc.stdout + proc.stderr)
        self.assertEqual(self.head(root), head_before)
        self.assertFalse(self.box_checked(plan, 1))

    def test_a_dirty_tree_in_no_op_mode_exits_non_zero_with_no_tick(self):
        root = self.repo()
        self.makefile(root)
        plan = self.plan()
        self.write(root, "a.py", "changed content\n")
        head_before = self.head(root)
        proc = self.run_step_commit(root, plan, 1, no_op="nothing needed")
        self.assertEqual(proc.returncode, 4, proc.stdout + proc.stderr)
        self.assertEqual(self.head(root), head_before)
        self.assertFalse(self.box_checked(plan, 1))
        self.assertNotEqual(self.git(root, "status", "--short").strip(), "")


class TestFailingCommitHook(StepCommitTestCase):
    def test_a_failing_pre_commit_hook_exits_non_zero_with_no_tick(self):
        root = self.repo()
        self.makefile(root)
        plan = self.plan()
        self.write(root, "a.py", "changed content\n")
        hook_path = os.path.join(root, ".git", "hooks", "pre-commit")
        with open(hook_path, "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\nexit 1\n")
        os.chmod(hook_path, os.stat(hook_path).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        head_before = self.head(root)
        proc = self.run_step_commit(root, plan, 1, message=VALID_MESSAGE)
        self.assertEqual(proc.returncode, 6, proc.stdout + proc.stderr)
        self.assertEqual(self.head(root), head_before)
        self.assertFalse(self.box_checked(plan, 1))


if __name__ == "__main__":
    unittest.main()

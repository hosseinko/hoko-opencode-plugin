#!/usr/bin/env python3
"""Tests for plan-progress.py — a scratch plan file per case, driven through the CLI.

The events a command asks for are recorded at the event writer's seam, because the writer
is a separate module; the checklist, the `Base:` line and `progress.json` are exercised
through the subprocess.
"""

import argparse
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import progress
import settings
from test_plan_format import FENCED_LINES, plan_with_fenced_header_lines

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plan-progress.py")


def load_plan_progress():
    spec = importlib.util.spec_from_file_location("plan_progress", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RecordingEvents:
    """The event writer's seam, recording what a command asks it to write instead of
    appending to a run's `events.jsonl`."""

    BACKEND = "opencode"
    FILE = "events.jsonl"

    def __init__(self):
        self.events = []
        self.opened = False

    def forget(self):
        """Stops looking at the events already recorded; the run stays open."""
        self.events.clear()

    def ulid(self):
        return "01JAB3K9V6T2Q8M4ZC7XWYN5RD"

    def repo_root(self, start):
        return start

    def has_events(self, root, run_id):
        return self.opened

    def run_directory(self, root, run_id):
        return os.path.join(root, run_id)

    def files_changed_payload(self, root, base):
        return {"files": []}

    def emit(self, root, run_id, type_, payload):
        self.opened = True
        self.events.append({"run_id": run_id, "type": type_, "payload": payload})

    def types(self):
        return [event["type"] for event in self.events]


class StubSettings:
    """The settings a command reads, pinned so a developer's own hoko.json cannot decide
    an in-process case."""

    VALUES = {"journalPath": "", "loopLimit": 3}

    def get(self, key):
        return self.VALUES.get(key)


NO_PROGRESS = """\
# Some plan

## Goal

Do the thing.

## Steps

### 1. First step

- Files: `a.py`
- Change: do the first thing.

### 2. Second step

- Files: `b.py`
- Change: do the second thing.
"""

WITH_PROGRESS = """\
# Some plan

## Goal

Do the thing.

## Progress

- [x] 1. First step
- [ ] 2. Second step

## Steps

### 1. First step

- Files: `a.py`
- Change: do the first thing.

### 2. Second step

- Files: `b.py`
- Change: do the second thing.
"""

PROGRESS_AFTER_STEPS = """\
# Some plan

## Goal

Do the thing.

## Steps

### 1. First step

- Files: `a.py`
- Change: do the first thing.

### 2. Second step

- Files: `b.py`
- Change: do the second thing.

## Verification

Run the tests.

## Progress

- [x] 1. First step
"""

FENCED_STEP_EXAMPLE = """\
# Some plan

## Goal

Do the thing.

## Steps

### 1. First step

- Files: `a.py`
- Change: do the first thing. Example:

```
### 9. Not a real step
```

### 2. Second step

- Files: `b.py`
- Change: do the second thing.
"""

LEGACY_STATUS = """\
# Some plan

## Goal

Do the thing.

## Steps

### 1. First step

- Files: `a.py`
- Change: do the first thing.
- Status: done

### 2. Second step

- Files: `b.py`
- Change: do the second thing.
"""


class PlanProgressTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.env = {name: value for name, value in os.environ.items()
                    if not name.startswith("HOKO_")}
        self.env["TMPDIR"] = self.tmpdir.name
        self.env["HOME"] = self.tmpdir.name
        self.configure_journal(None)

    def write_plan(self, text, name="plan.md"):
        path = os.path.join(self.tmpdir.name, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def read_plan(self, path):
        with open(path, encoding="utf-8") as f:
            return f.read()

    def configure_journal(self, journal_path, analytics_path=""):
        """Home's hoko.json: the journal root (None keeps journaling off) and the analytics
        root, always pinned so no case writes into the real analytics folder."""
        config_dir = os.path.join(self.tmpdir.name, ".config", "opencode")
        os.makedirs(config_dir, exist_ok=True)
        settings = {"analyticsPath": analytics_path}
        if journal_path is not None:
            settings["journalPath"] = journal_path
        with open(os.path.join(config_dir, "hoko.json"), "w", encoding="utf-8") as f:
            json.dump(settings, f)

    def write_report(self, name, text):
        path = os.path.join(self.tmpdir.name, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def run_progress(self, *args, input=None):
        return subprocess.run(
            [sys.executable, SCRIPT, *args], capture_output=True, text=True, env=self.env,
            cwd=self.tmpdir.name, input=input,
        )

    def read_progress_json(self, plan):
        with open(os.path.splitext(plan)[0] + ".progress.json", encoding="utf-8") as f:
            return json.load(f)

    def write_progress_json(self, plan, document):
        with open(os.path.splitext(plan)[0] + ".progress.json", "w", encoding="utf-8") as f:
            json.dump(document, f)

    def steps_of(self, document):
        return {step["n"]: step for step in document["rounds"][0]["steps"]}


class TestInitWithNoProgressSection(PlanProgressTestCase):
    def test_init_writes_one_unchecked_box_per_step_above_the_steps_section(self):
        plan = self.write_plan(NO_PROGRESS)
        proc = self.run_progress("init", "--plan", plan)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        text = self.read_plan(plan)
        self.assertIn("## Progress\n\n- [ ] 1. First step\n- [ ] 2. Second step\n", text)
        self.assertLess(text.index("## Progress"), text.index("## Steps"))


class TestInitReconciles(PlanProgressTestCase):
    def test_init_keeps_every_already_ticked_box_and_leaves_the_unticked_one(self):
        plan = self.write_plan(WITH_PROGRESS)
        proc = self.run_progress("init", "--plan", plan)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        text = self.read_plan(plan)
        self.assertIn("- [x] 1. First step", text)
        self.assertIn("- [ ] 2. Second step", text)

    def test_init_adds_only_the_box_a_step_is_missing(self):
        missing = WITH_PROGRESS.replace("- [ ] 2. Second step\n", "")
        plan = self.write_plan(missing)
        proc = self.run_progress("init", "--plan", plan)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        text = self.read_plan(plan)
        self.assertIn("- [x] 1. First step", text)
        self.assertIn("- [ ] 2. Second step", text)

    def test_init_twice_leaves_the_section_as_the_first_call_wrote_it(self):
        plan = self.write_plan(NO_PROGRESS)
        self.run_progress("init", "--plan", plan)
        once = self.read_plan(plan)
        proc = self.run_progress("init", "--plan", plan)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.read_plan(plan), once)

    def test_init_drops_a_legacy_status_done_line_and_checks_its_box(self):
        plan = self.write_plan(LEGACY_STATUS)
        proc = self.run_progress("init", "--plan", plan)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        text = self.read_plan(plan)
        self.assertNotIn("Status: done", text)
        self.assertIn("- [x] 1. First step", text)
        self.assertIn("- [ ] 2. Second step", text)


class TestFenceScoping(PlanProgressTestCase):
    """A `### N.` heading inside a fenced code example is not a real step."""

    def test_a_fenced_step_heading_inside_a_step_body_is_not_counted(self):
        plan = self.write_plan(FENCED_STEP_EXAMPLE)
        proc = self.run_progress("init", "--plan", plan)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        text = self.read_plan(plan)
        self.assertIn("## Progress\n\n- [ ] 1. First step\n- [ ] 2. Second step\n", text)
        self.assertNotIn("[ ] 9.", text)


class TestInitWithProgressAfterSteps(PlanProgressTestCase):
    def test_init_leaves_exactly_one_steps_and_one_verification_section(self):
        plan = self.write_plan(PROGRESS_AFTER_STEPS)
        proc = self.run_progress("init", "--plan", plan)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        text = self.read_plan(plan)
        self.assertEqual(text.count("## Steps"), 1)
        self.assertEqual(text.count("## Verification"), 1)

    def test_init_keeps_progress_last_and_reconciles_its_boxes(self):
        plan = self.write_plan(PROGRESS_AFTER_STEPS)
        proc = self.run_progress("init", "--plan", plan)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        text = self.read_plan(plan)
        self.assertTrue(text.rstrip("\n").endswith("- [ ] 2. Second step"))
        self.assertGreater(text.index("## Progress"), text.index("## Verification"))
        self.assertIn("- [x] 1. First step", text)
        self.assertIn("- [ ] 2. Second step", text)


class TestTick(PlanProgressTestCase):
    def test_tick_leaves_the_rest_of_the_file_byte_identical(self):
        plan = self.write_plan(WITH_PROGRESS)
        proc = self.run_progress("tick", "--plan", plan, "--step", "2")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        text = self.read_plan(plan)
        expected = WITH_PROGRESS.replace("- [ ] 2. Second step", "- [x] 2. Second step")
        self.assertEqual(text, expected)

    def test_tick_checks_only_the_named_steps_box(self):
        plan = self.write_plan(WITH_PROGRESS)
        proc = self.run_progress("tick", "--plan", plan, "--step", "2")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        text = self.read_plan(plan)
        self.assertIn("- [x] 1. First step", text)
        self.assertIn("- [x] 2. Second step", text)

    def test_tick_on_a_plan_with_no_progress_section_exits_non_zero(self):
        plan = self.write_plan(NO_PROGRESS)
        proc = self.run_progress("tick", "--plan", plan, "--step", "1")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("no `## Progress` section", proc.stderr)


class TestInitRecordsBase(PlanProgressTestCase):
    def make_repo(self):
        subprocess.run(["git", "init", "-q", self.tmpdir.name], check=True, env=self.env)
        subprocess.run(["git", "-C", self.tmpdir.name, "config", "user.email", "t@example.com"],
                        check=True, env=self.env)
        subprocess.run(["git", "-C", self.tmpdir.name, "config", "user.name", "t"],
                        check=True, env=self.env)

    def commit(self, message):
        subprocess.run(["git", "-C", self.tmpdir.name, "add", "-A"], check=True, env=self.env)
        subprocess.run(["git", "-C", self.tmpdir.name, "commit", "-q", "-m", message],
                        check=True, env=self.env)

    def head(self):
        result = subprocess.run(["git", "-C", self.tmpdir.name, "rev-parse", "HEAD"],
                                 capture_output=True, text=True, check=True, env=self.env)
        return result.stdout.strip()

    def test_init_records_base_from_head(self):
        self.make_repo()
        plan = self.write_plan(NO_PROGRESS)
        self.commit("first")
        sha = self.head()
        proc = self.run_progress("init", "--plan", plan)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        text = self.read_plan(plan)
        self.assertIn(f"Base: {sha}", text)

    def test_base_stays_fixed_across_a_later_init_even_after_head_moves(self):
        self.make_repo()
        plan = self.write_plan(NO_PROGRESS)
        self.commit("first")
        first_sha = self.head()
        self.run_progress("init", "--plan", plan)

        with open(plan, "a", encoding="utf-8") as f:
            f.write("\n")
        self.commit("second")
        second_sha = self.head()
        self.assertNotEqual(first_sha, second_sha)

        proc = self.run_progress("init", "--plan", plan)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        text = self.read_plan(plan)
        self.assertEqual(text.count("Base: "), 1)
        self.assertIn(f"Base: {first_sha}", text)
        self.assertNotIn(second_sha, text)

    def test_init_writes_the_base_line_into_the_header_when_a_fence_quotes_one(self):
        self.make_repo()
        plan = self.write_plan(plan_with_fenced_header_lines())
        self.commit("first")
        sha = self.head()
        proc = self.run_progress("init", "--plan", plan)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        text = self.read_plan(plan)
        self.assertTrue(text.startswith(f"# Plan\nBase: {sha}\n"), text)
        self.assertEqual(text.count(FENCED_LINES), 1)


class TestComplete(PlanProgressTestCase):
    def test_complete_sets_status_complete_and_files_the_report_next_to_the_round(self):
        round_dir = os.path.join(self.tmpdir.name, "journal", "some-project", "20260101-0000-thing")
        os.makedirs(round_dir)
        self.configure_journal(os.path.join(self.tmpdir.name, "journal"))
        plan = self.write_plan(f"Journal: {os.path.join(round_dir, 'plan-01.md')}\n\n" + NO_PROGRESS)
        report = self.write_report("report.md", "All 2 steps done.\n")

        proc = self.run_progress("complete", "--plan", plan, "--report-file", report)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

        text = self.read_plan(plan)
        self.assertIn("Status: complete", text)

        report_path = os.path.join(round_dir, "report-01.md")
        self.assertTrue(os.path.isfile(report_path))
        with open(report_path, encoding="utf-8") as f:
            self.assertEqual(f.read(), "All 2 steps done.\n")
        self.assertIn(report_path, proc.stdout)

    def test_complete_writes_the_status_line_into_the_header_when_a_fence_quotes_one(self):
        round_dir = os.path.join(self.tmpdir.name, "journal", "some-project", "20260101-0000-thing")
        os.makedirs(round_dir)
        self.configure_journal(os.path.join(self.tmpdir.name, "journal"))
        quoting = plan_with_fenced_header_lines(f"Journal: {os.path.join(round_dir, 'plan-01.md')}\n")
        plan = self.write_plan(quoting.replace("Status: complete\n", "Status: open\n"))
        report = self.write_report("report.md", "All done.\n")

        proc = self.run_progress("complete", "--plan", plan, "--report-file", report)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

        text = self.read_plan(plan)
        self.assertTrue(text.startswith(f"# Plan\nJournal: {os.path.join(round_dir, 'plan-01.md')}\nStatus: complete\n"), text)
        self.assertIn(FENCED_LINES.replace("Status: complete\n", "Status: open\n"), text)
        self.assertTrue(os.path.isfile(os.path.join(round_dir, "report-01.md")))

    def test_complete_reads_the_report_from_stdin(self):
        round_dir = os.path.join(self.tmpdir.name, "journal", "some-project", "20260102-0000-thing")
        os.makedirs(round_dir)
        self.configure_journal(os.path.join(self.tmpdir.name, "journal"))
        plan = self.write_plan(f"Journal: {os.path.join(round_dir, 'plan-01.md')}\n\n" + NO_PROGRESS,
                                name="plan-stdin.md")

        proc = subprocess.run(
            [sys.executable, SCRIPT, "complete", "--plan", plan, "--report-file", "-"],
            input="Done via stdin.\n", capture_output=True, text=True, env=self.env,
            cwd=self.tmpdir.name,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

        report_path = os.path.join(round_dir, "report-01.md")
        with open(report_path, encoding="utf-8") as f:
            self.assertEqual(f.read(), "Done via stdin.\n")

    def test_complete_with_a_broken_sessions_file_still_exits_zero_with_a_note(self):
        round_dir = os.path.join(self.tmpdir.name, "journal", "some-project", "20260104-0000-thing")
        os.makedirs(round_dir)
        self.configure_journal(os.path.join(self.tmpdir.name, "journal"))
        plan = self.write_plan(f"Journal: {os.path.join(round_dir, 'plan-01.md')}\n\n" + NO_PROGRESS,
                               name="plan-broken.md")
        report = self.write_report("report-broken.md", "Done.\n")
        with open(os.path.join(round_dir, "sessions.json"), "w", encoding="utf-8") as f:
            f.write("{not json")

        proc = self.run_progress("complete", "--plan", plan, "--report-file", report)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("invoice not written", proc.stderr)
        self.assertTrue(os.path.isfile(os.path.join(round_dir, "report-01.md")))

    def test_complete_when_journaling_is_off_only_sets_status(self):
        self.configure_journal("")
        plan = self.write_plan(NO_PROGRESS, name="plan-no-journal.md")
        report = self.write_report("report-off.md", "Done.\n")

        proc = self.run_progress("complete", "--plan", plan, "--report-file", report)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

        text = self.read_plan(plan)
        self.assertIn("Status: complete", text)
        self.assertIn("journaling is off", proc.stdout)

    def test_complete_marks_the_run_done_with_journaling_off(self):
        self.configure_journal("")
        plan = self.write_plan(WITH_PROGRESS, name="plan-closing.md")
        report = self.write_report("report-closing.md", "Done.\n")
        proc = self.run_progress("complete", "--plan", plan, "--report-file", report)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.read_progress_json(plan)["status"], "done")


class TestProgressJson(PlanProgressTestCase):
    def test_init_writes_a_progress_json_with_one_pending_entry_per_step(self):
        plan = self.write_plan(NO_PROGRESS)
        proc = self.run_progress("init", "--plan", plan)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

        document = self.read_progress_json(plan)
        self.assertEqual(document["version"], 1)
        self.assertEqual(document["task"], "plan")
        self.assertEqual(document["rounds"][0]["plan"], "plan.md")
        steps = document["rounds"][0]["steps"]
        self.assertEqual([(s["n"], s["title"], s["status"]) for s in steps],
                         [(1, "First step", "pending"), (2, "Second step", "pending")])

    def test_start_marks_the_step_in_progress_and_leaves_the_other_pending(self):
        plan = self.write_plan(NO_PROGRESS)
        self.run_progress("init", "--plan", plan)
        proc = self.run_progress("start", "--plan", plan, "--step", "2")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

        document = self.read_progress_json(plan)
        steps = self.steps_of(document)
        self.assertEqual(steps[1]["status"], "pending")
        self.assertEqual(steps[2]["status"], "in_progress")
        self.assertIsNotNone(steps[2]["started"])
        self.assertEqual(document["status"], "in_progress")

    def test_start_on_a_step_the_plan_does_not_have_exits_non_zero(self):
        plan = self.write_plan(NO_PROGRESS)
        self.run_progress("init", "--plan", plan)
        proc = self.run_progress("start", "--plan", plan, "--step", "9")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("no step 9", proc.stderr)

    def test_tick_sets_the_step_done_with_its_commit_and_note(self):
        plan = self.write_plan(WITH_PROGRESS)
        self.run_progress("init", "--plan", plan)
        proc = self.run_progress("tick", "--plan", plan, "--step", "2", "--commit", "abc1234")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

        step = self.steps_of(self.read_progress_json(plan))[2]
        self.assertEqual(step["status"], "done")
        self.assertEqual(step["commit"], "abc1234")
        self.assertIsNotNone(step["finished"])

    def test_tick_works_without_a_progress_json_beforehand(self):
        plan = self.write_plan(WITH_PROGRESS)
        proc = self.run_progress("tick", "--plan", plan, "--step", "2", "--note", "already done")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

        steps = self.steps_of(self.read_progress_json(plan))
        self.assertEqual(steps[1]["status"], "done")
        self.assertEqual(steps[2]["note"], "already done")

    def test_a_disagreeing_progress_json_takes_its_statuses_from_the_checklist_and_keeps_the_rest(self):
        plan = self.write_plan(WITH_PROGRESS)
        self.run_progress("init", "--plan", plan)
        document = self.read_progress_json(plan)
        document["run_id"] = "01JAB3K9V6T2Q8M4ZC7XWYN5RD"
        steps = self.steps_of(document)
        steps[1].update(status="pending", commit="9b1e0d2", started="2026-10-21T15:31:02.114Z")
        steps[2].update(status="done", commit="7c3d4e5", note="kept")
        self.write_progress_json(plan, document)

        proc = self.run_progress("init", "--plan", plan)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

        reconciled = self.read_progress_json(plan)
        self.assertEqual(reconciled["run_id"], "01JAB3K9V6T2Q8M4ZC7XWYN5RD")
        steps = self.steps_of(reconciled)
        self.assertEqual(steps[1]["status"], "done")
        self.assertEqual(steps[1]["commit"], "9b1e0d2")
        self.assertEqual(steps[1]["started"], "2026-10-21T15:31:02.114Z")
        self.assertEqual(steps[2]["status"], "pending")
        self.assertEqual(steps[2]["commit"], "7c3d4e5")
        self.assertEqual(steps[2]["note"], "kept")

    def test_an_unparsable_progress_json_is_rebuilt_from_the_plan(self):
        plan = self.write_plan(WITH_PROGRESS)
        with open(os.path.splitext(plan)[0] + ".progress.json", "w", encoding="utf-8") as f:
            f.write("{not json")
        proc = self.run_progress("init", "--plan", plan)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        steps = self.steps_of(self.read_progress_json(plan))
        self.assertEqual([steps[1]["status"], steps[2]["status"]], ["done", "pending"])


class TestAbort(PlanProgressTestCase):
    def test_abort_marks_the_run_stopped(self):
        plan = self.write_plan(NO_PROGRESS)
        self.run_progress("init", "--plan", plan)
        self.run_progress("start", "--plan", plan, "--step", "1")
        proc = self.run_progress("abort", "--plan", plan, "--reason", "-",
                                 input="Step 1 hit a blocker.\n")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.read_progress_json(plan)["status"], "stopped")

    def test_abort_on_a_plan_never_started_still_exits_zero(self):
        plan = self.write_plan(NO_PROGRESS)
        proc = self.run_progress("abort", "--plan", plan, "--reason", "the project was red")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.read_progress_json(plan)["status"], "stopped")


class TestRunEvents(PlanProgressTestCase):
    """The events a command asks the writer for, recorded at its seam."""

    def setUp(self):
        super().setUp()
        self.module = load_plan_progress()
        self.recorder = RecordingEvents()
        for patcher in (mock.patch.object(progress, "events", self.recorder),
                        mock.patch.object(self.module, "events", self.recorder),
                        mock.patch.object(self.module, "analytics", mock.Mock()),
                        mock.patch.object(settings, "get", StubSettings().get)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def started_plan(self):
        plan = self.write_plan(NO_PROGRESS)
        self.module.cmd_init(argparse.Namespace(plan=plan))
        return plan

    def test_start_appends_one_stage_started_naming_the_step(self):
        plan = self.started_plan()
        self.recorder.forget()
        self.module.cmd_start(argparse.Namespace(plan=plan, step=2))

        started = [event for event in self.recorder.events if event["type"] == "stage.started"]
        self.assertEqual(len(started), 1)
        self.assertEqual({key: started[0]["payload"][key]
                          for key in ("stage", "cycle", "step", "steps", "title", "round")},
                         {"stage": "Implement", "cycle": 1, "step": 2, "steps": 2,
                          "title": "Second step", "round": 1})

    def test_repeated_starts_append_stage_started_once_each_and_open_the_run_once(self):
        plan = self.started_plan()
        for step in (1, 2, 2):
            self.module.cmd_start(argparse.Namespace(plan=plan, step=step))
        self.assertEqual(self.recorder.types(),
                         ["run.started", "stage.started", "stage.started", "stage.started"])

    def test_complete_appends_files_changed_then_run_finished_done(self):
        plan = self.started_plan()
        report = self.write_report("report.md", "Done.\n")
        self.module.cmd_start(argparse.Namespace(plan=plan, step=1))
        self.recorder.forget()

        with contextlib.redirect_stdout(io.StringIO()):
            self.module.cmd_complete(argparse.Namespace(plan=plan, report_file=report))

        self.assertEqual(self.recorder.types(), ["files.changed", "run.finished"])
        self.assertEqual(self.recorder.events[-1]["payload"], {"status": "done"})

    def test_abort_appends_stage_failed_then_run_finished_failed(self):
        plan = self.started_plan()
        self.module.cmd_start(argparse.Namespace(plan=plan, step=1))
        self.recorder.forget()

        self.module.cmd_abort(argparse.Namespace(plan=plan, stage="QA", reason="gate not ready"))

        self.assertEqual(self.recorder.types(), ["stage.failed", "run.finished"])
        self.assertEqual({key: self.recorder.events[0]["payload"][key]
                          for key in ("stage", "cycle", "reason")},
                         {"stage": "QA", "cycle": 1, "reason": "gate not ready"})
        self.assertEqual(self.recorder.events[1]["payload"],
                         {"status": "failed", "reason": "gate not ready"})

    def test_abort_before_any_step_started_opens_the_run_first(self):
        plan = self.started_plan()
        self.module.cmd_abort(argparse.Namespace(plan=plan, stage="Implement",
                                                 reason="the project was red"))
        self.assertEqual(self.recorder.types(),
                         ["run.started", "stage.failed", "run.finished"])


if __name__ == "__main__":
    unittest.main()

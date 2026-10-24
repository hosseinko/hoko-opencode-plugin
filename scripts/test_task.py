#!/usr/bin/env python3
"""Tests for task.py — a scratch git repo per case, whole flows driven through the CLI
from canned hand-off files, every event checked against the committed event schema."""

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from datetime import datetime, timedelta, timezone

from test_events import assert_valid_events, read_events

SCRIPTS = Path(__file__).resolve().parent
SCRIPT = str(SCRIPTS / "task.py")
PROGRESS_SCRIPT = str(SCRIPTS / "plan-progress.py")

LEAN_PLAN = """\
# {title}

## Goal

Do the thing.

## Steps

{steps}"""

LEAN_STEP = """\
### {n}. Step {n}

- Change: do thing {n}.
- Tests: prove thing {n}.

"""


def finding(severity="important", summary="Guard the null case", file="src/a.py", line=3):
    return {"severity": severity, "file": file, "line": line, "summary": summary,
            "fix": "Check for null first.", "scenario": "A null input crashes."}


class TaskTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.home = os.path.join(self.tmpdir.name, "home")
        os.makedirs(os.path.join(self.home, ".config", "opencode"))
        self.write_hoko({"journalPath": ""})
        self.env = dict(os.environ)
        self.env["HOME"] = self.home
        self.env["TMPDIR"] = self.tmpdir.name
        self.env["GIT_AUTHOR_NAME"] = "Test"
        self.env["GIT_AUTHOR_EMAIL"] = "test@example.com"
        self.env["GIT_COMMITTER_NAME"] = "Test"
        self.env["GIT_COMMITTER_EMAIL"] = "test@example.com"
        for key in [k for k in self.env if k.startswith("HOKO_")]:
            del self.env[key]
        self.env["HOKO_STATE_DIR"] = os.path.join(self.tmpdir.name, "state")
        self.env["HOKO_PLAN_GATE"] = "false"
        self.repo = os.path.realpath(self.make_repo())
        self.qa_results = []
        self.review_results = []
        self.scope = {}

    def write_hoko(self, settings):
        with open(os.path.join(self.home, ".config", "opencode", "hoko.json"), "w", encoding="utf-8") as handle:
            json.dump({"analyticsPath": "", **settings}, handle)

    def git(self, *args, cwd=None):
        result = subprocess.run(["git", *args], cwd=cwd or self.repo, capture_output=True, text=True,
                                env=self.env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def make_repo(self, branch="feature/task-test"):
        path = os.path.join(self.tmpdir.name, "my-repo")
        os.makedirs(path)
        self.git("init", "-q", cwd=path)
        self.git("checkout", "-q", "-b", branch, cwd=path)
        Path(path, ".gitkeep").write_text("")
        self.git("add", ".gitkeep", cwd=path)
        self.git("commit", "-q", "-m", "initial", cwd=path)
        return path

    def run_task(self, *args, input=None):
        return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True,
                              env=self.env, cwd=self.repo, input=input)

    def ok(self, *args, input=None):
        result = self.run_task(*args, input=input)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout) if result.stdout.strip() else None

    def start(self, title="Fix login redirect", prompt="Fix the login redirect.", *extra):
        return self.ok("start", "--title", title, "--prompt-file", "-", *extra, input=prompt)

    def next(self, folder, *extra):
        return self.ok("next", "--task", folder, *extra)

    def record(self, folder, stage, *extra):
        return self.ok("record", "--task", folder, "--stage", stage, *extra)

    def answer(self, folder, answers):
        return self.ok("answer", "--task", folder, "--answer-file", "-", input=json.dumps(answers))

    def progress(self, folder):
        return json.loads(Path(folder, "progress.json").read_text(encoding="utf-8"))

    def events(self, folder):
        run_id = self.progress(folder)["run_id"]
        return assert_valid_events(self, Path(self.repo, ".ai", "runs", run_id, "events.jsonl"))

    def types(self, folder):
        return [event["type"] for event in self.events(folder)]

    def put(self, folder, name, data):
        Path(folder, name).write_text(json.dumps(data), encoding="utf-8")

    def scope_handoff(self, **changes):
        data = {"stage": "Refine", "status": "ok", "summary": "scoped", "questions": [], "decisions": [],
                "title": "Fix login redirect", "size": "small",
                "impact": {"areas": ["auth"], "files": ["src/a.py"], "contracts": []},
                "needs_spec": False, "needs_plan": True, "ticket": None, "unknowns": []}
        data.update(self.scope)
        data.update(changes)
        return data

    def spec_handoff(self, **changes):
        data = {"stage": "Spec", "status": "ok", "summary": "spec written", "questions": [], "decisions": [],
                "paths": ["specs/login.md"], "ids": ["SPEC-007/REQ-1"]}
        data.update(changes)
        return data

    def plan_handoff(self, **changes):
        data = {"stage": "Plan", "status": "ok", "summary": "planned", "questions": [], "decisions": [],
                "plan": "plan-01.md", "invalidates": [], "reason": ""}
        data.update(changes)
        return data

    def qa_handoff(self, verdict="green", findings=(), gates=None):
        return {"verdict": verdict, "findings": list(findings), "debt": [],
                "gates": gates if gates is not None else
                [{"check": "tests", "status": "passed", "exit_code": 0, "duration_ms": 12}]}

    def record_session(self, session_id, calls=(), entry=None, transcript=True):
        """The session recorded against the project, as the plugin records it, and, when
        `entry` is given, its assistant responses in the entry's analytics folder
        (`usage.json`): one for the main session plus one per `(agent, moment)` in `calls`,
        each reporting 100 input and 50 output tokens. `transcript=False` writes the row
        the plugin records for a session opencode holds no transcript path for."""
        path = Path(self.tmpdir.name, "projects", f"{session_id}.jsonl")
        if transcript:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}\n", encoding="utf-8")
        code = ("import sys; sys.path.insert(0, sys.argv[1]); import journal\n"
                "journal.record_session(sys.argv[2], sys.argv[3], sys.argv[4])\n")
        recorded = subprocess.run([sys.executable, "-c", code, str(SCRIPTS), self.repo, session_id,
                                   str(path) if transcript else ""],
                                  capture_output=True, text=True, env=self.env)
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        if entry is not None:
            moment = calls[0][1] if calls else None
            rows = [self.usage_row(session_id, "main", moment)]
            rows += [self.usage_row(session_id, agent, moment) for agent, moment in calls]
            # The plugin writes usage into the entry's analytics folder (analytics.py), not
            # beside it; a folder the analytics path blocks takes that write with it, which
            # is the case the unwritable-folder test covers.
            code = ("import json, sys; sys.path.insert(0, sys.argv[1]); import analytics, invoice\n"
                    "try:\n"
                    "    folder = analytics.folder_for(sys.argv[2])\n"
                    "    folder.mkdir(parents=True, exist_ok=True)\n"
                    "    usage = folder / invoice.USAGE_FILE\n"
                    "    written = json.loads(usage.read_text()) if usage.is_file() else []\n"
                    "    usage.write_text(json.dumps(written + json.loads(sys.argv[3])))\n"
                    "except OSError:\n"
                    "    pass\n")
            written = subprocess.run([sys.executable, "-c", code, str(SCRIPTS), entry, json.dumps(rows)],
                                     capture_output=True, text=True, env=self.env)
            self.assertEqual(written.returncode, 0, written.stdout + written.stderr)
        return path

    def usage_row(self, session_id, agent, moment):
        return {"session_id": session_id, "time": moment, "agent": agent,
                "model": "opencode-go/glm-5.3-flash", "provider": "opencode-go",
                "input": 100, "output": 50, "reasoning": 0, "cache_read": 0, "cache_write": 0,
                "cost": 0.0}

    def write_lean_plan(self, folder, steps=2, title="Fix login redirect"):
        body = "".join(LEAN_STEP.format(n=n) for n in range(1, steps + 1))
        Path(folder, "plan-01.md").write_text(LEAN_PLAN.format(title=title, steps=body), encoding="utf-8")

    def tick_all(self, action):
        for step in range(action["step"], action["steps"] + 1):
            result = subprocess.run([sys.executable, PROGRESS_SCRIPT, "tick", "--plan", action["plan"],
                                     "--step", str(step), "--note", "no change needed"],
                                    capture_output=True, text=True, env=self.env)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def drive(self, folder, *stop_at, until=None):
        """Answers every action the way a well-behaved conductor would — canned hand-offs,
        a green fast gate, every step ticked — until an action of kind `stop_at` comes
        back, or `until(action)` holds."""
        for _ in range(60):
            action = self.next(folder)
            kind = action["action"]
            if kind in stop_at or (until is not None and until(action)):
                return action
            if kind == "preflight":
                self.record(folder, "Preflight", "--exit-code", "0")
            elif kind == "step":
                self.tick_all(action)
            elif kind == "spawn":
                self.answer_spawn(folder, action)
            else:
                self.fail(f"unexpected action {action}")
        self.fail("the flow did not settle")

    def answer_spawn(self, folder, action):
        stage = action["stage"]
        if stage == "Refine":
            self.put(folder, "scope.json", self.scope_handoff())
        elif stage == "Spec":
            self.put(folder, "spec.json", self.spec_handoff())
        elif stage == "Plan":
            self.write_lean_plan(folder)
            self.put(folder, "plan.json", self.plan_handoff())
        elif stage == "QA":
            result = self.qa_results.pop(0) if self.qa_results else self.qa_handoff()
            self.put(folder, f"qa-{self.progress(folder)['cycle']:02d}.json", result)
        else:
            result = self.review_results.pop(0) if self.review_results else []
            self.put(folder, f"review-{self.progress(folder)['cycle']:02d}.json", result)
        self.record(folder, stage)


def spawns(stage):
    return lambda action: action["action"] == "spawn" and action["stage"] == stage


def starts_cycle(number):
    return lambda action: action["action"] == "step" and action["cycle"] == number


STEPLESS_PLAN = "# Forwarded plan\n\n## Goal\n\nDo the thing.\n"
FORWARDED_RUN = "01JAB3K9V6T2Q8M4ZC7XWYN5RD"


class RefusedStart:
    def stepless_plan(self, text=STEPLESS_PLAN):
        path = os.path.join(self.repo, "stepless.md")
        Path(path).write_text(text, encoding="utf-8")
        Path(self.repo, "stepless.progress.json").write_text(json.dumps({"run_id": FORWARDED_RUN}))
        return path

    def refuse(self, plan):
        result = self.run_task("start", "--title", "Forwarded plan", "--prompt-file", "-", "--plan", plan,
                               input="Run this plan.")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("is not a plan this pipeline can run", result.stderr)

    def assert_no_task_folder_or_events(self):
        plans = os.path.join(self.repo, ".ai", "plans")
        self.assertEqual(os.listdir(plans) if os.path.isdir(plans) else [], [])
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".ai", "runs", FORWARDED_RUN)))


class TestStart(RefusedStart, TaskTestCase):
    def test_start_creates_a_stamped_folder_with_a_slug_of_at_most_40_characters(self):
        title = "Rework the entire authentication redirect handling for expired sessions"
        folder = self.start(title)["dir"]
        name = os.path.basename(folder)
        self.assertRegex(name, r"^\d{8}-\d{4}-[a-z0-9-]+$")
        self.assertLessEqual(len(name[len("20261021-1530-"):]), 40)
        self.assertTrue(name.startswith(self.stamp_prefix(name)))
        self.assertEqual(os.path.dirname(folder), os.path.join(self.repo, ".ai", "plans"))
        self.assertEqual(Path(folder, "prompt.md").read_text(), "Fix the login redirect.\n")

    def stamp_prefix(self, name):
        return re.match(r"^\d{8}-\d{4}-", name).group(0)

    def test_a_second_task_with_the_same_title_in_the_same_minute_gets_a_numbered_folder(self):
        first = self.start()["dir"]
        second = self.start()["dir"]
        self.assertNotEqual(first, second)
        self.assertTrue(os.path.isdir(first) and os.path.isdir(second))

    def test_start_writes_progress_json_and_ignores_the_plans_directory(self):
        folder = self.start()["dir"]
        document = self.progress(folder)
        self.assertEqual((document["status"], document["stage"], document["cycle"], document["loop_limit"]),
                         ("in_progress", "Refine", 1, 3))
        self.assertEqual(document["title"], "Fix login redirect")
        self.assertEqual(document["base"], self.git("rev-parse", "HEAD").strip())
        self.assertRegex(document["run_id"], r"^[0-9A-Z]{26}$")
        self.assertEqual(set(document["stages"]), {"Refine", "Spec", "Plan", "Implement", "QA", "Review"})
        self.assertEqual(self.git("status", "--short", "--", ".ai/plans"), "")
        self.assertEqual(subprocess.run(["git", "-C", self.repo, "check-ignore", "-q", ".ai/plans/x.md"]).returncode, 0)

    def test_r3_run_started_carries_the_named_models_and_no_effort(self):
        self.env["HOKO_EXECUTOR_MODEL"] = "opencode-go/deepseek-v4-flash"
        folder = self.start()["dir"]
        started = self.events(folder)[0]
        self.assertEqual(started["type"], "run.started")
        self.assertEqual(started["payload"]["source"], "prompt")
        self.assertEqual(started["payload"]["text"], "Fix the login redirect.")
        self.assertEqual(started["payload"]["models"], {"Implement": "opencode-go/deepseek-v4-flash"})
        self.assertNotIn("efforts", started["payload"])
        self.assertNotIn("effort", started["payload"])
        self.assertEqual(started["payload"]["loop_limit"], 3)

    def test_start_refuses_when_git_tracks_the_plans_directory(self):
        Path(self.repo, ".ai", "plans").mkdir(parents=True)
        Path(self.repo, ".ai", "plans", "old.md").write_text("# old\n")
        self.git("add", "-f", ".ai/plans/old.md")
        self.git("commit", "-q", "-m", "track plans")
        result = self.run_task("start", "--title", "A task", "--prompt-file", "-", input="Do it.")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("tracked by git", result.stderr)
        self.assertEqual(os.listdir(os.path.join(self.repo, ".ai", "plans")), ["old.md"])

    def test_start_ignores_the_plans_directory_even_when_the_repo_tracks_other_files_beside_it(self):
        Path(self.repo, ".ai").mkdir()
        Path(self.repo, ".ai", "settings.json").write_text("{}\n")
        self.git("add", "-f", ".ai/settings.json")
        self.git("commit", "-q", "-m", "track settings")
        folder = self.start()["dir"]
        self.assertEqual(self.git("status", "--short", "--", ".ai/plans"), "")
        self.assertTrue(os.path.isdir(folder))

    def test_R1_R4_a_plan_that_plan_progress_refuses_leaves_no_task_folder_and_writes_no_events(self):
        self.refuse(self.stepless_plan())
        self.assert_no_task_folder_or_events()

    def test_start_refuses_an_empty_prompt(self):
        result = self.run_task("start", "--title", "A task", "--prompt-file", "-", input="  \n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("prompt is empty", result.stderr)


SPEC_FILE = """\
---
id: SPEC-007
title: Login
---

# Login

## Requirements

- **REQ-1** When the user logs in, the login service shall redirect to the page asked for.
- **REQ-2** The login service shall refuse a redirect to another host.
- **REQ-3** _Retired._
"""


class TestStartFromSpec(TaskTestCase):
    def write_spec(self, text=SPEC_FILE, name="specs/login.md"):
        path = Path(self.repo, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return name

    def start_spec(self, spec="specs/login.md", title="Login redirect", *extra):
        return self.run_task("start", "--title", title, "--prompt-file", "-", "--spec", spec, *extra,
                             input="Implement the login spec.")

    def started(self, **kwargs):
        self.write_spec(**kwargs)
        result = self.start_spec()
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)["dir"]

    def test_R17_a_spec_start_marks_refine_and_spec_skipped_and_spawns_plan_next(self):
        folder = self.started()
        stages = self.progress(folder)["stages"]
        self.assertEqual((stages["Refine"], stages["Spec"], stages["Plan"]), ("skipped", "skipped", "pending"))
        skipped = [e["payload"]["stage"] for e in self.events(folder)
                   if e["type"] == "stage.completed" and e["payload"]["outcome"] == "skipped"]
        self.assertEqual(skipped, ["Refine", "Spec"])
        self.assertEqual(self.next(folder)["action"], "preflight")
        self.record(folder, "Preflight", "--exit-code", "0")
        action = self.next(folder)
        self.assertEqual((action["action"], action["stage"], action["agent"]), ("spawn", "Plan", "hoko-planner"))
        self.assertIn(str(Path(folder, "spec.json")), action["prompt"])
        self.assertNotIn("scope.json", action["prompt"])

    def test_R17_a_spec_start_runs_the_pipeline_through_to_finish(self):
        folder = self.started()
        self.drive(folder, "finish")
        document = self.progress(folder)
        self.assertEqual((document["source"], document["spec"]), ("spec", ["specs/login.md"]))
        started = self.events(folder)[0]["payload"]
        self.assertEqual((started["source"], started["path"]), ("spec", "specs/login.md"))

    def test_R18_a_spec_start_writes_spec_json_with_the_file_and_its_live_requirement_ids(self):
        folder = self.started()
        handoff = json.loads(Path(folder, "spec.json").read_text())
        self.assertEqual((handoff["stage"], handoff["status"]), ("Spec", "ok"))
        self.assertEqual(handoff["paths"], ["specs/login.md"])
        self.assertEqual(handoff["ids"], ["SPEC-007/REQ-1", "SPEC-007/REQ-2"])
        document = self.progress(folder)
        self.assertEqual(document["spec"], ["specs/login.md"])
        self.assertEqual(document["flow"]["spec_ids"], ["SPEC-007/REQ-1", "SPEC-007/REQ-2"])

    def test_R18_the_spec_path_is_relative_to_the_repository_even_when_given_absolute(self):
        self.write_spec()
        result = self.start_spec(os.path.join(self.repo, "specs", "login.md"))
        self.assertEqual(result.returncode, 0, result.stderr)
        handoff = json.loads(Path(json.loads(result.stdout)["dir"], "spec.json").read_text())
        self.assertEqual(handoff["paths"], ["specs/login.md"])

    def test_a_spec_handed_back_by_the_planner_is_revised_without_naming_a_scope(self):
        folder = self.started()
        self.drive(folder, until=spawns("Plan"))
        self.write_lean_plan(folder)
        self.put(folder, "plan.json", self.plan_handoff(status="spec_invalid", reason="REQ-1 clashes",
                                                        invalidates=["SPEC-007/REQ-1"]))
        self.record(folder, "Plan")
        action = self.next(folder)
        self.assertEqual((action["stage"], action["mode"]), ("Spec", "revise"))
        self.assertNotIn("scope.json", action["prompt"])

    def test_R19_a_missing_spec_file_exits_2_and_creates_no_task_folder(self):
        result = self.start_spec("specs/missing.md")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("specs/missing.md", result.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".ai", "plans")))

    def test_R19_a_spec_file_without_a_front_matter_id_exits_2_and_creates_no_task_folder(self):
        self.write_spec("# Login\n\n- **REQ-1** The login service shall log in.\n")
        result = self.start_spec()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("no `id:`", result.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".ai", "plans")))

    def test_R19_a_spec_file_outside_the_repository_exits_2_and_creates_no_task_folder(self):
        outside = os.path.join(self.tmpdir.name, "outside.md")
        Path(outside).write_text(SPEC_FILE)
        result = self.start_spec(outside)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("outside the repository", result.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".ai", "plans")))

    def test_a_task_cannot_start_from_a_plan_and_a_spec_at_once(self):
        self.write_spec()
        result = self.start_spec("specs/login.md", "Login redirect", "--plan", "x.md")
        self.assertEqual(result.returncode, 1)
        self.assertIn("not both", result.stderr)

    def test_SPEC_LOCAL_REQ_15_a_spec_start_carries_no_checks_line_so_the_plans_qa_line_stands(self):
        folder = self.started()
        self.record(folder, "Preflight", "--exit-code", "0")
        action = self.next(folder)
        self.assertEqual(action["stage"], "Plan")
        self.assertNotIn("Refine selected", action["prompt"])


class TestNext(TaskTestCase):
    def test_next_prints_one_json_object_naming_the_agent_and_no_model_without_one(self):
        folder = self.start()["dir"]
        result = self.run_task("next", "--task", folder)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(result.stdout.strip().splitlines()), 1)
        action = json.loads(result.stdout)
        self.assertEqual((action["action"], action["stage"], action["agent"], action["name"]),
                         ("spawn", "Refine", "hoko-specifier", "refine-c1"))
        self.assertNotIn("model", action, "no HOKO_*_MODEL names the refine stage")
        self.assertNotIn("effort", action, "no effort is resolved or recorded for a stage")
        self.assertIn(str(Path(folder, "scope.json")), action["prompt"])

    def test_r1_a_step_carries_the_model_its_stage_environment_names(self):
        self.env["HOKO_EXECUTOR_MODEL"] = "opencode-go/deepseek-v4-flash"
        self.scope = {"needs_plan": False}
        folder = self.start()["dir"]
        step = self.drive(folder, "step")
        self.assertEqual(step["model"], "opencode-go/deepseek-v4-flash")

    def test_r1_a_step_keeps_the_variant_its_configured_model_names(self):
        self.env["HOKO_EXECUTOR_MODEL"] = "opencode-go/deepseek-v4-flash#max"
        self.scope = {"needs_plan": False}
        folder = self.start()["dir"]
        step = self.drive(folder, "step")
        self.assertEqual(step["model"], "opencode-go/deepseek-v4-flash#max")

    def test_r1_a_spawn_carries_the_stage_model_exactly_as_configured(self):
        self.env["HOKO_QA_MODEL"] = "opencode-go/glm-5.3-flash"
        folder = self.start()["dir"]
        action = self.drive(folder, until=spawns("QA"))
        self.assertEqual(action["model"], "opencode-go/glm-5.3-flash")
        self.assertNotIn("effort", action)

    def test_r1_a_spawn_keeps_the_variant_the_configured_model_names(self):
        self.env["HOKO_QA_MODEL"] = "opencode-go/glm-5.3-flash#low"
        folder = self.start()["dir"]
        action = self.drive(folder, until=spawns("QA"))
        self.assertEqual(action["model"], "opencode-go/glm-5.3-flash#low")

    def test_r3_a_spawn_records_no_effort_in_its_stage_event(self):
        folder = self.start()["dir"]
        self.assertEqual(self.next(folder)["stage"], "Refine")
        event = self.events(folder)[-1]
        self.assertEqual(event["type"], "stage.started")
        self.assertNotIn("effort", event["payload"])
        self.assertNotIn("efforts", event["payload"])

    def test_asking_again_writes_no_event_a_second_time(self):
        folder = self.start()["dir"]
        self.next(folder)
        written = self.types(folder)
        self.assertEqual(written, ["run.started", "stage.started"])
        self.assertEqual(self.next(folder)["name"], "refine-c1")
        self.assertEqual(self.next(folder)["name"], "refine-c1")
        self.assertEqual(self.types(folder), written)

    def test_asking_again_leaves_progress_json_byte_for_byte_alone(self):
        folder = self.start()["dir"]
        self.next(folder)
        before = Path(folder, "progress.json").read_bytes()
        self.next(folder)
        self.assertEqual(Path(folder, "progress.json").read_bytes(), before)

    def test_a_folder_without_progress_json_is_not_a_task(self):
        result = self.run_task("next", "--task", self.repo)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not a task folder", result.stderr)


class TestHandoffSchema(TaskTestCase):
    def setUp(self):
        super().setUp()
        self.folder = self.start()["dir"]
        self.next(self.folder)

    def rejected(self, data, *words):
        self.put(self.folder, "scope.json", data)
        before = Path(self.folder, "progress.json").read_bytes()
        events_before = self.types(self.folder)
        result = self.run_task("record", "--task", self.folder, "--stage", "Refine")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        for word in words:
            self.assertIn(word, result.stderr)
        self.assertEqual(Path(self.folder, "progress.json").read_bytes(), before)
        self.assertEqual(self.types(self.folder), events_before)
        return result.stderr

    def test_a_hand_off_that_fails_its_schema_exits_non_zero_naming_the_first_problem(self):
        message = self.rejected(self.scope_handoff(size="huge"), "scope.json", "size")
        self.assertEqual(len(message.strip().splitlines()), 1)

    def test_a_hand_off_that_fails_its_schema_leaves_progress_json_unchanged(self):
        self.rejected(self.scope_handoff(needs_plan="yes"), "needs_plan")

    def test_a_hand_off_that_is_not_json_is_rejected_by_name(self):
        Path(self.folder, "scope.json").write_text("{not json")
        before = Path(self.folder, "progress.json").read_bytes()
        result = self.run_task("record", "--task", self.folder, "--stage", "Refine")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("scope.json: not valid JSON", result.stderr)
        self.assertEqual(Path(self.folder, "progress.json").read_bytes(), before)

    def test_a_missing_hand_off_is_rejected_by_name(self):
        result = self.run_task("record", "--task", self.folder, "--stage", "Refine")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("scope.json: not found", result.stderr)

    def test_the_envelope_status_and_a_needs_input_without_questions_are_checked(self):
        self.rejected(self.scope_handoff(status="done"), "status")
        self.rejected(self.scope_handoff(status="needs_input"), "needs_input needs 1 to 4 questions")

    def test_a_question_needs_two_to_four_options_and_a_recommended_one_of_them(self):
        bad = {"id": "q1", "question": "Which?", "options": ["a", "b"], "recommended": "c", "why": "because"}
        self.rejected(self.scope_handoff(status="needs_input", questions=[bad]), "recommended")

    def test_SPEC_LOCAL_REQ_11_a_multiple_hint_must_be_a_boolean(self):
        bad = {"id": "q1", "question": "Which?", "options": ["a", "b", "c"], "recommended": "a",
               "why": "because", "multiple": "yes"}
        self.rejected(self.scope_handoff(status="needs_input", questions=[bad]), "multiple")

    def test_SPEC_LOCAL_REQ_13_a_checks_value_other_than_crap_or_mutation_is_rejected(self):
        self.rejected(self.scope_handoff(checks=["lint"]), "scope.json", "checks", "lint")
        self.rejected(self.scope_handoff(checks="crap"), "checks", "list")

    def test_a_qa_hand_off_needs_a_findings_list_and_known_gate_checks(self):
        folder = self.green_to_qa()
        bad = self.qa_handoff(gates=[{"check": "vibes", "status": "passed", "duration_ms": 1}])
        self.put(folder, "qa-01.json", bad)
        result = self.run_task("record", "--task", folder, "--stage", "QA")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("gates[0].check", result.stderr)
        self.put(folder, "qa-01.json", self.qa_handoff(verdict="not ready"))
        result = self.run_task("record", "--task", folder, "--stage", "QA")
        self.assertIn("at least one finding", result.stderr)

    def test_a_review_hand_off_is_an_array_of_findings_with_a_known_severity(self):
        folder = self.green_to_qa()
        self.put(folder, "qa-01.json", self.qa_handoff())
        self.record(folder, "QA")
        self.put(folder, "review-01.json", [{"severity": "huge", "summary": "x"}])
        result = self.run_task("record", "--task", folder, "--stage", "Review")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("[0].severity", result.stderr)
        self.put(folder, "review-01.json", {"severity": "blocking"})
        result = self.run_task("record", "--task", folder, "--stage", "Review")
        self.assertIn("JSON array", result.stderr)

    def green_to_qa(self):
        folder = self.start("Another task")["dir"]
        self.drive(folder, until=spawns("QA"))
        return folder


class TestBranch(TaskTestCase):
    def test_a_refine_hand_off_recorded_on_a_protected_branch_returns_branch_before_any_spec_spawn(self):
        self.git("checkout", "-q", "-B", "main")
        self.scope = {"needs_spec": True, "ticket": "ABC-12"}
        folder = self.start()["dir"]
        self.drive(folder, "branch")
        action = self.next(folder)
        self.assertEqual((action["action"], action["current"], action["ticket"]), ("branch", "main", "ABC-12"))
        self.assertEqual(self.next(folder)["action"], "branch")
        self.git("checkout", "-q", "-b", "feature/ABC-12-login")
        self.assertEqual(self.next(folder)["action"], "preflight")
        self.record(folder, "Preflight", "--exit-code", "0")
        self.assertEqual(self.next(folder)["stage"], "Spec")

    def test_a_refine_hand_off_on_a_feature_branch_goes_straight_to_preflight(self):
        folder = self.start()["dir"]
        self.drive(folder, "preflight")

    def test_the_ticket_only_names_the_branch_and_no_ticket_tool_is_called(self):
        self.git("checkout", "-q", "-B", "main")
        self.scope = {"ticket": "ABC-12"}
        folder = self.start()["dir"]
        action = self.drive(folder, "branch")
        self.assertEqual((action["action"], action["current"], action["ticket"]),
                         ("branch", "main", "ABC-12"))
        source = Path(SCRIPT).read_text(encoding="utf-8")
        for token in ("Jira", "Atlassian", "mcp"):
            self.assertNotIn(token, source, "the state machine fetches or edits no ticket")


class TestPreflight(TaskTestCase):
    def test_a_green_fast_gate_writes_a_check_result_and_moves_on(self):
        folder = self.start()["dir"]
        action = self.drive(folder, "preflight")
        self.assertIn("fast-gate.py", action["command"])
        self.record(folder, "Preflight", "--exit-code", "0", "--duration-ms", "40")
        check = [e for e in self.events(folder) if e["type"] == "check.result"][0]["payload"]
        self.assertEqual((check["check"], check["status"], check["exit_code"], check["duration_ms"]),
                         ("fast-gate", "passed", 0, 40))
        self.assertEqual(self.next(folder)["stage"], "Plan")

    def test_a_red_fast_gate_asks_and_continue_goes_on(self):
        folder = self.start()["dir"]
        self.drive(folder, "preflight")
        self.record(folder, "Preflight", "--exit-code", "1")
        asked = self.next(folder)
        self.assertEqual(asked["action"], "ask")
        self.assertEqual(asked["questions"][0]["options"], ["Continue", "Stop"])
        self.answer(folder, {"preflight": "Continue"})
        self.assertEqual(self.next(folder)["stage"], "Plan")

    def test_a_red_fast_gate_and_stop_ends_the_task_failed(self):
        folder = self.start()["dir"]
        self.drive(folder, "preflight")
        self.record(folder, "Preflight", "--exit-code", "1")
        self.next(folder)
        self.answer(folder, {"preflight": "Stop"})
        self.assertEqual(self.progress(folder)["status"], "stopped")
        self.assertEqual(self.next(folder)["action"], "stop")


class TestTrivialTask(TaskTestCase):
    def test_a_trivial_task_with_no_plan_runs_one_step_and_qa_and_skips_spec_plan_and_review(self):
        self.scope = {"size": "trivial", "needs_spec": False, "needs_plan": False}
        folder = self.start()["dir"]
        step = self.drive(folder, "step")
        self.assertEqual((step["step"], step["steps"], step["round"]), (1, 1, 1))
        self.assertTrue(os.path.isfile(step["slice"]))
        self.tick_all(step)
        self.assertEqual(self.drive(folder, "finish")["action"], "finish")

        stages = self.progress(folder)["stages"]
        self.assertEqual((stages["Spec"], stages["Plan"], stages["Review"], stages["QA"]),
                         ("skipped", "skipped", "skipped", "done"))
        self.ok("finish", "--task", folder, "--report-file", "-", input="All done.")
        self.assertEqual(self.progress(folder)["status"], "done")
        self.assertEqual(Path(folder, "report.md").read_text(), "All done.\n")
        types = self.types(folder)
        self.assertEqual(types[-2:], ["files.changed", "run.finished"])
        self.assertEqual([e["payload"]["stage"] for e in self.events(folder) if e["type"] == "stage.completed"
                          and e["payload"].get("outcome") == "skipped"], ["Spec", "Plan", "Review"])
        self.assertEqual(self.next(folder)["action"], "stop")

    def test_a_refine_hand_off_without_needs_plan_writes_a_one_step_plan_and_skips_plan(self):
        self.scope = {"size": "small", "needs_plan": False, "title": "Rename the flag"}
        folder = self.start()["dir"]
        self.drive(folder, "step")
        text = Path(folder, "plan-01.md").read_text()
        self.assertTrue(text.startswith("# Rename the flag\n"))
        self.assertIn("Project: my-repo", text)
        self.assertIn("- [ ] 1. Rename the flag", text)
        self.assertEqual(len(re.findall(r"^### \d+\.", text, re.M)), 1)
        self.assertRegex(text, r"Base: [0-9a-f]{40}")
        document = self.progress(folder)
        self.assertEqual(document["stages"]["Plan"], "skipped")
        self.assertEqual([(r["plan"], r["source"], len(r["steps"])) for r in document["rounds"]],
                         [("plan-01.md", "implicit", 1)])

    def test_ticking_a_step_through_plan_progress_marks_it_in_the_tasks_progress_json(self):
        self.scope = {"needs_plan": False}
        folder = self.start()["dir"]
        step = self.drive(folder, "step")
        subprocess.run([sys.executable, PROGRESS_SCRIPT, "start", "--plan", step["plan"], "--step", "1"],
                       env=self.env, check=True, capture_output=True)
        started = self.progress(folder)["rounds"][0]["steps"][0]
        self.assertEqual(started["status"], "in_progress")
        self.assertFalse(os.path.exists(os.path.join(folder, "plan-01.progress.json")))
        stage = [e for e in self.events(folder) if e["type"] == "stage.started"][-1]["payload"]
        self.assertEqual((stage["stage"], stage["cycle"], stage["step"]), ("Implement", 1, 1))


class TestNeedsNoPlan(TaskTestCase):
    def setUp(self):
        super().setUp()
        self.scope = {"needs_spec": True, "needs_plan": False, "title": "Rename the flag"}
        Path(self.repo, "specs").mkdir()
        Path(self.repo, "specs", "login.md").write_text(SPEC_FILE, encoding="utf-8")
        self.folder = self.start()["dir"]
        self.drive(self.folder, until=spawns("Spec"))

    def record_spec(self, **changes):
        self.put(self.folder, "spec.json", self.spec_handoff(**changes))
        return self.record(self.folder, "Spec")

    def plan_text(self):
        return Path(self.folder, "plan-01.md").read_text(encoding="utf-8")

    def test_SPEC_011_REQ_27_a_task_that_needs_no_plan_runs_its_spec_without_the_planner(self):
        self.record_spec(ids=["SPEC-007/REQ-1", "SPEC-007/REQ-2"])
        self.assertIn("Spec: specs/login.md (SPEC-007: REQ-1, REQ-2)", self.plan_text())

    def test_SPEC_011_REQ_27_a_local_spec_is_named_by_its_path_under_the_repository_and_its_front_matter_id(self):
        Path(self.folder, "spec.md").write_text(SPEC_FILE.replace("SPEC-007", "SPEC-LOCAL"), encoding="utf-8")
        self.record_spec(paths=["spec.md"], ids=["SPEC-LOCAL/REQ-1"])
        relative = os.path.relpath(Path(self.folder, "spec.md"), self.repo)
        self.assertIn(f"Spec: {relative} (SPEC-LOCAL: REQ-1)\n", self.plan_text())

    def test_SPEC_011_REQ_27_each_spec_the_ids_name_gets_its_own_line(self):
        Path(self.repo, "specs", "session.md").write_text(
            SPEC_FILE.replace("SPEC-007", "SPEC-008"), encoding="utf-8")
        self.record_spec(paths=["specs/login.md", "specs/session.md"],
                         ids=["SPEC-007/REQ-1", "SPEC-008/REQ-2", "SPEC-007/REQ-2"])
        text = self.plan_text()
        self.assertIn("Spec: specs/login.md (SPEC-007: REQ-1, REQ-2)\n", text)
        self.assertIn("Spec: specs/session.md (SPEC-008: REQ-2)\n", text)

    def test_SPEC_011_REQ_28_the_one_step_claims_every_id_of_the_hand_off(self):
        self.record_spec(ids=["SPEC-007/REQ-1", "SPEC-007/REQ-2"])
        text = self.plan_text()
        self.assertEqual(len(re.findall(r"^### \d+\.", text, re.M)), 1)
        self.assertEqual(re.findall(r"^- Satisfies: (.*)$", text, re.M), ["SPEC-007/REQ-1, SPEC-007/REQ-2"])
        self.assertIn("- Tests: a test for each claimed requirement that fails without the change; "
                      "the project's own checks stay green.", text)
        self.assertRegex(text, r"Base: [0-9a-f]{40}")

    def test_SPEC_011_REQ_28_the_rewritten_plan_passes_plan_lint(self):
        self.record_spec(ids=["SPEC-007/REQ-1", "SPEC-007/REQ-2"])
        result = subprocess.run([sys.executable, str(SCRIPTS / "plan-lint.py"), "--plan",
                                 str(Path(self.folder, "plan-01.md")), "--root", self.repo],
                                capture_output=True, text=True, env=self.env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_SPEC_011_REQ_29_the_next_action_is_the_first_step_with_no_plan_spawn(self):
        self.record_spec(ids=["SPEC-007/REQ-1", "SPEC-007/REQ-2"])
        action = self.next(self.folder)
        self.assertEqual((action["action"], action["step"], action["steps"], action["round"]),
                         ("step", 1, 1, 1))
        document = self.progress(self.folder)
        self.assertEqual(document["stages"]["Plan"], "skipped")
        self.assertEqual([(r["plan"], r["source"], len(r["steps"])) for r in document["rounds"]],
                         [("plan-01.md", "implicit", 1)])
        self.assertEqual(document["spec"], ["specs/login.md"])
        self.events(self.folder)

    def test_SPEC_011_REQ_29_the_plan_gate_is_not_asked_for_the_rewritten_plan(self):
        self.env["HOKO_PLAN_GATE"] = "true"
        self.record_spec(ids=["SPEC-007/REQ-1", "SPEC-007/REQ-2"])
        self.assertEqual(self.next(self.folder)["action"], "step")
        self.assertNotIn("user.input_requested", self.types(self.folder))

    def test_SPEC_011_REQ_30_an_id_whose_spec_no_path_carries_is_rejected_and_changes_nothing(self):
        before = Path(self.folder, "progress.json").read_bytes()
        plan = self.plan_text()
        self.put(self.folder, "spec.json", self.spec_handoff(ids=["SPEC-007/REQ-1", "SPEC-009/REQ-1"]))
        result = self.run_task("record", "--task", self.folder, "--stage", "Spec")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("spec.json", result.stderr)
        self.assertIn("SPEC-009/REQ-1", result.stderr)
        self.assertEqual(Path(self.folder, "progress.json").read_bytes(), before)
        self.assertEqual(self.plan_text(), plan)

    def test_SPEC_011_REQ_30_a_path_that_cannot_be_read_is_rejected_and_changes_nothing(self):
        before = Path(self.folder, "progress.json").read_bytes()
        self.put(self.folder, "spec.json", self.spec_handoff(paths=["specs/missing.md"]))
        result = self.run_task("record", "--task", self.folder, "--stage", "Spec")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("spec.json", result.stderr)
        self.assertEqual(Path(self.folder, "progress.json").read_bytes(), before)

    def test_SPEC_011_REQ_30_a_spec_file_without_a_front_matter_id_is_rejected(self):
        Path(self.repo, "specs", "anon.md").write_text("# No id\n", encoding="utf-8")
        self.put(self.folder, "spec.json", self.spec_handoff(paths=["specs/anon.md"]))
        result = self.run_task("record", "--task", self.folder, "--stage", "Spec")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("spec.json", result.stderr)
        self.assertIn("front matter", result.stderr)

    def test_SPEC_011_REQ_29_a_spec_blocker_on_the_implicit_plan_still_returns_a_replan_spawn(self):
        self.record_spec(ids=["SPEC-007/REQ-1", "SPEC-007/REQ-2"])
        self.assertEqual(self.next(self.folder)["action"], "step")
        result = self.run_task("record", "--task", self.folder, "--stage", "Implement", "--blocker-file", "-",
                               input=json.dumps({"kind": "spec", "text": "REQ-1 cannot hold", "step": 1}))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.next(self.folder)["mode"], "revise")
        plan = self.plan_text()
        self.record_spec(summary="revised", ids=["SPEC-007/REQ-2"])
        self.assertEqual(self.plan_text(), plan)
        action = self.next(self.folder)
        self.assertEqual((action["action"], action["stage"], action["mode"]), ("spawn", "Plan", "replan"))
        self.assertIn("plan-02.md", action["prompt"])


class TestRefineChecks(TaskTestCase):
    """The QA checks the Refine answer selects reach the plan and the QA gate."""

    def asked(self, **question):
        folder = self.start()["dir"]
        self.next(folder)
        checks = {"id": "checks", "question": "Which checks does this run get?",
                  "options": ["CRAP", "Mutation", "Skip"], "recommended": "CRAP",
                  "why": "Every extra check costs run time."}
        checks.update(question)
        self.put(folder, "scope.json", self.scope_handoff(status="needs_input", questions=[checks]))
        self.record(folder, "Refine")
        return self.next(folder)

    def test_SPEC_LOCAL_REQ_11_a_multiple_hint_reaches_the_ask_action(self):
        asked = self.asked(multiple=True)
        self.assertEqual(asked["action"], "ask")
        self.assertTrue(asked["questions"][0]["multiple"])

    def test_SPEC_LOCAL_REQ_14_a_checks_list_lands_in_the_plan_prompt(self):
        self.scope = {"checks": ["crap"]}
        folder = self.start()["dir"]
        prompt = self.drive(folder, until=spawns("Plan"))["prompt"]
        self.assertIn("Refine selected the QA checks crap:", prompt)
        self.assertNotIn("mutation", prompt)

    def test_SPEC_LOCAL_REQ_12_the_selected_checks_land_in_the_qa_prompt(self):
        self.scope = {"checks": ["crap"]}
        folder = self.start()["dir"]
        prompt = self.drive(folder, until=spawns("QA"))["prompt"]
        self.assertIn("Refine selected the QA checks crap:", prompt)
        self.assertNotIn("mutation", prompt)

    def test_SPEC_LOCAL_REQ_12_skip_selects_no_quality_check(self):
        self.scope = {"checks": []}
        folder = self.start()["dir"]
        plan = self.drive(folder, until=spawns("Plan"))["prompt"]
        self.assertIn("Refine selected no QA check (Skip): write the plan's `QA:` line as `QA: none`.", plan)

        folder = self.start("Another task")["dir"]
        qa = self.drive(folder, until=spawns("QA"))["prompt"]
        self.assertIn("Refine selected no QA check (Skip): run neither the CRAP index nor mutation testing", qa)

    def test_SPEC_LOCAL_REQ_12_skip_writes_qa_none_into_the_implicit_plan(self):
        self.scope = {"checks": [], "needs_plan": False}
        folder = self.start()["dir"]
        step = self.drive(folder, "step")
        self.assertIn("QA: none\n", Path(step["plan"]).read_text())


class TestQaScope(TaskTestCase):
    """REQ-16 — the QA stage scopes both expensive checks to the run's changed files."""

    def commit_files(self, *names):
        for name in names:
            path = Path(self.repo, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x = 1\n", encoding="utf-8")
        self.git("add", *names)
        self.git("commit", "-q", "-m", "implement the step")

    def test_SPEC_LOCAL_REQ_16_the_qa_prompt_names_exactly_the_files_the_range_changed(self):
        folder = self.start()["dir"]
        step = self.drive(folder, "step")
        self.commit_files("src/a.py", "src/login/b.py")
        self.tick_all(step)
        action = self.next(folder)
        self.assertEqual(action["stage"], "QA")
        prompt = action["prompt"]
        self.assertIn("The files this run changed, and the only files in scope for the CRAP index and "
                      "mutation testing: src/a.py, src/login/b.py.", prompt)
        self.assertNotIn("whole project", prompt)
        self.assertNotIn("project-wide", prompt)

    def test_SPEC_LOCAL_REQ_16_an_empty_scope_is_reported_absent_instead_of_widened(self):
        folder = self.start()["dir"]
        prompt = self.drive(folder, until=spawns("QA"))["prompt"]
        self.assertIn("The run changed no files: report the CRAP index and mutation testing as absent "
                      "rather than widening the scope.", prompt)


class TestSpecHandBack(TaskTestCase):
    def setUp(self):
        super().setUp()
        self.scope = {"needs_spec": True}
        self.folder = self.start()["dir"]
        self.drive(self.folder, until=spawns("Plan"))

    def hand_back(self, reason="REQ-1 contradicts REQ-2"):
        self.write_lean_plan(self.folder)
        self.put(self.folder, "plan.json", self.plan_handoff(
            status="spec_invalid", reason=reason, invalidates=["SPEC-007/REQ-1"]))
        return self.record(self.folder, "Plan")

    def test_a_spec_invalid_plan_returns_a_spec_spawn_in_revise_mode(self):
        self.hand_back()
        action = self.next(self.folder)
        self.assertEqual((action["action"], action["stage"], action["mode"]), ("spawn", "Spec", "revise"))
        self.assertIn("REQ-1 contradicts REQ-2", action["prompt"])
        self.assertIn("SPEC-007/REQ-1", action["prompt"])
        handed = [e for e in self.events(self.folder) if e["type"] == "stage.completed"
                  and e["payload"]["stage"] == "Plan"][0]["payload"]
        self.assertEqual((handed["handoff_to"], handed["reason"]), ("Spec", "REQ-1 contradicts REQ-2"))

    def test_a_revised_spec_returns_a_plan_spawn(self):
        self.hand_back()
        self.next(self.folder)
        self.put(self.folder, "spec.json", self.spec_handoff(summary="revised"))
        self.record(self.folder, "Spec")
        action = self.next(self.folder)
        self.assertEqual((action["action"], action["stage"]), ("spawn", "Plan"))
        self.assertNotEqual(action["name"], "plan-c1")

    def test_the_third_spec_hand_back_returns_an_ask_action(self):
        for _ in range(2):
            self.hand_back()
            self.assertEqual(self.next(self.folder)["mode"], "revise")
            self.put(self.folder, "spec.json", self.spec_handoff())
            self.record(self.folder, "Spec")
            self.assertEqual(self.next(self.folder)["stage"], "Plan")
        self.hand_back("still contradictory")
        asked = self.next(self.folder)
        self.assertEqual(asked["action"], "ask")
        self.assertEqual(asked["questions"][0]["id"], "handback")
        self.assertIn("still contradictory", asked["questions"][0]["question"])

    def test_at_the_cap_answering_revise_goes_back_to_spec_and_stop_ends_the_task(self):
        for _ in range(3):
            self.hand_back()
            if self.next(self.folder)["action"] == "ask":
                break
            self.put(self.folder, "spec.json", self.spec_handoff())
            self.record(self.folder, "Spec")
        self.answer(self.folder, {"handback": "Revise the spec again"})
        self.assertEqual(self.next(self.folder)["mode"], "revise")
        self.put(self.folder, "spec.json", self.spec_handoff())
        self.record(self.folder, "Spec")
        self.hand_back()
        self.assertEqual(self.next(self.folder)["action"], "ask")
        self.answer(self.folder, {"handback": "Stop the task"})
        self.assertEqual(self.next(self.folder)["action"], "stop")

    def test_planning_against_the_spec_as_written_spawns_a_plan_that_may_not_hand_back(self):
        for _ in range(3):
            self.hand_back()
            if self.next(self.folder)["action"] == "ask":
                break
            self.put(self.folder, "spec.json", self.spec_handoff())
            self.record(self.folder, "Spec")
        self.answer(self.folder, {"handback": "Plan against the spec as written"})
        action = self.next(self.folder)
        self.assertEqual(action["stage"], "Plan")
        self.assertIn("do not hand it back again", action["prompt"])

    def test_a_plan_with_no_spec_cannot_be_handed_back(self):
        self.scope = {"needs_spec": False}
        folder = self.start("No spec here")["dir"]
        self.drive(folder, until=spawns("Plan"))
        self.write_lean_plan(folder)
        self.put(folder, "plan.json", self.plan_handoff(status="spec_invalid", reason="x", invalidates=["a/REQ-1"]))
        result = self.run_task("record", "--task", folder, "--stage", "Plan")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no spec", result.stderr)


class TestQuestions(TaskTestCase):
    def question(self):
        return {"id": "q1", "question": "Keep the old URL working?", "options": ["Yes", "No"],
                "recommended": "Yes", "why": "Bookmarks exist."}

    def test_a_needs_input_hand_off_becomes_an_ask_that_is_logged_once_and_a_resume_after_the_answer(self):
        folder = self.start()["dir"]
        self.next(folder)
        self.put(folder, "scope.json", self.scope_handoff(status="needs_input", questions=[self.question()]))
        self.record(folder, "Refine")
        asked = self.next(folder)
        self.assertEqual(asked["action"], "ask")
        self.assertEqual(asked["stage"], "Refine")
        self.next(folder)
        requested = [e for e in self.events(folder) if e["type"] == "user.input_requested"]
        self.assertEqual(len(requested), 1)
        self.assertEqual((requested[0]["payload"]["question"], requested[0]["payload"]["initial"]),
                         ("Keep the old URL working?", "Yes"))

        self.answer(folder, {"q1": "No"})
        answered = [e for e in self.events(folder) if e["type"] == "user.input_answered"][0]["payload"]
        self.assertEqual((answered["stage"], answered["answer"]), ("Refine", "No"))
        self.assertEqual(json.loads(Path(folder, "answers.json").read_text()), {"q1": "No"})
        resume = self.next(folder)
        self.assertEqual((resume["action"], resume["name"]), ("resume", "refine-c1"))
        self.assertIn("answers.json", resume["message"])

        self.put(folder, "scope.json", self.scope_handoff())
        self.record(folder, "Refine")
        self.assertEqual(self.next(folder)["action"], "preflight")

    def test_R23_an_answered_question_resumes_the_child_session_that_asked(self):
        folder = self.start()["dir"]
        self.next(folder)
        self.put(folder, "scope.json", self.scope_handoff(status="needs_input", questions=[self.question()]))
        self.record(folder, "Refine", "--agent-session", "ses_child")
        self.next(folder)
        self.answer(folder, {"q1": "Yes"})
        resume = self.next(folder)
        self.assertEqual((resume["action"], resume["stage"], resume["session_id"]),
                         ("resume", "Refine", "ses_child"))
        self.assertEqual(self.progress(folder)["flow"]["sessions"], {"Refine": "ses_child"})

    def test_R23_a_fresh_spawn_after_a_failed_resume_names_no_session(self):
        folder = self.start()["dir"]
        self.next(folder)
        self.put(folder, "scope.json", self.scope_handoff(status="needs_input", questions=[self.question()]))
        self.record(folder, "Refine", "--agent-session", "ses_child")
        self.next(folder)
        self.answer(folder, {"q1": "Yes"})
        fresh = self.next(folder, "--resume-failed")
        self.assertEqual((fresh["action"], fresh["name"]), ("spawn", "refine-c1-a1"))
        self.assertNotIn("session_id", fresh)

    def test_a_failed_resume_returns_a_fresh_spawn_that_names_the_answers(self):
        folder = self.start()["dir"]
        self.next(folder)
        self.put(folder, "scope.json", self.scope_handoff(status="needs_input", questions=[self.question()]))
        self.record(folder, "Refine")
        self.next(folder)
        self.answer(folder, {"q1": "Yes"})
        self.assertEqual(self.next(folder)["action"], "resume")
        fresh = self.next(folder, "--resume-failed")
        self.assertEqual((fresh["action"], fresh["stage"], fresh["name"]), ("spawn", "Refine", "refine-c1-a1"))
        self.assertIn("answers.json", fresh["prompt"])

    def test_an_answer_that_misses_a_question_id_changes_nothing(self):
        folder = self.start()["dir"]
        self.next(folder)
        self.put(folder, "scope.json", self.scope_handoff(status="needs_input", questions=[self.question()]))
        self.record(folder, "Refine")
        self.next(folder)
        before = Path(folder, "progress.json").read_bytes()
        result = self.run_task("answer", "--task", folder, "--answer-file", "-", input='{"other": "x"}')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("q1", result.stderr)
        self.assertEqual(Path(folder, "progress.json").read_bytes(), before)
        self.assertFalse(os.path.exists(os.path.join(folder, "answers.json")))

    def test_a_blocked_hand_off_stops_the_task(self):
        folder = self.start()["dir"]
        self.next(folder)
        self.put(folder, "scope.json", self.scope_handoff(status="blocked", summary="no repo access"))
        self.record(folder, "Refine")
        self.assertEqual(self.progress(folder)["status"], "stopped")
        self.assertEqual(self.types(folder)[-2:], ["stage.failed", "run.finished"])
        self.assertEqual(self.next(folder)["action"], "stop")

    def test_recording_while_a_question_waits_is_refused(self):
        folder = self.start()["dir"]
        self.next(folder)
        self.put(folder, "scope.json", self.scope_handoff(status="needs_input", questions=[self.question()]))
        self.record(folder, "Refine")
        result = self.run_task("record", "--task", folder, "--stage", "Refine")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("question is waiting", result.stderr)


class TestQaCycle(TaskTestCase):
    def test_a_not_ready_verdict_opens_the_next_cycle_without_a_review_spawn(self):
        folder = self.start()["dir"]
        self.qa_results = [self.qa_handoff("not ready", [finding("blocking", "Tests fail on empty input")])]
        action = self.drive(folder, until=starts_cycle(2))
        self.assertEqual((action["round"], os.path.basename(action["plan"])), (2, "plan-02.md"))
        started = [e["payload"]["stage"] for e in self.events(folder) if e["type"] == "stage.started"]
        self.assertNotIn("Review", started)
        document = self.progress(folder)
        self.assertEqual(document["cycle"], 2)
        self.assertEqual(document["rounds"][1]["source"], "qa")
        cycle = [e for e in self.events(folder) if e["type"] == "cycle.started"][0]["payload"]
        self.assertEqual((cycle["cycle"], cycle["reasons"]), (2, ["checks"]))
        reported = [e for e in self.events(folder) if e["type"] == "finding.reported"][0]["payload"]
        self.assertEqual((reported["stage"], reported["id"], reported["file"], reported["line"],
                          reported["problem"]), ("QA", "1.1", "src/a.py", 3, "Tests fail on empty input"))
        checks = [e["payload"] for e in self.events(folder) if e["type"] == "check.result"
                  and e["payload"]["stage"] == "QA"]
        self.assertEqual([(c["check"], c["status"]) for c in checks], [("tests", "passed")])

    def test_a_fix_cycle_writes_plan_nn_titled_with_the_task_title_and_round(self):
        folder = self.start("Fix login redirect")["dir"]
        self.qa_results = [self.qa_handoff("not ready", [finding("blocking", "Tests fail on empty input")])]
        self.drive(folder, until=starts_cycle(2))
        text = Path(folder, "plan-02.md").read_text()
        self.assertTrue(text.startswith("# Fix login redirect (round 2)\n"))
        self.assertIn("Tests fail on empty input", text)
        self.assertIn("Project: my-repo", text)
        self.assertEqual(self.progress(folder)["rounds"][1]["round"], 2)

    def test_the_step_events_of_a_fix_cycle_name_cycle_2_and_its_round(self):
        folder = self.start()["dir"]
        self.qa_results = [self.qa_handoff("not ready", [finding("blocking", "Tests fail on empty input")])]
        step = self.drive(folder, until=starts_cycle(2))
        subprocess.run([sys.executable, PROGRESS_SCRIPT, "start", "--plan", step["plan"], "--step", "1"],
                       env=self.env, check=True, capture_output=True)
        committed = subprocess.run(
            [sys.executable, str(SCRIPTS / "step-commit.py"), "--plan", step["plan"], "--step", "1",
             "--message-file", "-"], env=self.env, cwd=self.repo, capture_output=True, text=True,
            input="Guard the null case.\n\n* Check for null first.\n")
        self.assertEqual(committed.returncode, 0, committed.stdout + committed.stderr)
        found = [e["payload"] for e in self.events(folder)
                 if e["type"] in ("stage.started", "stage.completed", "check.result")
                 and e["payload"].get("step") == 1 and e["payload"]["stage"] == "Implement"]
        self.assertEqual(len(found), 3)
        self.assertEqual({(p["cycle"], p["round"]) for p in found if "round" in p}, {(2, 2)})
        self.assertEqual({p["cycle"] for p in found}, {2})
        self.assertEqual(self.progress(folder)["rounds"][1]["steps"][0]["status"], "done")

    def test_the_name_of_a_fix_plan_does_not_grow_from_round_to_round(self):
        self.env["HOKO_LOOP_LIMIT"] = "3"
        folder = self.start("Fix login redirect")["dir"]
        self.review_results = [[finding()], [finding()], [finding()]]
        self.drive(folder, "finish")
        names = sorted(n for n in os.listdir(folder) if n.startswith("plan-"))
        self.assertEqual(names, ["plan-01.md", "plan-02.md", "plan-03.md", "plan-04.md"])
        self.assertTrue(Path(folder, "plan-04.md").read_text().startswith("# Fix login redirect (round 4)\n"))

    def test_a_green_with_debt_verdict_continues_to_review_in_the_same_cycle(self):
        folder = self.start()["dir"]
        self.qa_results = [self.qa_handoff("green with debt")]
        action = self.drive(folder, until=spawns("Review"))
        self.assertEqual((action["name"], self.progress(folder)["cycle"]), ("review-c1", 1))
        self.assertEqual(self.progress(folder)["stages"]["QA"], "done")


class TestReviewLoop(TaskTestCase):
    def test_review_findings_open_the_next_cycle_and_green_ends_the_task(self):
        folder = self.start()["dir"]
        self.review_results = [[finding("blocking"), finding("nit", "Rename x")], []]
        self.drive(folder, "finish")
        document = self.progress(folder)
        self.assertEqual(document["cycle"], 2)
        self.assertEqual(document["rounds"][1]["source"], "review")
        text = Path(folder, "plan-02.md").read_text()
        self.assertEqual(len(re.findall(r"^### \d+\.", text, re.M)), 1)
        self.assertNotIn("Rename x", text)
        cycle = [e for e in self.events(folder) if e["type"] == "cycle.started"][0]["payload"]
        self.assertEqual(cycle["reasons"], ["findings"])
        ids = [e["payload"]["id"] for e in self.events(folder) if e["type"] == "finding.reported"]
        self.assertEqual(ids, ["1.1", "1.2"])

    def limit_reached(self, limit):
        self.env["HOKO_LOOP_LIMIT"] = str(limit)
        folder = self.start()["dir"]
        self.review_results = [[finding("blocking", f"Open item {n}")] for n in range(limit + 1)]
        asked = self.drive(folder, "ask")
        return folder, asked

    def test_open_items_after_the_last_cycle_return_an_ask_with_stage_cycles(self):
        folder, asked = self.limit_reached(1)
        self.assertEqual(asked["stage"], "Cycles")
        self.assertEqual(asked["questions"][0]["options"], ["Continue", "Accept", "Stop"])
        self.assertEqual(self.progress(folder)["cycle"], 2)
        requested = [e for e in self.events(folder) if e["type"] == "user.input_requested"][0]["payload"]
        self.assertEqual((requested["stage"], requested["initial"]), ("Cycles", "Accept"))

    def test_R20_a_loop_limit_of_zero_renders_the_open_items_as_a_follow_up_plan_without_asking(self):
        self.env["HOKO_LOOP_LIMIT"] = "0"
        folder = self.start()["dir"]
        self.review_results = [[finding("blocking", "Open item 1")]]
        finish = self.drive(folder, "finish")
        text = Path(folder, "plan-02.md").read_text()
        self.assertTrue(text.startswith("# Fix login redirect (round 2)\n"))
        self.assertIn("Open item 1", text)
        self.assertEqual(finish["followup"], str(Path(folder, "plan-02.md")))
        self.assertEqual(len(self.progress(folder)["rounds"]), 1)
        self.assertNotIn("user.input_requested", self.types(folder))
        accepted = [e for e in self.events(folder) if e["type"] == "stage.completed"
                    and e["payload"]["stage"] == "Cycles"]
        self.assertEqual(accepted[0]["payload"]["accepted"], 1)

    def test_R20_a_loop_limit_of_zero_accepts_the_findings_of_a_not_ready_qa_too(self):
        self.env["HOKO_LOOP_LIMIT"] = "0"
        folder = self.start()["dir"]
        self.qa_results = [self.qa_handoff("not ready", [finding("blocking", "Tests fail on empty input")])]
        self.drive(folder, "finish")
        self.assertIn("Tests fail on empty input", Path(folder, "plan-02.md").read_text())
        self.assertNotIn("user.input_requested", self.types(folder))

    def test_R21_a_loop_limit_of_zero_ends_the_run_done_after_one_cycle(self):
        self.env["HOKO_LOOP_LIMIT"] = "0"
        folder = self.start()["dir"]
        self.review_results = [[finding("blocking", "Open item 1")]]
        self.drive(folder, "finish")
        document = self.progress(folder)
        self.assertEqual((document["status"], document["cycle"]), ("done", 1))
        self.ok("finish", "--task", folder, "--report-file", "-", input="Accepted open items.")
        self.assertNotIn("cycle.started", self.types(folder))
        self.assertEqual(self.events(folder)[-1]["payload"]["status"], "done")

    def test_a_loop_limit_of_zero_with_nothing_open_finishes_without_a_follow_up(self):
        self.env["HOKO_LOOP_LIMIT"] = "0"
        folder = self.start()["dir"]
        finish = self.drive(folder, "finish")
        self.assertNotIn("followup", finish)
        self.assertFalse(os.path.exists(os.path.join(folder, "plan-02.md")))

    def test_answering_stop_writes_stage_failed_cycles_and_then_run_finished_failed(self):
        folder, _ = self.limit_reached(1)
        self.answer(folder, {"cycles": "Stop"})
        tail = self.events(folder)[-3:]
        self.assertEqual([e["type"] for e in tail], ["user.input_answered", "stage.failed", "run.finished"])
        self.assertEqual((tail[1]["payload"]["stage"], tail[2]["payload"]["status"]), ("Cycles", "failed"))
        self.assertEqual(self.progress(folder)["status"], "stopped")
        self.assertEqual(self.next(folder)["action"], "stop")

    def test_answering_accept_renders_the_open_findings_as_a_follow_up_plan_and_ends_done(self):
        folder, _ = self.limit_reached(1)
        self.answer(folder, {"cycles": "Accept"})
        document = self.progress(folder)
        self.assertEqual(document["status"], "done")
        text = Path(folder, "plan-03.md").read_text()
        self.assertTrue(text.startswith("# Fix login redirect (round 3)\n"))
        self.assertIn("Open item 1", text)
        self.assertEqual(len(document["rounds"]), 2)
        finish = self.next(folder)
        self.assertEqual((finish["action"], finish["followup"]), ("finish", str(Path(folder, "plan-03.md"))))
        self.ok("finish", "--task", folder, "--report-file", "-", input="Accepted open items.")
        self.assertEqual(self.types(folder)[-1], "run.finished")
        self.assertEqual(self.events(folder)[-1]["payload"]["status"], "done")

    def test_answering_continue_raises_the_limit_by_one_and_opens_another_cycle(self):
        folder, _ = self.limit_reached(1)
        self.answer(folder, {"cycles": "Continue"})
        document = self.progress(folder)
        self.assertEqual((document["cycle"], document["loop_limit"]), (3, 2))
        cycle = [e for e in self.events(folder) if e["type"] == "cycle.started"][-1]["payload"]
        self.assertEqual((cycle["cycle"], cycle["reasons"]), (3, ["findings"]))
        self.assertEqual(self.next(folder)["action"], "step")

    def test_continue_with_words_adds_them_as_a_step_and_the_instruction_reason(self):
        folder, _ = self.limit_reached(1)
        self.answer(folder, {"cycles": "Continue: also cover the expired-session case"})
        cycle = [e for e in self.events(folder) if e["type"] == "cycle.started"][-1]["payload"]
        self.assertEqual(cycle["reasons"], ["findings", "instruction"])
        text = Path(folder, "plan-03.md").read_text()
        self.assertIn("also cover the expired-session case", text)
        self.assertEqual(len(re.findall(r"^### \d+\.", text, re.M)), 2)

    def test_an_answer_that_is_none_of_the_options_changes_nothing(self):
        folder, _ = self.limit_reached(1)
        before = Path(folder, "progress.json").read_bytes()
        result = self.run_task("answer", "--task", folder, "--answer-file", "-",
                               input=json.dumps({"cycles": "Maybe"}))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must begin with one of", result.stderr)
        self.assertEqual(Path(folder, "progress.json").read_bytes(), before)
        self.assertFalse(os.path.exists(os.path.join(folder, "answers.json")))


class TestPlanGate(TaskTestCase):
    def setUp(self):
        super().setUp()
        self.env["HOKO_PLAN_GATE"] = "true"

    def gated(self):
        folder = self.start()["dir"]
        asked = self.drive(folder, "ask")
        return folder, asked

    def test_R22_the_plan_hand_off_returns_an_ask_with_stage_plan_before_any_step(self):
        folder, asked = self.gated()
        self.assertEqual(asked["stage"], "Plan")
        question = asked["questions"][0]
        self.assertEqual((question["options"], question["recommended"]), (["Approve", "Revise", "Stop"], "Approve"))
        self.assertIn("2 step(s)", question["question"])
        self.assertEqual([r["steps"][0]["status"] for r in self.progress(folder)["rounds"]], ["pending"])
        requested = [e for e in self.events(folder) if e["type"] == "user.input_requested"][0]["payload"]
        self.assertEqual((requested["stage"], requested["initial"]), ("Plan", "Approve"))
        self.assertEqual(self.next(folder)["action"], "ask")

    def test_SPEC_015_REQ_9_the_gate_names_the_steps_that_cannot_be_undone(self):
        folder = self.start()["dir"]
        self.drive(folder, until=spawns("Plan"))
        self.write_lean_plan(folder, steps=2)
        plan = Path(folder, "plan-01.md")
        plan.write_text(plan.read_text(encoding="utf-8").replace(
            "- Change: do thing 2.\n", "- Change: do thing 2.\n- Irreversible: drops the legacy_name column\n"),
            encoding="utf-8")
        self.put(folder, "plan.json", self.plan_handoff())
        self.record(folder, "Plan")
        asked = self.next(folder)
        self.assertEqual((asked["action"], asked["stage"]), ("ask", "Plan"))
        question = asked["questions"][0]["question"]
        self.assertIn("step 2 (drops the legacy_name column)", question)
        self.assertNotIn("step 1 (", question)
        self.assertEqual(asked["questions"][0]["options"], ["Approve", "Revise", "Stop"])

    def test_SPEC_015_REQ_9_a_plan_without_marked_steps_keeps_the_plain_question(self):
        _, asked = self.gated()
        question = asked["questions"][0]["question"]
        self.assertTrue(question.endswith("Approve it and start implementing, revise it "
                                          "(say what to change after the word), or stop?"))
        self.assertNotIn("cannot undo", question)

    def test_R22_approving_goes_to_the_first_step(self):
        folder, _ = self.gated()
        self.answer(folder, {"plan": "Approve"})
        action = self.next(folder)
        self.assertEqual((action["action"], action["step"]), ("step", 1))

    def test_R23_revise_returns_a_plan_spawn_whose_prompt_carries_the_users_text(self):
        folder, _ = self.gated()
        self.answer(folder, {"plan": "Revise: split step 2 in two"})
        action = self.next(folder)
        self.assertEqual((action["action"], action["stage"]), ("spawn", "Plan"))
        self.assertIn("split step 2 in two", action["prompt"])
        self.assertNotEqual(action["name"], "plan-c1")
        self.assertEqual(self.progress(folder)["stages"]["Plan"], "in_progress")

    def test_R23_a_plan_recorded_after_revise_goes_through_the_gate_again(self):
        folder, _ = self.gated()
        self.answer(folder, {"plan": "Revise: add a third step"})
        self.next(folder)
        self.write_lean_plan(folder, steps=3)
        self.put(folder, "plan.json", self.plan_handoff())
        self.record(folder, "Plan")
        asked = self.next(folder)
        self.assertEqual((asked["action"], asked["stage"]), ("ask", "Plan"))
        self.assertIn("3 step(s)", asked["questions"][0]["question"])
        self.assertEqual(len(self.progress(folder)["rounds"]), 1)
        self.answer(folder, {"plan": "Approve"})
        self.assertEqual(self.next(folder)["steps"], 3)

    def test_R23_a_revise_with_no_words_is_refused_and_changes_nothing(self):
        folder, _ = self.gated()
        before = Path(folder, "progress.json").read_bytes()
        result = self.run_task("answer", "--task", folder, "--answer-file", "-", input='{"plan": "Revise"}')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Revise: <what to change>", result.stderr)
        self.assertEqual(Path(folder, "progress.json").read_bytes(), before)
        self.assertFalse(os.path.exists(os.path.join(folder, "answers.json")))

    def test_R24_stop_ends_the_run_failed_with_stage_failed_plan(self):
        folder, _ = self.gated()
        self.answer(folder, {"plan": "Stop"})
        tail = self.events(folder)[-3:]
        self.assertEqual([e["type"] for e in tail], ["user.input_answered", "stage.failed", "run.finished"])
        self.assertEqual((tail[1]["payload"]["stage"], tail[2]["payload"]["status"]), ("Plan", "failed"))
        self.assertEqual(self.progress(folder)["status"], "stopped")
        self.assertEqual(self.next(folder)["action"], "stop")

    def test_SPEC_015_REQ_1_a_plan_is_gated_when_no_source_sets_planGate(self):
        del self.env["HOKO_PLAN_GATE"]
        folder = self.start()["dir"]
        asked = self.drive(folder, "ask")
        self.assertEqual(asked["stage"], "Plan")
        question = asked["questions"][0]
        self.assertEqual(question["options"], ["Approve", "Revise", "Stop"])
        self.assertIn("user.input_requested", self.types(folder))

    def test_SPEC_015_REQ_10_the_gate_says_how_to_turn_it_off(self):
        _, asked = self.gated()
        why = asked["questions"][0]["why"]
        self.assertIn('"planGate": false', why)
        self.assertIn("~/.config/opencode/hoko.json", why)
        self.assertIn("HOKO_PLAN_GATE=false", why)

    def test_R25_without_the_gate_the_plan_goes_straight_to_implement(self):
        self.env["HOKO_PLAN_GATE"] = "false"
        folder = self.start()["dir"]
        step = self.drive(folder, "step")
        self.assertEqual(step["step"], 1)
        self.assertNotIn("user.input_requested", self.types(folder))

    def test_a_revised_plan_is_refiled_in_the_journal_instead_of_stopping_the_task(self):
        journal = os.path.join(self.tmpdir.name, "journal")
        self.write_hoko({"journalPath": journal})
        folder, _ = self.gated()
        self.answer(folder, {"plan": "Revise: add a third step"})
        self.next(folder)
        self.write_lean_plan(folder, steps=3)
        self.put(folder, "plan.json", self.plan_handoff())
        self.record(folder, "Plan")
        entry = os.path.join(journal, "my-repo", os.listdir(os.path.join(journal, "my-repo"))[0])
        self.assertEqual(Path(entry, "plan-01.md").read_text(), Path(folder, "plan-01.md").read_text())
        self.assertIn("### 3.", Path(entry, "plan-01.md").read_text())


class TestImplementBlockers(TaskTestCase):
    def setUp(self):
        super().setUp()
        self.scope = {"needs_spec": True}
        self.folder = self.start()["dir"]
        self.step = self.drive(self.folder, "step")

    def blocker_json(self, kind, text="The step cannot be done as written.", step=1):
        return json.dumps({"kind": kind, "text": text, "step": step})

    def run_blocker(self, kind, text="The step cannot be done as written.", step=1):
        return self.run_task("record", "--task", self.folder, "--stage", "Implement", "--blocker-file", "-",
                             input=self.blocker_json(kind, text, step))

    def block(self, kind, text="The step cannot be done as written.", step=1):
        result = self.run_task("record", "--task", self.folder, "--stage", "Implement", "--blocker-file", "-",
                               input=self.blocker_json(kind, text, step))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return self.next(self.folder)

    def write_replan(self, steps=1):
        number = len(self.progress(self.folder)["rounds"]) + 1
        body = "".join(LEAN_STEP.format(n=n) for n in range(1, steps + 1))
        Path(self.folder, f"plan-{number:02d}.md").write_text(
            LEAN_PLAN.format(title="Fix login redirect", steps=body), encoding="utf-8")
        self.put(self.folder, "plan.json", self.plan_handoff(plan=f"plan-{number:02d}.md"))
        return self.record(self.folder, "Plan")

    def replan(self, kind="plan", text="Step 1 assumes a table that does not exist."):
        action = self.block(kind, text)
        self.assertEqual((action["action"], action["stage"], action["mode"]), ("spawn", "Plan", "replan"))
        self.write_replan()
        return self.next(self.folder)

    def test_R26_a_spec_blocker_returns_a_spec_spawn_in_revise_mode_carrying_the_text(self):
        action = self.block("spec", "REQ-1 and REQ-2 cannot both hold")
        self.assertEqual((action["action"], action["stage"], action["mode"]), ("spawn", "Spec", "revise"))
        self.assertIn("REQ-1 and REQ-2 cannot both hold", action["prompt"])
        step = self.progress(self.folder)["rounds"][0]["steps"][0]
        self.assertEqual((step["status"], step["blocker"]["kind"]), ("in_progress", "spec"))
        self.events(self.folder)

    def test_R27_the_revised_spec_returns_a_plan_spawn_in_replan_mode(self):
        self.block("spec", "REQ-1 and REQ-2 cannot both hold")
        self.put(self.folder, "spec.json", self.spec_handoff(summary="revised"))
        self.record(self.folder, "Spec")
        action = self.next(self.folder)
        self.assertEqual((action["action"], action["stage"], action["mode"]), ("spawn", "Plan", "replan"))
        self.assertIn("plan-02.md", action["prompt"])
        self.assertIn("REQ-1 and REQ-2 cannot both hold", action["prompt"])
        self.assertNotEqual(action["name"], "plan-c1")
        self.events(self.folder)

    def test_R28_a_plan_blocker_returns_a_plan_spawn_in_replan_mode_carrying_the_text(self):
        action = self.block("plan", "Step 1 assumes a table that does not exist.")
        self.assertEqual((action["action"], action["stage"], action["mode"]), ("spawn", "Plan", "replan"))
        self.assertIn("Step 1 assumes a table that does not exist.", action["prompt"])
        self.assertIn("only the steps still to do", action["prompt"])
        self.assertEqual(self.progress(self.folder)["cycle"], 1)
        self.events(self.folder)

    def test_R29_a_replan_hand_off_adds_its_plan_as_the_next_round_of_the_same_cycle(self):
        self.git("commit", "--allow-empty", "-q", "-m", "work of the first plan")
        self.block("plan")
        recorded = self.write_replan(steps=2)
        self.assertEqual(recorded["phase"], "implement")
        document = self.progress(self.folder)
        self.assertEqual([(r["round"], r["plan"], r["source"]) for r in document["rounds"]],
                         [(1, "plan-01.md", "plan"), (2, "plan-02.md", "replan")])
        self.assertEqual(document["cycle"], 1)
        self.assertEqual(document["rounds"][0]["steps"][0]["status"], "in_progress")
        self.assertEqual(document["rounds"][0]["steps"][0]["blocker"]["kind"], "plan")
        action = self.next(self.folder)
        self.assertEqual((action["action"], action["round"], action["cycle"], action["step"], action["steps"]),
                         ("step", 2, 1, 1, 2))
        self.assertTrue(action["plan"].endswith("plan-02.md"))
        bases = [re.search(r"^Base: (\w+)$", Path(self.folder, f"plan-0{n}.md").read_text(), re.M).group(1)
                 for n in (1, 2)]
        self.assertEqual(bases[0], bases[1])
        self.events(self.folder)

    def test_R29_a_replan_goes_straight_to_implement_even_with_the_plan_gate_on(self):
        self.env["HOKO_PLAN_GATE"] = "true"
        self.block("plan")
        self.assertEqual(self.write_replan()["phase"], "implement")
        self.assertEqual(self.next(self.folder)["action"], "step")

    def test_a_replan_that_names_the_wrong_plan_file_is_refused_and_changes_nothing(self):
        self.block("plan")
        Path(self.folder, "plan-02.md").write_text(LEAN_PLAN.format(title="T", steps=LEAN_STEP.format(n=1)))
        self.put(self.folder, "plan.json", self.plan_handoff(plan="plan-01.md"))
        before = Path(self.folder, "progress.json").read_bytes()
        result = self.run_task("record", "--task", self.folder, "--stage", "Plan")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("plan must name plan-02.md", result.stderr)
        self.assertEqual(Path(self.folder, "progress.json").read_bytes(), before)

    def test_a_fix_cycle_after_a_replan_takes_the_next_round_and_the_next_cycle(self):
        self.replan()
        self.qa_results = [self.qa_handoff("not ready", [finding()])]
        action = self.drive(self.folder, until=starts_cycle(2))
        self.assertEqual((action["round"], action["cycle"]), (3, 2))
        self.assertTrue(os.path.isfile(os.path.join(self.folder, "plan-03.md")))
        self.assertEqual(self.progress(self.folder)["cycle"], 2)
        self.events(self.folder)

    def test_R30_the_third_replan_of_a_cycle_asks_re_plan_or_stop_with_stage_plan(self):
        for _ in range(2):
            action = self.replan()
            self.assertEqual(action["action"], "step")
        asked = self.block("plan", "Still wrong.")
        self.assertEqual((asked["action"], asked["stage"]), ("ask", "Plan"))
        question = asked["questions"][0]
        self.assertEqual((question["options"], question["id"]), (["Re-plan", "Stop"], "replan"))
        self.assertIn("Still wrong.", question["question"])
        self.answer(self.folder, {"replan": "Re-plan"})
        again = self.next(self.folder)
        self.assertEqual((again["action"], again["stage"], again["mode"]), ("spawn", "Plan", "replan"))
        self.assertEqual(len(self.progress(self.folder)["rounds"]), 3)
        self.write_replan()
        self.assertEqual(self.next(self.folder)["round"], 4)
        self.events(self.folder)

    def test_R30_stopping_at_the_third_replan_ends_the_run_failed_with_stage_failed_plan(self):
        for _ in range(2):
            self.replan()
        self.block("plan")
        self.answer(self.folder, {"replan": "Stop"})
        tail = self.events(self.folder)[-2:]
        self.assertEqual([e["type"] for e in tail], ["stage.failed", "run.finished"])
        self.assertEqual((tail[0]["payload"]["stage"], tail[1]["payload"]["status"]), ("Plan", "failed"))
        self.assertEqual(self.next(self.folder)["action"], "stop")

    def test_the_replan_count_starts_again_in_the_next_cycle(self):
        for _ in range(2):
            self.replan()
        self.qa_results = [self.qa_handoff("not ready", [finding()])]
        self.drive(self.folder, until=starts_cycle(2))
        action = self.block("plan")
        self.assertEqual((action["action"], action["mode"]), ("spawn", "replan"))

    def test_R31_an_external_blocker_returns_a_researcher_spawn_with_the_text_as_its_question(self):
        action = self.block("external", "Does the client retry on 429?")
        self.assertEqual((action["action"], action["agent"], action["name"]),
                         ("spawn", "hoko-researcher", "research-c1-s1"))
        self.assertIn("Does the client retry on 429?", action["prompt"])
        self.assertEqual(self.next(self.folder)["name"], "research-c1-s1")
        self.events(self.folder)

    def test_R32_recording_research_returns_the_same_step_with_the_findings_path_in_its_context(self):
        self.block("external", "Does the client retry on 429?")
        findings = Path(self.repo, ".ai", "research", "retry.md")
        findings.parent.mkdir(parents=True)
        findings.write_text("It does not.\n")
        self.ok("record", "--task", self.folder, "--stage", "Implement", "--research", str(findings))
        action = self.next(self.folder)
        self.assertEqual((action["action"], action["step"], action["round"]), ("step", 1, 1))
        self.assertIn(str(findings), action["context"])
        self.assertIn("Does the client retry on 429?", action["context"])
        self.events(self.folder)

    def test_R32_a_findings_file_that_does_not_exist_is_refused_and_changes_nothing(self):
        self.block("external")
        before = Path(self.folder, "progress.json").read_bytes()
        result = self.run_task("record", "--task", self.folder, "--stage", "Implement", "--research",
                               "nowhere.md")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no findings file", result.stderr)
        self.assertEqual(Path(self.folder, "progress.json").read_bytes(), before)

    def test_R32_the_context_is_given_to_the_blocked_step_only(self):
        self.block("external")
        findings = Path(self.repo, "findings.md")
        findings.write_text("x\n")
        self.ok("record", "--task", self.folder, "--stage", "Implement", "--research", str(findings))
        self.tick_all(self.next(self.folder))
        self.assertNotIn("context", self.next(self.folder))

    def test_R33_a_second_external_blocker_on_the_same_step_asks_retry_or_stop(self):
        self.block("external", "First question")
        findings = Path(self.repo, "findings.md")
        findings.write_text("x\n")
        self.ok("record", "--task", self.folder, "--stage", "Implement", "--research", str(findings))
        self.assertEqual(self.next(self.folder)["action"], "step")
        asked = self.block("external", "Still unknown")
        self.assertEqual((asked["action"], asked["stage"]), ("ask", "Implement"))
        question = asked["questions"][0]
        self.assertEqual((question["options"], question["recommended"]), (["Retry", "Stop"], "Retry"))
        self.assertIn("Still unknown", question["question"])
        self.answer(self.folder, {"blocker": "Stop"})
        tail = self.events(self.folder)[-2:]
        self.assertEqual((tail[0]["type"], tail[0]["payload"]["stage"], tail[1]["payload"]["status"]),
                         ("stage.failed", "Implement", "failed"))

    def test_R34_a_product_blocker_returns_an_ask_whose_question_carries_the_text(self):
        asked = self.block("product", "Should expired sessions redirect to /login or /expired?")
        self.assertEqual((asked["action"], asked["stage"]), ("ask", "Implement"))
        question = asked["questions"][0]
        self.assertIn("Should expired sessions redirect to /login or /expired?", question["question"])
        self.assertEqual((question["options"], question["recommended"]), (["Retry", "Stop"], "Retry"))
        requested = [e for e in self.events(self.folder) if e["type"] == "user.input_requested"][0]["payload"]
        self.assertEqual((requested["stage"], requested["initial"]), ("Implement", "Retry"))

    def test_R35_answering_retry_returns_the_blocked_step_with_the_answer_in_its_context(self):
        self.block("product", "Which page?")
        self.answer(self.folder, {"blocker": "Retry: redirect to /expired"})
        action = self.next(self.folder)
        self.assertEqual((action["action"], action["step"]), ("step", 1))
        self.assertIn("redirect to /expired", action["context"])
        self.assertIn("Which page?", action["context"])
        self.events(self.folder)

    def test_R35_a_bare_retry_runs_the_step_again(self):
        self.block("product", "Which page?")
        self.answer(self.folder, {"blocker": "Retry"})
        action = self.next(self.folder)
        self.assertEqual((action["action"], action["step"]), ("step", 1))
        self.assertIn("retry as it is", action["context"])

    def test_a_product_blocker_stopped_by_the_user_ends_the_run_failed_with_stage_failed_implement(self):
        self.block("product", "Which page?")
        self.answer(self.folder, {"blocker": "Stop"})
        tail = self.events(self.folder)[-3:]
        self.assertEqual([e["type"] for e in tail], ["user.input_answered", "stage.failed", "run.finished"])
        self.assertEqual((tail[1]["payload"]["stage"], tail[2]["payload"]["status"]), ("Implement", "failed"))
        self.assertEqual(self.next(self.folder)["action"], "stop")

    def test_R36_an_unknown_kind_exits_non_zero_and_leaves_progress_json_and_the_events_alone(self):
        before = Path(self.folder, "progress.json").read_bytes()
        count = len(self.events(self.folder))
        result = self.run_blocker("flaky")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("kind must be one of spec, plan, external, product", result.stderr)
        self.assertEqual(Path(self.folder, "progress.json").read_bytes(), before)
        self.assertEqual(len(self.events(self.folder)), count)

    def test_R37_a_blocker_for_a_step_that_is_not_the_current_one_changes_nothing(self):
        before = Path(self.folder, "progress.json").read_bytes()
        count = len(self.events(self.folder))
        result = self.run_blocker("plan", step=2)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("step must be the current step, 1", result.stderr)
        self.assertEqual(Path(self.folder, "progress.json").read_bytes(), before)
        self.assertEqual(len(self.events(self.folder)), count)

    def test_R37_a_blocker_with_no_text_or_that_is_not_json_changes_nothing(self):
        before = Path(self.folder, "progress.json").read_bytes()
        for payload in ('{"kind": "plan", "text": "  ", "step": 1}', "not json", "[1]"):
            with self.subTest(payload=payload):
                result = self.run_task("record", "--task", self.folder, "--stage", "Implement",
                                       "--blocker-file", "-", input=payload)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(Path(self.folder, "progress.json").read_bytes(), before)

    def test_R37_a_spec_blocker_of_a_task_with_no_spec_is_refused_and_changes_nothing(self):
        self.scope = {"needs_spec": False}
        folder = self.start("No spec here")["dir"]
        self.drive(folder, "step")
        before = Path(folder, "progress.json").read_bytes()
        result = self.run_task("record", "--task", folder, "--stage", "Implement", "--blocker-file", "-",
                               input=self.blocker_json("spec"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no spec to hand back to", result.stderr)
        self.assertEqual(Path(folder, "progress.json").read_bytes(), before)

    def test_recording_a_blocker_needs_exactly_one_of_the_blocker_file_and_the_research_path(self):
        result = self.run_task("record", "--task", self.folder, "--stage", "Implement")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exactly one of", result.stderr)

    def test_research_is_refused_while_the_task_is_not_waiting_for_it(self):
        result = self.run_task("record", "--task", self.folder, "--stage", "Implement", "--research", "x.md")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not 'research'", result.stderr)

    def test_a_blocker_while_a_question_waits_is_refused(self):
        self.block("product")
        result = self.run_blocker("plan")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("a question is waiting", result.stderr)

    def test_R38_a_spec_blocker_at_the_spec_hand_back_cap_returns_an_ask(self):
        folder = self.start("Hand back twice")["dir"]
        self.drive(folder, until=spawns("Plan"))
        for _ in range(2):
            self.write_lean_plan(folder)
            self.put(folder, "plan.json", self.plan_handoff(
                status="spec_invalid", reason="REQ-1 contradicts REQ-2", invalidates=["SPEC-007/REQ-1"]))
            self.record(folder, "Plan")
            self.assertEqual(self.next(folder)["mode"], "revise")
            self.put(folder, "spec.json", self.spec_handoff())
            self.record(folder, "Spec")
            self.next(folder)
        self.write_lean_plan(folder)
        self.put(folder, "plan.json", self.plan_handoff())
        self.record(folder, "Plan")
        self.assertEqual(self.next(folder)["action"], "step")
        self.run_task("record", "--task", folder, "--stage", "Implement", "--blocker-file", "-",
                      input=self.blocker_json("spec", "REQ-3 cannot hold"))
        asked = self.next(folder)
        self.assertEqual((asked["action"], asked["stage"]), ("ask", "Plan"))
        self.assertEqual(asked["questions"][0]["id"], "handback")
        self.assertIn("REQ-3 cannot hold", asked["questions"][0]["question"])
        self.answer(folder, {"handback": "Plan against the spec as written"})
        action = self.next(folder)
        self.assertEqual((action["stage"], action["mode"]), ("Plan", "replan"))
        self.events(folder)

    def test_a_replan_after_a_spec_blocker_goes_through_the_planner_not_a_second_round_one(self):
        self.block("spec", "REQ-1 cannot hold")
        self.put(self.folder, "spec.json", self.spec_handoff())
        self.record(self.folder, "Spec")
        self.next(self.folder)
        self.write_replan()
        action = self.next(self.folder)
        self.assertEqual((action["action"], action["round"], action["cycle"]), ("step", 2, 1))
        document = self.progress(self.folder)
        self.assertEqual([r["source"] for r in document["rounds"]], ["plan", "replan"])


class TestResume(TaskTestCase):
    def test_a_resumed_task_returns_the_first_unticked_step_of_the_checklist(self):
        folder = self.start()["dir"]
        step = self.drive(folder, "step")
        self.assertEqual(step["step"], 1)
        subprocess.run([sys.executable, PROGRESS_SCRIPT, "start", "--plan", step["plan"], "--step", "1"],
                       env=self.env, check=True, capture_output=True)

        # the run crashed after step 1's commit ticked the plan, before anything else
        plan = Path(step["plan"])
        plan.write_text(plan.read_text().replace("- [ ] 1.", "- [x] 1."))
        resumed = self.next(folder)
        self.assertEqual((resumed["action"], resumed["step"]), ("step", 2))
        steps = self.progress(folder)["rounds"][0]["steps"]
        self.assertEqual([s["status"] for s in steps], ["done", "pending"])
        self.assertIsNotNone(steps[0]["started"])

    def test_a_stage_with_no_hand_off_is_spawned_again_after_a_crash(self):
        folder = self.start()["dir"]
        first = self.next(folder)
        again = self.next(folder)
        self.assertEqual((again["stage"], again["name"]), (first["stage"], first["name"]))

    def test_resuming_mid_step_re_dispatches_the_step_that_was_in_progress(self):
        folder = self.start()["dir"]
        step = self.drive(folder, "step")
        subprocess.run([sys.executable, PROGRESS_SCRIPT, "start", "--plan", step["plan"], "--step", "1"],
                       env=self.env, check=True, capture_output=True)
        self.assertEqual(self.next(folder)["step"], 1)


class TestForwardedPlan(TaskTestCase):
    def flat_plan(self, run_id="01JAB3K9V6T2Q8M4ZC7XWYN5RD"):
        path = os.path.join(self.repo, "flat.md")
        Path(path).write_text(LEAN_PLAN.format(title="Forwarded plan", steps="".join(
            LEAN_STEP.format(n=n) for n in (1, 2))), encoding="utf-8")
        subprocess.run([sys.executable, PROGRESS_SCRIPT, "init", "--plan", path], env=self.env,
                       check=True, capture_output=True)
        sidecar = os.path.join(self.repo, "flat.progress.json")
        document = json.loads(Path(sidecar).read_text())
        document["run_id"] = run_id
        Path(sidecar).write_text(json.dumps(document))
        return path

    def test_a_task_started_from_a_plan_that_has_a_run_id_keeps_it(self):
        plan = self.flat_plan()
        started = self.start("Forwarded plan", "Run this plan.", "--plan", plan)
        self.assertEqual(started["run_id"], "01JAB3K9V6T2Q8M4ZC7XWYN5RD")
        document = self.progress(started["dir"])
        self.assertEqual(document["run_id"], "01JAB3K9V6T2Q8M4ZC7XWYN5RD")
        self.assertEqual(document["source"], "plan")
        events_file = Path(self.repo, ".ai", "runs", "01JAB3K9V6T2Q8M4ZC7XWYN5RD", "events.jsonl")
        self.assertTrue(events_file.is_file())
        self.assertEqual(read_events(events_file)[0]["payload"]["path"], "flat.md")

    def test_a_forwarded_plan_skips_refine_spec_and_plan_and_goes_to_its_steps(self):
        plan = self.flat_plan()
        folder = self.start("Forwarded plan", "Run this plan.", "--plan", plan)["dir"]
        stages = self.progress(folder)["stages"]
        self.assertEqual((stages["Refine"], stages["Spec"], stages["Plan"]), ("skipped",) * 3)
        self.assertEqual(self.next(folder)["action"], "preflight")
        self.record(folder, "Preflight", "--exit-code", "0")
        step = self.next(folder)
        self.assertEqual((step["action"], step["step"], step["steps"]), ("step", 1, 2))
        self.assertTrue(step["plan"].endswith("plan-01.md"))
        self.assertEqual(len(self.progress(folder)["rounds"][0]["steps"]), 2)

    def test_a_plan_without_a_run_id_gets_a_fresh_one(self):
        plan = self.flat_plan(run_id=None)
        folder = self.start("Forwarded plan", "Run this plan.", "--plan", plan)
        self.assertRegex(folder["run_id"], r"^[0-9A-Z]{26}$")


class JournalTaskCase(TaskTestCase):
    """A task with journaling on: every start files an entry, so its sessions and
    `usage.json` have a home."""

    def setUp(self):
        super().setUp()
        self.journal = os.path.join(self.tmpdir.name, "journal")
        self.write_hoko({"journalPath": self.journal})

    def entry(self):
        project = os.path.join(self.journal, "my-repo")
        entries = os.listdir(project)
        self.assertEqual(len(entries), 1, entries)
        return os.path.join(project, entries[0])

    def archived_events(self, folder):
        """A finished run's events, read from the journal copy: closing prunes the live
        folder under `.ai/runs` once that copy exists."""
        copies = sorted(Path(self.entry()).glob("events-*.jsonl"))
        self.assertEqual(len(copies), 1, copies)
        return assert_valid_events(self, copies[0])


class TestJournal(RefusedStart, JournalTaskCase):
    def test_start_files_the_prompt_in_the_journal_under_the_folders_stamp_and_slug(self):
        started = self.start("Fix login redirect", "Fix the login redirect, please.")
        entry = self.entry()
        self.assertEqual(os.path.basename(entry), os.path.basename(started["dir"]))
        self.assertEqual(started["journal"], entry)
        self.assertIn("Fix the login redirect, please.", Path(entry, "prompt.md").read_text())
        self.assertFalse(os.path.exists(os.path.join(entry, "plan-01.md")))
        self.assertEqual(self.progress(started["dir"])["flow"]["journal"], entry)

    def test_a_plan_the_task_writes_is_copied_into_the_entry_with_a_journal_line(self):
        self.scope = {"needs_plan": False}
        folder = self.start()["dir"]
        self.drive(folder, "step")
        entry = self.entry()
        self.assertIn(f"Journal: {entry}/plan-01.md", Path(folder, "plan-01.md").read_text())
        self.assertEqual(Path(entry, "plan-01.md").read_text(), Path(folder, "plan-01.md").read_text())

    def test_finish_files_the_report_and_the_events_in_the_journal(self):
        self.scope = {"size": "trivial", "needs_plan": False}
        folder = self.start()["dir"]
        self.drive(folder, "finish")
        self.ok("finish", "--task", folder, "--report-file", "-", input="All good.")
        entry = self.entry()
        self.assertEqual(Path(entry, "report-01.md").read_text(), "All good.\n")
        self.assertTrue(os.path.isfile(os.path.join(entry, "events-01.jsonl")))

    def test_finish_leaves_the_marker_the_plugin_invoices_from(self):
        self.scope = {"size": "trivial", "needs_plan": False}
        folder = self.start()["dir"]
        self.drive(folder, "finish")
        self.ok("finish", "--task", folder, "--report-file", "-", input="All good.")
        marker = json.loads(Path(folder, "finish-pending.json").read_text())
        self.assertEqual(marker, {"entry": self.entry(), "plan": str(Path(folder, "plan-01.md")),
                                  "task": self.progress(folder)["task"]})

    def test_a_finish_with_journaling_off_leaves_no_finish_marker(self):
        self.write_hoko({"journalPath": ""})
        self.scope = {"size": "trivial", "needs_plan": False}
        folder = self.start()["dir"]
        self.drive(folder, "finish")
        self.ok("finish", "--task", folder, "--report-file", "-", input="All good.")
        self.assertFalse(os.path.exists(os.path.join(folder, "finish-pending.json")))

    def test_a_forwarded_plan_that_is_already_journaled_keeps_its_entry_and_files_no_second_one(self):
        entry = os.path.join(self.journal, "my-repo", "20261001-0900-forwarded")
        os.makedirs(entry)
        Path(entry, "plan-01.md").write_text("# Forwarded plan\n")
        plan = os.path.join(self.repo, "flat.md")
        Path(plan).write_text(f"# Forwarded plan\nProject: my-repo\nJournal: {entry}/plan-01.md\n\n"
                              + LEAN_PLAN.split("\n", 2)[2].format(steps=LEAN_STEP.format(n=1)),
                              encoding="utf-8")
        folder = self.start("Forwarded plan", "Run this plan.", "--plan", plan)["dir"]
        self.assertEqual(os.listdir(os.path.join(self.journal, "my-repo")), ["20261001-0900-forwarded"])
        self.assertEqual(self.progress(folder)["flow"]["journal"], entry)
        self.assertIn(f"Journal: {entry}/plan-01.md", Path(folder, "plan-01.md").read_text())
        self.assertEqual(Path(entry, "plan-01.md").read_text(), "# Forwarded plan\n")

    def test_R2_R1_R4_a_refused_start_removes_the_entry_it_filed_and_the_task_folder(self):
        self.refuse(self.stepless_plan())
        self.assertEqual(os.listdir(os.path.join(self.journal, "my-repo")), [])
        self.assert_no_task_folder_or_events()

    def test_R3_a_refused_start_leaves_the_entry_the_plans_journal_line_names_unchanged(self):
        entry = os.path.join(self.journal, "my-repo", "20261001-0900-forwarded")
        os.makedirs(entry)
        Path(entry, "plan-01.md").write_text("# Forwarded plan\n")
        Path(entry, "prompt.md").write_text("Run this plan.\n")
        before = {name: Path(entry, name).read_bytes() for name in os.listdir(entry)}
        self.refuse(self.stepless_plan(f"# Forwarded plan\nProject: my-repo\nJournal: {entry}/plan-01.md\n\n"
                                       "## Goal\n\nDo the thing.\n"))
        self.assertEqual(os.listdir(os.path.join(self.journal, "my-repo")), ["20261001-0900-forwarded"])
        self.assertEqual({name: Path(entry, name).read_bytes() for name in os.listdir(entry)}, before)
        self.assert_no_task_folder_or_events()

    def test_R10_a_fix_cycles_plan_is_filed_in_the_entry_under_the_task_folders_round_number(self):
        folder = self.start()["dir"]
        self.qa_results = [self.qa_handoff("not ready", [finding("blocking", "Tests fail on empty input")])]
        self.drive(folder, until=starts_cycle(2))
        entry = self.entry()
        self.assertEqual(Path(entry, "plan-02.md").read_text(), Path(folder, "plan-02.md").read_text())
        self.assertIn(f"Journal: {entry}/plan-02.md", Path(folder, "plan-02.md").read_text())

    def test_R10_an_entry_that_already_holds_the_rounds_plan_stops_the_task_instead_of_renumbering(self):
        folder = self.start()["dir"]
        self.qa_results = [self.qa_handoff("not ready", [finding("blocking", "Tests fail on empty input")])]
        action = self.drive(folder, until=spawns("QA"))
        Path(self.entry(), "plan-02.md").write_text("# Someone else's round\n")
        self.put(folder, "qa-01.json", self.qa_results.pop(0))
        result = self.run_task("record", "--task", folder, "--stage", action["stage"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("plan-02.md", result.stderr)
        self.assertEqual(Path(self.entry(), "plan-02.md").read_text(), "# Someone else's round\n")
        self.assertFalse(os.path.exists(os.path.join(self.entry(), "plan-03.md")))

    def test_with_journaling_off_no_journal_folder_is_written(self):
        self.write_hoko({"journalPath": ""})
        folder = self.start()["dir"]
        self.assertIsNone(self.progress(folder)["flow"]["journal"])
        self.assertFalse(os.path.exists(self.journal))


    def test_R16_a_prompt_started_task_writes_the_invoice_from_the_session_that_typed_its_prompt(self):
        folder = self.start()["dir"]
        later = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
        self.record_session("S1", [("abc", later)], self.entry())
        stale = self.record_session("S0", [("old", later)])
        os.utime(stale, (0, 0))
        self.drive(folder, "finish")
        self.ok("finish", "--task", folder, "--report-file", "-", input="All good.")
        entry = Path(self.entry())
        rows = json.loads(entry.joinpath("sessions.json").read_text())
        self.assertEqual([(row["session_id"], row["role"]) for row in rows], [("S1", "execute")])
        data = json.loads(entry.joinpath("invoice.json").read_text())
        self.assertEqual([session["session_id"] for session in data["sessions"]], ["S1"])
        self.assertEqual(data["totals"]["input_tokens"], 200)
        self.assertIn("Token invoice", entry.joinpath("invoice.md").read_text())

    def finish_with_session(self, analytics_path):
        """A prompt-started task finished against `analyticsPath`; returns the finish result."""
        self.write_hoko({"journalPath": self.journal, "analyticsPath": analytics_path})
        folder = self.start()["dir"]
        later = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
        self.record_session("S1", [("abc", later)], self.entry())
        self.drive(folder, "finish")
        result = self.run_task("finish", "--task", folder, "--report-file", "-", input="All good.")
        return folder, result

    def test_finish_writes_no_invoice_before_the_plugin_wrote_usage_json(self):
        folder = self.start()["dir"]
        self.drive(folder, "finish")
        self.ok("finish", "--task", folder, "--report-file", "-", input="All good.")
        entry = Path(self.entry())
        self.assertFalse(entry.joinpath("invoice.json").exists())
        self.assertFalse(entry.joinpath("invoice.md").exists())
        self.assertEqual(entry.joinpath("report-01.md").read_text(), "All good.\n")

    def test_finish_writes_the_invoice_once_the_entry_has_usage_json(self):
        folder = self.start()["dir"]
        later = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
        self.record_session("S1", [("abc", later)], self.entry())
        self.drive(folder, "finish")
        self.ok("finish", "--task", folder, "--report-file", "-", input="All good.")
        data = json.loads(Path(self.entry(), "invoice.json").read_text())
        self.assertEqual([session["session_id"] for session in data["sessions"]], ["S1"])
        self.assertEqual(data["totals"]["input_tokens"], 200)

    def files_in(self, folder):
        return sorted(name for name in os.listdir(folder)
                      if name.startswith(("sessions", "invoice", "events", "entry")))

    def test_a_completed_runs_analytics_land_beside_the_journal_not_in_it(self):
        analytics = os.path.join(self.tmpdir.name, "analytics")
        folder, result = self.finish_with_session(analytics)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        entry = self.entry()
        beside = os.path.join(analytics, "my-repo", os.path.basename(entry))
        self.assertEqual(self.files_in(beside),
                         ["entry.json", "events-01.jsonl", "invoice.json", "invoice.md", "sessions.json"])
        self.assertEqual(self.files_in(entry), [])
        self.assertEqual(Path(entry, "report-01.md").read_text(), "All good.\n")
        link = json.loads(Path(beside, "entry.json").read_text())
        self.assertEqual(link, {"journal_entry": entry, "project": "my-repo", "entry": os.path.basename(entry),
                                "run_ids": [self.progress(folder)["run_id"]], "session_ids": ["S1"]})
        self.assertEqual([row["session_id"] for row in json.loads(Path(beside, "sessions.json").read_text())],
                         ["S1"])

    def test_finish_prunes_the_live_run_directory_after_its_analytics_copy(self):
        analytics = os.path.join(self.tmpdir.name, "analytics")
        folder, result = self.finish_with_session(analytics)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        run_id = self.progress(folder)["run_id"]
        beside = os.path.join(analytics, "my-repo", os.path.basename(self.entry()))
        self.assertTrue(os.path.isfile(os.path.join(beside, "events-01.jsonl")))
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".ai", "runs", run_id)))

    def test_an_empty_analytics_path_keeps_the_analytics_in_the_journal_entry(self):
        analytics = os.path.join(self.tmpdir.name, "analytics")
        _, result = self.finish_with_session("")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.files_in(self.entry()),
                         ["events-01.jsonl", "invoice.json", "invoice.md", "sessions.json"])
        self.assertFalse(os.path.exists(analytics))

    def test_an_unwritable_analytics_folder_does_not_fail_the_run(self):
        blocker = os.path.join(self.tmpdir.name, "blocker")
        Path(blocker).write_text("a file, not a directory")
        _, result = self.finish_with_session(os.path.join(blocker, "analytics"))

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        entry = self.entry()
        self.assertIn(os.path.join(blocker, "analytics", "my-repo", os.path.basename(entry)), result.stderr)
        self.assertEqual(self.files_in(entry), [])
        self.assertEqual(Path(entry, "report-01.md").read_text(), "All good.\n")

    def test_the_completing_runs_id_is_listed_with_events_off(self):
        self.env["HOKO_EVENTS"] = "false"
        analytics = os.path.join(self.tmpdir.name, "analytics")
        folder, result = self.finish_with_session(analytics)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        beside = os.path.join(analytics, "my-repo", os.path.basename(self.entry()))
        self.assertEqual(json.loads(Path(beside, "entry.json").read_text())["run_ids"],
                         [self.progress(folder)["run_id"]])
        self.assertNotIn("events-01.jsonl", os.listdir(beside))

    def test_with_journaling_off_nothing_is_written_under_the_analytics_path(self):
        analytics = os.path.join(self.tmpdir.name, "analytics")
        self.write_hoko({"journalPath": "", "analyticsPath": analytics})
        folder = self.start()["dir"]
        self.drive(folder, "finish")
        self.ok("finish", "--task", folder, "--report-file", "-", input="All good.")
        self.assertFalse(os.path.exists(analytics))

    def test_R7_an_entry_that_already_has_sessions_keeps_its_rows_and_gains_the_round_rows(self):
        folder = self.start()["dir"]
        later = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
        self.record_session("S1", [("abc", later)], self.entry())
        kept = Path(self.entry(), "sessions.json")
        existing = {"session_id": "P", "transcript_path": "", "round": 1, "role": "plan",
                    "since": "2026-10-01T10:00:00.000+00:00"}
        kept.write_text(json.dumps([existing]))
        self.drive(folder, "finish")
        self.ok("finish", "--task", folder, "--report-file", "-", input="All good.")
        rows = json.loads(kept.read_text())
        self.assertEqual(rows[0], existing)
        self.assertEqual([(row["session_id"], row["round"], row["role"]) for row in rows[1:]],
                         [("S1", 1, "execute")])

    def three_round_task(self):
        """A task with round 1, a re-plan round 2 and a fix-cycle round 3, finished-ready."""
        folder = self.start()["dir"]
        self.drive(folder, "step")
        blocker = json.dumps({"kind": "plan", "text": "Step 1 assumes a missing table.", "step": 1})
        self.ok("record", "--task", folder, "--stage", "Implement", "--blocker-file", "-", input=blocker)
        self.drive(folder, until=spawns("Plan"))
        body = LEAN_STEP.format(n=1)
        Path(folder, "plan-02.md").write_text(LEAN_PLAN.format(title="Fix login redirect", steps=body))
        self.put(folder, "plan.json", self.plan_handoff(plan="plan-02.md"))
        self.record(folder, "Plan")
        self.qa_results = [self.qa_handoff("not ready", [finding("blocking", "Tests fail on empty input")])]
        self.drive(folder, "finish")
        document = self.progress(folder)
        self.assertEqual([entry["round"] for entry in document["rounds"]], [1, 2, 3])
        return folder, document

    def test_R5_R6_a_finished_task_registers_each_recorded_session_once_per_round_since_that_rounds_start(self):
        folder, document = self.three_round_task()
        starts = document["flow"]["round_starts"]
        self.assertEqual([entry["round"] for entry in starts], [1, 2, 3])
        self.assertEqual(starts[0]["started"], document["started"])
        later = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
        self.record_session("S1", [("abc", later)], self.entry())
        self.record_session("S2", [("def", later)], self.entry())
        self.ok("finish", "--task", folder, "--report-file", "-", input="Done in three rounds.")
        rows = json.loads(Path(self.entry(), "sessions.json").read_text())
        self.assertEqual([(row["session_id"], row["round"], row["role"], row["since"]) for row in rows],
                         [(session, entry["round"], "execute", entry["started"])
                          for session in ("S1", "S2") for entry in starts])

    def test_R5_R7_a_transcriptless_session_still_registers_in_every_round_conductor_included(self):
        folder, document = self.three_round_task()
        starts = document["flow"]["round_starts"]
        self.record_session("C1", transcript=False)
        self.record_session("S1")
        self.ok("finish", "--task", folder, "--report-file", "-", input="Done.")
        rows = json.loads(Path(self.entry(), "sessions.json").read_text())
        self.assertEqual([(row["session_id"], row["round"], row["role"], row["since"]) for row in rows],
                         [(session, entry["round"], "execute", entry["started"])
                          for session in ("C1", "S1") for entry in starts])

    def test_R1_a_session_recorded_before_the_task_started_still_registers_at_finish(self):
        self.record_session("C1", transcript=False)
        folder = self.start()["dir"]
        self.drive(folder, "finish")
        self.record_session("C1", transcript=False)
        self.ok("finish", "--task", folder, "--report-file", "-", input="Done.")
        rows = json.loads(Path(self.entry(), "sessions.json").read_text())
        self.assertEqual([row["session_id"] for row in rows], ["C1"])

    def test_R8_the_invoice_bills_each_response_to_the_round_that_was_running(self):
        folder, document = self.three_round_task()
        document["started"] = "2026-10-21T10:00:00.000Z"
        document["flow"]["round_starts"] = [{"round": 1, "started": "2026-10-21T10:00:00.000Z"},
                                            {"round": 2, "started": "2026-10-21T10:10:00.000Z"},
                                            {"round": 3, "started": "2026-10-21T10:20:00.000Z"}]
        self.put(folder, "progress.json", document)
        self.record_session("S1", [("first", "2026-10-21T10:05:00.000Z"),
                                   ("second", "2026-10-21T10:15:00.000Z"),
                                   ("third", "2026-10-21T10:25:00.000Z")], self.entry())
        self.ok("finish", "--task", folder, "--report-file", "-", input="Done in three rounds.")
        written = subprocess.run([sys.executable, str(SCRIPTS / "invoice.py"), "write", "--entry", self.entry()],
                                 capture_output=True, text=True, env=self.env)
        self.assertEqual(written.returncode, 0, written.stdout + written.stderr)
        data = json.loads(Path(self.entry(), "invoice.json").read_text())
        billed = {}
        for task in data["tasks"]:
            billed[task["round"]] = billed.get(task["round"], 0) + task["input"]
        self.assertEqual(billed, {1: 200, 2: 100, 3: 100})

    def test_a_progress_file_without_round_starts_registers_no_row_for_its_unrecorded_rounds(self):
        folder, document = self.three_round_task()
        document["flow"]["round_starts"] = document["flow"]["round_starts"][:1]
        self.put(folder, "progress.json", document)
        later = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
        self.record_session("S1", [("abc", later)], self.entry())
        self.ok("finish", "--task", folder, "--report-file", "-", input="Done.")
        rows = json.loads(Path(self.entry(), "sessions.json").read_text())
        self.assertEqual([(row["session_id"], row["round"]) for row in rows], [("S1", 1)])

    def test_a_progress_file_with_no_round_starts_at_all_finishes_and_registers_nothing(self):
        folder, document = self.three_round_task()
        del document["flow"]["round_starts"]
        self.put(folder, "progress.json", document)
        later = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
        self.record_session("S1", [("abc", later)], self.entry())
        self.ok("finish", "--task", folder, "--report-file", "-", input="Done.")
        self.assertFalse(Path(self.entry(), "sessions.json").exists())

    def test_the_closing_report_is_filed_under_the_last_rounds_plan(self):
        folder = self.start()["dir"]
        self.qa_results = [self.qa_handoff("not ready", [finding("blocking", "Tests fail on empty input")])]
        self.drive(folder, "finish")
        self.ok("finish", "--task", folder, "--report-file", "-", input="Fixed in round two.")
        entry = Path(self.entry())
        self.assertEqual(entry.joinpath("report-02.md").read_text(), "Fixed in round two.\n")
        self.assertTrue(entry.joinpath("events-02.jsonl").is_file())
        self.assertFalse(entry.joinpath("report-01.md").exists())


class TestStop(TaskTestCase):
    def test_stop_writes_stage_failed_and_run_finished_failed_and_ends_the_task(self):
        folder = self.start()["dir"]
        self.next(folder)
        self.ok("stop", "--task", folder, "--reason", "-", input="the user changed their mind")
        tail = self.events(folder)[-2:]
        self.assertEqual([e["type"] for e in tail], ["stage.failed", "run.finished"])
        self.assertEqual((tail[0]["payload"]["stage"], tail[0]["payload"]["reason"]),
                         ("Refine", "the user changed their mind"))
        self.assertEqual(tail[1]["payload"]["status"], "failed")
        action = self.next(folder)
        self.assertEqual((action["action"], action["status"]), ("stop", "stopped"))
        self.assertNotEqual(self.run_task("stop", "--task", folder, "--reason", "again").returncode, 0)

    def test_finish_before_the_task_is_green_is_refused(self):
        folder = self.start()["dir"]
        result = self.run_task("finish", "--task", folder, "--report-file", "-", input="Not yet.")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not ready to finish", result.stderr)


class TestUsagePerCycle(JournalTaskCase):
    def test_R15_each_usage_event_names_the_cycle_that_was_running_when_its_call_started(self):
        folder = self.start()["dir"]
        self.qa_results = [self.qa_handoff("not ready", [finding("blocking", "Tests fail on empty input")])]
        self.drive(folder, "finish")
        document = self.progress(folder)
        self.assertEqual([cycle["cycle"] for cycle in document["flow"]["cycles"]], [1, 2])
        document["started"] = "2026-10-21T10:00:00.000Z"
        document["flow"]["cycles"] = [{"cycle": 1, "started": "2026-10-21T10:00:00.000Z"},
                                      {"cycle": 2, "started": "2026-10-21T10:10:00.000Z"}]
        self.put(folder, "progress.json", document)
        self.record_session("S1", [("first", "2026-10-21T10:05:00.000Z"),
                                   ("second", "2026-10-21T10:15:00.000Z")], self.entry())

        self.ok("finish", "--task", folder, "--report-file", "-", input="Fixed in round two.")

        usage = {e["payload"]["call_id"]: e["payload"]["cycle"]
                 for e in self.archived_events(folder) if e["type"] == "usage.reported"
                 and e["payload"]["call_id"] != "main"}
        self.assertEqual(usage, {"first": 1, "second": 2})

    def test_R15_a_task_that_ran_one_cycle_records_it_and_reports_cycle_1(self):
        folder = self.start()["dir"]
        self.drive(folder, "finish")
        self.record_session("S1", [("only", (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat())],
                            self.entry())
        self.ok("finish", "--task", folder, "--report-file", "-", input="Done.")
        self.assertEqual([c["cycle"] for c in self.progress(folder)["flow"]["cycles"]], [1])
        usage = {e["payload"]["cycle"] for e in self.archived_events(folder)
                 if e["type"] == "usage.reported"}
        self.assertEqual(usage, {1})


class TestEventsStayValid(TaskTestCase):
    def test_every_event_of_a_full_run_with_a_fix_cycle_validates_and_seq_has_no_gap(self):
        self.scope = {"needs_spec": True}
        folder = self.start()["dir"]
        self.review_results = [[finding("blocking")], []]
        self.drive(folder, "finish")
        self.ok("finish", "--task", folder, "--report-file", "-", input="Done after one fix cycle.")
        found = self.events(folder)
        self.assertEqual([e["seq"] for e in found], list(range(1, len(found) + 1)))
        types = [e["type"] for e in found]
        for expected in ("run.started", "stage.started", "stage.completed", "check.result",
                         "finding.reported", "cycle.started", "files.changed", "run.finished"):
            self.assertIn(expected, types)
        self.assertEqual(types[-1], "run.finished")
        fix_steps = [e for e in found if e["type"] == "stage.started" and e["payload"]["stage"] == "QA"]
        self.assertEqual([e["payload"]["cycle"] for e in fix_steps], [1, 2])


if __name__ == "__main__":
    unittest.main(verbosity=2)

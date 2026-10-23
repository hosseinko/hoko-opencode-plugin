#!/usr/bin/env python3
"""Tests for events.py — a scratch repo root per case, every event checked against a
fixture copy of hoko-code's `schemas/hoko-events.v1.json` by a small stdlib validator."""

import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

import events
import settings

SCRIPTS = Path(__file__).resolve().parent
SCHEMA = json.loads((SCRIPTS / "fixtures" / "hoko-events.v1.json").read_text(encoding="utf-8"))

ULID = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")
TIMESTAMP = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")
ENVELOPE = {"v", "event_id", "run_id", "seq", "ts", "type", "project", "payload"}
RUN_ID = "01JAB3K9V6T2Q8M4ZC7XWYN5RD"


def has_type(value, name):
    if name == "null":
        return value is None
    if name == "boolean":
        return isinstance(value, bool)
    if name == "string":
        return isinstance(value, str)
    if name == "array":
        return isinstance(value, list)
    if name == "object":
        return isinstance(value, dict)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    raise AssertionError(f"the validator does not know the type {name!r}")


def matches(schema, value):
    """Whether `value` satisfies `schema`, for the keywords hoko-events.v1.json uses."""
    if "oneOf" in schema and sum(matches(branch, value) for branch in schema["oneOf"]) != 1:
        return False
    if "anyOf" in schema and not any(matches(branch, value) for branch in schema["anyOf"]):
        return False
    if "const" in schema and value != schema["const"]:
        return False
    if "enum" in schema and value not in schema["enum"]:
        return False
    if "type" in schema:
        names = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(has_type(value, name) for name in names):
            return False
    if "pattern" in schema and not (isinstance(value, str) and re.search(schema["pattern"], value)):
        return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            return False
        if "maximum" in schema and value > schema["maximum"]:
            return False
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            return False
    if isinstance(value, dict):
        if any(name not in value for name in schema.get("required", [])):
            return False
        for name, sub in schema.get("properties", {}).items():
            if name in value and not matches(sub, value[name]):
                return False
        if "propertyNames" in schema and not all(matches(schema["propertyNames"], n) for n in value):
            return False
        if "additionalProperties" in schema and "properties" not in schema:
            if not all(matches(schema["additionalProperties"], item) for item in value.values()):
                return False
    if isinstance(value, list) and "items" in schema:
        if not all(matches(schema["items"], item) for item in value):
            return False
    return True


def read_events(path):
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


def assert_valid_events(test, path):
    """Every line of the events file at `path` validates; returns the events."""
    found = read_events(path)
    test.assertTrue(found, f"no events in {path}")
    for event in found:
        test.assertTrue(matches(SCHEMA, event), f"does not validate: {json.dumps(event)}")
    return found


class EventsTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve() / "my-repo"
        self.root.mkdir()
        self.run_file = self.root / ".ai" / "runs" / RUN_ID / "events.jsonl"
        self.isolate({})
        events._noted = False

    def isolate(self, env):
        """Settings read from `env` alone, never from a real hoko.json."""
        patches = [mock.patch.object(settings, "CONFIG_DIRS", ()),
                   mock.patch.dict(os.environ, env)]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def git(self, *args):
        result = subprocess.run(["git", "-C", str(self.root), *args], capture_output=True,
                                text=True, env={**os.environ, "GIT_AUTHOR_NAME": "t",
                                                "GIT_AUTHOR_EMAIL": "t@example.com",
                                                "GIT_COMMITTER_NAME": "t",
                                                "GIT_COMMITTER_EMAIL": "t@example.com"})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout


class TestEnvelope(EventsTestCase):
    def test_every_event_carries_the_eight_envelope_fields(self):
        event = events.emit(self.root, RUN_ID, "run.finished", {"status": "done"})
        self.assertEqual(set(event), ENVELOPE)
        self.assertEqual(set(read_events(self.run_file)[0]), ENVELOPE)

    def test_the_envelope_carries_version_ulid_utc_millisecond_time_and_project_name(self):
        events.emit(self.root, RUN_ID, "run.finished", {"status": "done"})
        event = read_events(self.run_file)[0]
        self.assertEqual(event["v"], 1)
        self.assertEqual(event["run_id"], RUN_ID)
        self.assertEqual(event["type"], "run.finished")
        self.assertEqual(event["project"], "my-repo")
        self.assertRegex(event["event_id"], ULID)
        self.assertRegex(event["ts"], TIMESTAMP)

    def test_an_event_that_validates_is_accepted_by_the_schema_check(self):
        events.emit(self.root, RUN_ID, "run.finished", {"status": "done", "reason": "extra fields stay open"})
        assert_valid_events(self, self.run_file)

    def test_the_schema_check_rejects_an_event_that_does_not_validate(self):
        events.emit(self.root, RUN_ID, "run.finished", {"status": "sideways"})
        events.emit(self.root, RUN_ID, "run.unknown", {})
        for event in read_events(self.run_file):
            self.assertFalse(matches(SCHEMA, event), json.dumps(event))

    def test_the_payloads_the_plugin_writes_validate_against_the_committed_schema(self):
        samples = [
            ("run.started", {"source": "plan", "text": "# Plan", "backend": "opencode",
                             "path": ".ai/plans/p.md",
                             "models": {"Implement": "opencode-go/deepseek-v4-flash"}, "presets": [],
                             "loop_limit": 3, "engine": "hoko-plugin", "plugin_version": "1.14.5",
                             "task": "p"}),
            ("stage.started", {"stage": "Implement", "cycle": 1, "model": "opencode-go/deepseek-v4-flash",
                               "step": 1, "steps": 2, "title": "First", "round": 1}),
            ("stage.started", {"stage": "Implement", "cycle": 1, "step": 1}),
            ("check.result", {"stage": "Implement", "cycle": 1, "check": "fast-gate", "status": "passed",
                              "duration_ms": 12, "exit_code": 0, "step": 1}),
            ("stage.completed", {"stage": "Implement", "cycle": 1, "outcome": "done", "commit": None,
                                 "no_op": True}),
            ("stage.failed", {"stage": "QA", "cycle": 1, "reason": "gate red"}),
            ("files.changed", {"files": [{"status": "A", "path": "a.py"}]}),
            ("files.changed", {"error": "no base commit recorded"}),
            ("usage.reported", events.usage_payloads([{
                "agent_type": "hoko-plan-executor", "agent_id": "a1",
                "model": "opencode-go/deepseek-v4-flash",
                "input_tokens": 1, "output_tokens": 2, "cache_read_tokens": 3,
                "cache_write_5m_tokens": 4, "cache_write_1h_tokens": 5, "cost": 0.5, "duration_ms": 9}])[0]),
            ("run.finished", {"status": "failed", "reason": "stopped"}),
        ]
        for type_, payload in samples:
            events.emit(self.root, RUN_ID, type_, payload)
        self.assertEqual(len(assert_valid_events(self, self.run_file)), len(samples))

    def test_the_run_id_must_be_a_plain_name_so_it_cannot_leave_the_events_directory(self):
        with redirect_stderr(io.StringIO()):
            self.assertIsNone(events.emit(self.root, "../escape", "run.finished", {"status": "done"}))
        self.assertFalse((self.root / ".ai" / "escape").exists())
        self.assertFalse((self.root / ".ai" / "runs").exists())


class TestIdentifiers(unittest.TestCase):
    def test_a_ulid_is_26_crockford_characters_and_sorts_by_time(self):
        earlier, later = events.ulid(1_000), events.ulid(2_000)
        self.assertRegex(earlier, ULID)
        self.assertLess(earlier, later)


class TestSequence(EventsTestCase):
    def test_seq_counts_one_two_three_in_one_process(self):
        for _ in range(3):
            events.emit(self.root, RUN_ID, "run.finished", {"status": "done"})
        self.assertEqual([e["seq"] for e in read_events(self.run_file)], [1, 2, 3])

    def test_two_processes_writing_one_run_number_their_events_with_no_gap_and_no_repeat(self):
        code = (
            "import sys; sys.path.insert(0, sys.argv[1]); import events\n"
            "for _ in range(40):\n"
            "    events.emit(sys.argv[2], sys.argv[3], 'run.finished', {'status': 'done'})\n"
        )
        env = {**os.environ, "HOKO_EVENTS": "true"}
        children = [subprocess.Popen([sys.executable, "-c", code, str(SCRIPTS), str(self.root), RUN_ID],
                                     env=env, cwd=str(self.root)) for _ in range(2)]
        for child in children:
            self.assertEqual(child.wait(timeout=120), 0)
        found = assert_valid_events(self, self.run_file)
        self.assertEqual([e["seq"] for e in found], list(range(1, 81)))


class TestFailedWrite(EventsTestCase):
    def fail_one_write(self):
        real = os.write
        calls = {"n": 0}

        def flaky(descriptor, data):
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError("disk full")
            return real(descriptor, data)

        return mock.patch.object(events.os, "write", flaky)

    def test_a_failed_write_writes_no_further_events_for_that_run(self):
        with self.fail_one_write(), redirect_stderr(io.StringIO()):
            self.assertIsNone(events.emit(self.root, RUN_ID, "run.finished", {"status": "done"}))
            self.assertIsNone(events.emit(self.root, RUN_ID, "run.finished", {"status": "done"}))
        self.assertTrue((self.run_file.parent / "events.disabled").is_file())
        self.assertEqual(self.run_file.read_text() if self.run_file.exists() else "", "")

    def test_a_failed_write_prints_one_note_on_stderr(self):
        captured = io.StringIO()
        with self.fail_one_write(), redirect_stderr(captured):
            events.emit(self.root, RUN_ID, "run.finished", {"status": "done"})
            events.emit(self.root, RUN_ID, "run.finished", {"status": "done"})
        self.assertEqual(captured.getvalue(), "events not recorded: disk full\n")

    def test_another_run_keeps_writing_after_one_run_failed(self):
        with self.fail_one_write(), redirect_stderr(io.StringIO()):
            events.emit(self.root, RUN_ID, "run.finished", {"status": "done"})
            self.assertIsNotNone(events.emit(self.root, "01OTHERRUN", "run.finished", {"status": "done"}))

    def test_an_unwritable_events_directory_is_a_note_not_an_exception(self):
        blocker = self.root / "blocker"
        blocker.write_text("a file, not a directory")
        self.isolate({"HOKO_EVENTS_DIR": "blocker/runs"})
        captured = io.StringIO()
        with redirect_stderr(captured):
            self.assertIsNone(events.emit(self.root, RUN_ID, "run.finished", {"status": "done"}))
        self.assertIn("events not recorded:", captured.getvalue())


class TestGitignore(EventsTestCase):
    def test_the_events_folder_gets_a_gitignore_that_ignores_everything(self):
        events.emit(self.root, RUN_ID, "run.finished", {"status": "done"})
        self.assertEqual((self.root / ".ai" / ".gitignore").read_text(), "*\n")

    def test_the_gitignore_exists_before_the_run_directory_is_created(self):
        run_directory = self.root / ".ai" / "runs" / RUN_ID
        seen = {}
        real = events.ensure_ignored

        def watch(top):
            seen["run_directory_existed"] = run_directory.exists()
            real(top)

        with mock.patch.object(events, "ensure_ignored", watch):
            events.emit(self.root, RUN_ID, "run.finished", {"status": "done"})
        self.assertFalse(seen["run_directory_existed"])
        self.assertTrue((self.root / ".ai" / ".gitignore").is_file())

    def test_a_gitignore_the_user_already_has_is_left_alone(self):
        (self.root / ".ai").mkdir()
        (self.root / ".ai" / ".gitignore").write_text("keep-me\n")
        events.emit(self.root, RUN_ID, "run.finished", {"status": "done"})
        self.assertEqual((self.root / ".ai" / ".gitignore").read_text(), "keep-me\n")

    def test_git_add_all_never_stages_an_event_file(self):
        self.git("init", "-q")
        events.emit(self.root, RUN_ID, "run.finished", {"status": "done"})
        self.git("add", "-A")
        self.assertEqual(self.git("diff", "--cached", "--name-only"), "")

    def test_an_events_dir_at_the_repository_root_is_refused_rather_than_ignoring_the_repository(self):
        self.isolate({"HOKO_EVENTS_DIR": "."})
        with redirect_stderr(io.StringIO()):
            self.assertIsNone(events.emit(self.root, RUN_ID, "run.finished", {"status": "done"}))
        self.assertFalse((self.root / ".gitignore").exists())


class TestEventsSetting(EventsTestCase):
    def test_with_events_false_no_events_file_or_folder_is_created(self):
        self.isolate({"HOKO_EVENTS": "false"})
        self.assertIsNone(events.emit(self.root, RUN_ID, "run.finished", {"status": "done"}))
        self.assertFalse((self.root / ".ai").exists())

    def test_the_events_dir_setting_moves_the_run_folder(self):
        self.isolate({"HOKO_EVENTS_DIR": "logs/runs"})
        events.emit(self.root, RUN_ID, "run.finished", {"status": "done"})
        self.assertTrue((self.root / "logs" / "runs" / RUN_ID / "events.jsonl").is_file())
        self.assertEqual((self.root / "logs" / ".gitignore").read_text(), "*\n")

    def test_a_run_without_an_id_writes_nothing(self):
        self.assertIsNone(events.emit(self.root, None, "run.finished", {"status": "done"}))
        self.assertFalse((self.root / ".ai").exists())


class TestPayloadHelpers(EventsTestCase):
    def test_files_changed_reads_added_modified_and_deleted_paths_from_the_base(self):
        self.git("init", "-q")
        (self.root / "keep.py").write_text("one\n")
        (self.root / "gone.py").write_text("one\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        base = self.git("rev-parse", "HEAD").strip()
        (self.root / "keep.py").write_text("two\n")
        (self.root / "gone.py").unlink()
        (self.root / "new file.py").write_text("new\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "work")

        payload = events.files_changed_payload(self.root, base)
        self.assertEqual(sorted((f["status"], f["path"]) for f in payload["files"]),
                         [("A", "new file.py"), ("D", "gone.py"), ("M", "keep.py")])

    def test_files_changed_reports_an_error_without_a_base(self):
        self.assertEqual(events.files_changed_payload(self.root, None),
                         {"error": "no base commit recorded"})

    def test_files_changed_reports_an_error_when_git_cannot_diff(self):
        self.git("init", "-q")
        self.assertIn("error", events.files_changed_payload(self.root, "deadbeef"))

    def call(self, agent_type, role="execute"):
        return {"agent_type": agent_type, "agent_id": "a1", "role": role,
                "model": "opencode-go/deepseek-v4-flash",
                "input_tokens": 1, "output_tokens": 2, "cache_read_tokens": 3,
                "cache_write_5m_tokens": 4, "cache_write_1h_tokens": 5, "cost": 0.5, "duration_ms": 9}

    def test_the_backend_is_opencode_and_every_hoko_agent_maps_to_its_stage(self):
        self.assertEqual(events.BACKEND, "opencode")
        self.assertEqual(events.AGENT_STAGES, {
            "hoko-plan-executor": "Implement", "hoko-quality-assurance": "QA",
            "hoko-final-reviewer": "Review", "hoko-spec-writer": "Spec",
            "hoko-specifier": "Refine", "hoko-planner": "Plan"})

    def test_usage_payloads_map_the_agent_to_a_stage_and_role_and_sum_cache_writes(self):
        implementer, reviewer, qa = (events.usage_payloads([self.call(kind)])[0]
                                     for kind in ("hoko-plan-executor", "hoko-final-reviewer",
                                                  "hoko-quality-assurance"))
        self.assertEqual((implementer["stage"], implementer["role"]), ("Implement", "implementer"))
        self.assertEqual((reviewer["stage"], reviewer["role"]), ("Review", "reviewer"))
        self.assertEqual((qa["stage"], qa["role"]), ("QA", "reviewer"))
        self.assertEqual(implementer["cache_creation_tokens"], 9)
        self.assertEqual((implementer["call_id"], implementer["cost_source"], implementer["cost_usd"]),
                         ("a1", "computed", 0.5))
        self.assertEqual(implementer["backend"], "opencode")

    def test_usage_payloads_count_an_unmapped_agent_as_implementation_and_a_planning_one_as_plan(self):
        self.assertEqual(events.usage_payloads([self.call("Explore")])[0]["stage"], "Implement")
        planning = events.usage_payloads([self.call("Explore", role="plan")])[0]
        self.assertEqual((planning["stage"], planning["role"]), ("Plan", "planner"))

    def test_usage_payloads_give_a_call_the_cycle_running_when_it_started(self):
        cycles = [{"cycle": 1, "started": "2026-10-21T10:00:00.000Z"},
                  {"cycle": 2, "started": "2026-10-21T10:10:00.000Z"},
                  {"cycle": 3, "started": "2026-10-21T10:20:00.000Z"}]
        starts = ["2026-10-21T09:00:00.000Z", "2026-10-21T10:05:00.000Z", "2026-10-21T10:10:00.000Z",
                  "2026-10-21T10:19:59.000Z", "2026-10-21T11:00:00.000Z", None]
        calls = [{**self.call("hoko-plan-executor"), "started": started} for started in starts]
        self.assertEqual([p["cycle"] for p in events.usage_payloads(calls, cycles)], [1, 1, 2, 2, 3, 1])

    def test_usage_payloads_without_cycles_keep_every_call_in_cycle_1(self):
        calls = [{**self.call("hoko-plan-executor"), "started": "2026-10-21T10:15:00.000Z"}]
        self.assertEqual(events.usage_payloads(calls)[0]["cycle"], 1)
        self.assertEqual(events.usage_payloads(calls, [])[0]["cycle"], 1)
        self.assertEqual(events.usage_payloads(calls, [{"cycle": "x"}, "junk"])[0]["cycle"], 1)


if __name__ == "__main__":
    unittest.main()

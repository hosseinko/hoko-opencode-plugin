#!/usr/bin/env python3
"""Tests for migrate-analytics.py — a canned journal root and analytics root per case,
the CLI driven as the user runs it, every synthesized event checked against the
committed event schema."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from test_events import assert_valid_events

SCRIPTS = Path(__file__).resolve().parent
SCRIPT = SCRIPTS / "migrate-analytics.py"
PLAN_TIME = datetime(2026, 10, 21, 10, 0, tzinfo=timezone.utc)
REPORT_TIME = datetime(2026, 10, 21, 10, 30, tzinfo=timezone.utc)


def snapshot(root):
    return {str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in sorted(root.rglob("*")) if path.is_file()}


class MigrateTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        self.journal = self.tmp / "Journal"
        self.entry = self.journal / "shop" / "20261022-0950-speed"
        self.entry.mkdir(parents=True)
        self.root = self.tmp / "analytics"
        self.folder = self.root / "shop" / "20261022-0950-speed"
        self.env = {name: value for name, value in os.environ.items() if not name.startswith("HOKO_")}
        self.env["HOME"] = str(self.tmp / "home")

    def write(self, name, text):
        path = self.entry / name
        path.write_text(text, encoding="utf-8")
        return path

    def dated(self, name, text, moment):
        path = self.write(name, text)
        os.utime(path, (moment.timestamp(), moment.timestamp()))
        return path

    def command(self):
        return subprocess.run([sys.executable, str(SCRIPT), str(self.journal), str(self.root)],
                              capture_output=True, text=True, env=self.env)

    def migrate(self):
        proc = self.command()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc

    def events(self, name="events-01.jsonl"):
        return [json.loads(line) for line in
                (self.folder / name).read_text(encoding="utf-8").splitlines()]


class TestLayout(MigrateTestCase):
    def test_req17_a_migrated_entry_lands_in_its_projects_folder_under_the_analytics_root(self):
        self.write("sessions.json", "[]")
        self.migrate()
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()),
                         ["entry.json", "sessions.json"])
        self.assertFalse((self.entry / "sessions.json").exists())


class TestMoving(MigrateTestCase):
    def test_req18_sessions_invoices_and_every_event_copy_move_into_the_entry_folder(self):
        contents = {name: f"{name}\n" for name in
                    ("sessions.json", "invoice.json", "invoice.md", "events-01.jsonl", "events-02.jsonl")}
        for name, text in contents.items():
            self.write(name, text)
        self.migrate()
        for name, text in contents.items():
            self.assertEqual((self.folder / name).read_text(), text)
            self.assertFalse((self.entry / name).exists())

    def test_req18_a_file_already_in_the_target_is_overwritten(self):
        self.folder.mkdir(parents=True)
        (self.folder / "invoice.md").write_text("old\n")
        self.write("invoice.md", "new\n")
        self.migrate()
        self.assertEqual((self.folder / "invoice.md").read_text(), "new\n")


class TestSynthesis(MigrateTestCase):
    def test_req2_a_round_without_an_event_copy_is_backfilled_with_a_slim_migrated_event(self):
        self.dated("plan-01.md", "# Speed up the shop\n\n## Goal\n" + "The shop is slow.\n" * 500,
                   PLAN_TIME)
        self.dated("report-01.md", "# Report\n", REPORT_TIME)
        self.migrate()

        found = self.events()
        self.assertEqual([event["type"] for event in found], ["run.started", "run.finished"])
        self.assertEqual(found[0]["payload"], {
            "source": "plan", "text": "Speed up the shop",
            "path": str((self.entry / "plan-01.md").resolve()),
            "backend": "opencode", "migrated": True})
        self.assertLess(len((self.folder / "events-01.jsonl").read_bytes()), 1024)

    def test_req3_a_report_only_round_gains_a_single_run_finished_dated_from_its_report(self):
        self.dated("report-02.md", "# Report\n", REPORT_TIME)
        self.migrate()

        self.assertEqual([(event["type"], event["ts"], event["seq"])
                          for event in self.events("events-02.jsonl")],
                         [("run.finished", "2026-10-21T10:30:00.000Z", 1)])

    def test_req4_a_synthesized_round_is_written_under_the_run_id_entry_rnn(self):
        self.dated("plan-03.md", "# Plan\n", PLAN_TIME)
        self.migrate()

        self.assertEqual({event["run_id"] for event in self.events("events-03.jsonl")},
                         {"20261022-0950-speed-r03"})

    def test_req5_a_synthesized_run_started_sets_the_migrated_marker(self):
        self.dated("plan-01.md", "# Plan\n", PLAN_TIME)
        self.migrate()

        self.assertIs(self.events()[0]["payload"]["migrated"], True)

    def test_req6_a_synthesized_run_started_sets_the_text_to_the_plans_first_heading(self):
        self.dated("plan-01.md", "Some preamble\n\n# Speed up the shop\n\n## Goal\n", PLAN_TIME)
        self.migrate()

        self.assertEqual(self.events()[0]["payload"]["text"], "Speed up the shop")

    def test_req6_without_a_heading_the_text_is_the_plans_first_non_empty_line(self):
        self.dated("plan-01.md", "\nShip the slim payload\n## Goal\n", PLAN_TIME)
        self.migrate()

        self.assertEqual(self.events()[0]["payload"]["text"], "Ship the slim payload")

    def test_req6_the_text_is_cut_to_120_characters(self):
        self.dated("plan-01.md", "# " + "x" * 150 + "\n", PLAN_TIME)
        self.migrate()

        self.assertEqual(self.events()[0]["payload"]["text"], "x" * 120)

    def test_req7_a_synthesized_run_started_sets_the_path_to_the_journal_plan(self):
        self.dated("plan-01.md", "# Plan\n", PLAN_TIME)
        self.migrate()

        self.assertEqual(self.events()[0]["payload"]["path"],
                         str((self.entry / "plan-01.md").resolve()))

    def test_req19_a_round_without_an_event_copy_gains_one_dated_from_its_plan_and_report(self):
        self.dated("plan-01.md", "# Plan\n", PLAN_TIME)
        self.dated("report-01.md", "# Report\n", REPORT_TIME)
        self.migrate()

        found = [json.loads(line) for line in
                 (self.folder / "events-01.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([(event["type"], event["ts"]) for event in found], [
            ("run.started", "2026-10-21T10:00:00.000Z"),
            ("run.finished", "2026-10-21T10:30:00.000Z")])
        self.assertEqual({event["run_id"] for event in found}, {"20261022-0950-speed-r01"})

    def test_req19_the_synthesized_events_validate_against_the_committed_schema(self):
        self.dated("plan-01.md", "# Plan\n", PLAN_TIME)
        self.dated("report-01.md", "# Report\n", REPORT_TIME)
        self.migrate()
        assert_valid_events(self, self.folder / "events-01.jsonl")

    def test_req19_a_round_with_an_event_copy_keeps_it_unchanged(self):
        self.write("events-01.jsonl", '{"kept": true}\n')
        self.dated("plan-01.md", "# Plan\n", PLAN_TIME)
        self.dated("report-01.md", "# Report\n", REPORT_TIME)
        self.migrate()
        self.assertEqual((self.folder / "events-01.jsonl").read_text(), '{"kept": true}\n')

    def test_req19_a_round_with_neither_a_plan_nor_a_report_is_skipped_with_a_note(self):
        self.write("sessions.json", json.dumps([{"session_id": "S1", "round": 2, "role": "execute"}]))
        proc = self.migrate()
        self.assertFalse((self.folder / "events-02.jsonl").exists())
        self.assertIn("round 02", proc.stderr)
        self.assertIn("skipped", proc.stderr)


class TestLink(MigrateTestCase):
    def test_req20_entry_json_names_the_journal_entry_and_lists_its_sessions(self):
        self.write("sessions.json", json.dumps([
            {"session_id": "S1", "round": 1, "role": "plan"},
            {"session_id": "S2", "round": 1, "role": "execute"},
        ]))
        self.migrate()
        link = json.loads((self.folder / "entry.json").read_text())
        self.assertEqual(link["journal_entry"], str(self.entry.resolve()))
        self.assertEqual((link["project"], link["entry"]), ("shop", "20261022-0950-speed"))
        self.assertEqual(link["session_ids"], ["S1", "S2"])


class TestArguments(MigrateTestCase):
    def test_req21_the_journal_root_and_the_analytics_root_are_its_two_arguments(self):
        self.write("sessions.json", "[]")
        proc = self.command()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue((self.folder / "sessions.json").is_file())


class TestSecondRun(MigrateTestCase):
    def test_a_second_run_changes_nothing(self):
        self.write("sessions.json", json.dumps([{"session_id": "S1", "round": 1, "role": "plan"}]))
        self.write("invoice.json", "{}\n")
        self.dated("plan-01.md", "# Plan\n", PLAN_TIME)
        self.dated("report-01.md", "# Report\n", REPORT_TIME)
        self.migrate()
        before = snapshot(self.root)
        self.migrate()
        self.assertEqual(snapshot(self.root), before)


if __name__ == "__main__":
    unittest.main()

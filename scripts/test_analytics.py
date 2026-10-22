#!/usr/bin/env python3
"""Tests for analytics.py — settings read from the environment alone, a temp dir per case."""

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import analytics
import settings


class AnalyticsTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        self.entry = self.tmp / "Journal" / "shop" / "20261022-0950-speed"
        self.entry.mkdir(parents=True)
        self.root = self.tmp / "analytics"
        self.folder = self.root / "shop" / "20261022-0950-speed"
        patches = [mock.patch.object(settings, "CONFIG_DIRS", ()), mock.patch.dict(os.environ)]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        for name in [name for name in os.environ if name.startswith("HOKO_")]:
            del os.environ[name]

    def use(self, path):
        os.environ["HOKO_ANALYTICS_PATH"] = str(path)

    def register(self, *session_ids):
        self.folder.mkdir(parents=True, exist_ok=True)
        rows = [{"session_id": sid, "transcript_path": "", "round": 1, "role": "execute"} for sid in session_ids]
        (self.folder / "sessions.json").write_text(json.dumps(rows))

    def read_link(self):
        return json.loads((self.folder / "entry.json").read_text())

    def capture(self, function, *args, **kwargs):
        with contextlib.redirect_stderr(io.StringIO()) as note:
            function(*args, **kwargs)
        return note.getvalue()


class TestRoot(AnalyticsTestCase):
    def test_an_unset_analytics_path_has_no_root(self):
        self.assertIsNone(analytics.analytics_root())

    def test_a_leading_tilde_expands_to_the_home_directory(self):
        os.environ["HOME"] = str(self.tmp / "home")
        self.use("~/stats")
        self.assertEqual(analytics.analytics_root(), self.tmp / "home" / "stats")

    def test_a_dollar_variable_expands(self):
        os.environ["HOKO_TEST_BASE"] = str(self.tmp / "base")
        self.use("$HOKO_TEST_BASE/stats")
        self.assertEqual(analytics.analytics_root(), self.tmp / "base" / "stats")


class TestFolder(AnalyticsTestCase):
    def test_r8_an_unset_analytics_path_keeps_the_analytics_in_the_journal_entry(self):
        analytics.link(self.entry, "run-1")
        self.assertEqual(analytics.folder_for(self.entry), self.entry)
        self.assertEqual(os.listdir(self.entry), [])

    def test_an_empty_analytics_path_maps_the_entry_to_itself(self):
        self.assertEqual(analytics.folder_for(self.entry), self.entry)

    def test_the_folder_mirrors_the_entrys_project_and_name_under_the_root(self):
        self.use(self.root)
        self.assertEqual(analytics.folder_for(self.entry), self.folder)

    def test_the_mapping_is_idempotent_so_an_analytics_folder_maps_to_itself(self):
        self.use(self.root)
        self.assertEqual(analytics.folder_for(self.folder), self.folder)

    def test_a_relative_entry_is_made_absolute(self):
        self.use(self.root)
        relative = os.path.relpath(self.entry)
        self.assertEqual(analytics.folder_for(relative), self.folder)


class TestJournalEntryOf(AnalyticsTestCase):
    def test_a_journal_entry_names_itself(self):
        self.use(self.root)
        self.assertEqual(analytics.journal_entry_of(self.entry), self.entry)

    def test_with_no_analytics_root_any_path_names_itself(self):
        self.assertEqual(analytics.journal_entry_of(self.folder), self.folder)

    def test_an_analytics_folder_names_the_entry_its_link_does(self):
        self.use(self.root)
        self.folder.mkdir(parents=True)
        (self.folder / "entry.json").write_text(json.dumps({"journal_entry": str(self.entry)}))
        self.assertEqual(analytics.journal_entry_of(self.folder), self.entry)

    def test_an_analytics_folder_without_a_link_maps_through_the_journal_root(self):
        self.use(self.root)
        os.environ["HOKO_JOURNAL_PATH"] = str(self.tmp / "Journal")
        self.assertEqual(analytics.journal_entry_of(self.folder), self.entry)

    def test_an_analytics_folder_naming_no_journal_entry_names_none(self):
        self.use(self.root)
        self.assertIsNone(analytics.journal_entry_of(self.folder))


class TestGuard(AnalyticsTestCase):
    def test_an_os_error_becomes_a_note_naming_the_folder(self):
        def failing():
            with analytics.guard(self.folder):
                raise PermissionError("denied")

        note = self.capture(failing)
        self.assertIn(str(self.folder), note)
        self.assertIn("denied", note)

    def test_another_error_is_not_swallowed(self):
        with self.assertRaises(KeyError), analytics.guard(self.folder):
            raise KeyError("bug")


class TestLink(AnalyticsTestCase):
    def test_an_empty_analytics_path_writes_no_entry_json(self):
        analytics.link(self.entry, "run-1")
        self.assertEqual(os.listdir(self.entry), [])

    def test_no_journal_entry_writes_nothing_under_the_root(self):
        self.use(self.root)
        analytics.link(None, "run-1")
        self.assertFalse(self.root.exists())

    def test_the_link_names_the_entry_its_runs_and_its_sessions(self):
        self.use(self.root)
        self.register("S1", "S2")
        analytics.link(self.entry, "run-1")
        self.assertEqual(self.read_link(), {
            "journal_entry": str(self.entry), "project": "shop", "entry": "20261022-0950-speed",
            "run_ids": ["run-1"], "session_ids": ["S1", "S2"]})

    def test_the_folder_and_its_parents_are_created(self):
        self.use(self.root / "deep" / "er")
        analytics.link(self.entry)
        self.assertTrue((self.root / "deep" / "er" / "shop" / "20261022-0950-speed" / "entry.json").is_file())

    def test_a_session_registered_under_several_rounds_is_listed_once_in_first_seen_order(self):
        self.use(self.root)
        self.register("S2", "S1", "S2", "S1")
        analytics.link(self.entry)
        self.assertEqual(self.read_link()["session_ids"], ["S2", "S1"])

    def test_a_rewrite_keeps_the_run_ids_listed_and_adds_a_run_once(self):
        self.use(self.root)
        analytics.link(self.entry, "run-1")
        analytics.link(self.entry, "run-2")
        analytics.link(self.entry, "run-2")
        analytics.link(self.entry)
        self.assertEqual(self.read_link()["run_ids"], ["run-1", "run-2"])

    def test_an_unreadable_or_non_object_link_is_replaced(self):
        self.use(self.root)
        self.register("S1")
        for broken in ("{not json", "[1]", "null", ""):
            with self.subTest(broken=broken):
                (self.folder / "entry.json").write_text(broken)
                analytics.link(self.entry, "run-9")
                self.assertEqual((self.read_link()["run_ids"], self.read_link()["session_ids"]),
                                 (["run-9"], ["S1"]))

    def test_a_run_ids_value_that_is_not_a_list_of_strings_is_rebuilt(self):
        self.use(self.root)
        self.folder.mkdir(parents=True)
        (self.folder / "entry.json").write_text(json.dumps({"run_ids": "run-1"}))
        analytics.link(self.entry, "run-2")
        self.assertEqual(self.read_link()["run_ids"], ["run-2"])
        (self.folder / "entry.json").write_text(json.dumps({"run_ids": ["run-1", 7, None]}))
        analytics.link(self.entry)
        self.assertEqual(self.read_link()["run_ids"], ["run-1"])

    def test_no_temporary_file_is_left_beside_the_link(self):
        self.use(self.root)
        analytics.link(self.entry, "run-1")
        self.assertEqual(os.listdir(self.folder), ["entry.json"])

    def test_a_folder_that_cannot_be_created_is_a_note_not_an_error(self):
        blocker = self.tmp / "blocker"
        blocker.write_text("a file")
        self.use(blocker / "analytics")
        note = self.capture(analytics.link, self.entry, "run-1")
        self.assertIn(str(blocker / "analytics" / "shop" / "20261022-0950-speed"), note)
        self.assertEqual(os.listdir(self.entry), [])


class TestSessionIds(AnalyticsTestCase):
    def test_a_missing_or_malformed_registry_lists_none(self):
        self.folder.mkdir(parents=True)
        self.assertEqual(analytics.session_ids(self.folder), [])
        for broken in ("{not json", '{"a": 1}'):
            (self.folder / "sessions.json").write_text(broken)
            self.assertEqual(analytics.session_ids(self.folder), [])

    def test_rows_without_a_session_id_are_skipped(self):
        self.folder.mkdir(parents=True)
        (self.folder / "sessions.json").write_text(json.dumps([{"role": "plan"}, "x", {"session_id": "S1"}]))
        self.assertEqual(analytics.session_ids(self.folder), ["S1"])


if __name__ == "__main__":
    unittest.main()

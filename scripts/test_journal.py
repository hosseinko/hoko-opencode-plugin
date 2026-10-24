#!/usr/bin/env python3
"""Tests for journal.py — a scratch journal root and a scratch home per case.

Every case points `journalPath` (or HOKO_JOURNAL_PATH) and HOME at throwaway roots, so
the real journal and config are never touched.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import analytics
import journal
import settings
from test_plan_format import FENCED_LINES

SCRIPT = Path(__file__).resolve().parent / "journal.py"
PROMPT = "add a --dry-run flag\n\nit must not write anything, and `--dry-run` wins over --force"
PLAN = "## Goal\nShip a dry-run flag.\n\n## Steps\n### 1. Parse the flag\n- Files: cli.py\n"
REPORT = "All 2 steps done.\n\n- 1. Parse the flag — `a1b2c3d` cli: add --dry-run\n\nTests: `pytest -q` green."


class JournalTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.tmp = Path(self.tmpdir.name).resolve()
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.state = self.tmp / "state"
        self.state.mkdir()
        # A space in the root is deliberate — every real root is one somebody typed.
        self.journal = self.tmp / "my notes" / "journal"
        self.repo = self.tmp / "my-project"
        (self.repo / ".ai" / "plans").mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        self.plan = self.repo / ".ai" / "plans" / "20260902084632-ship-dry-run.md"
        self.plan.write_text(PLAN)
        self.prompt_file = self.tmp / "first.prompt"
        self.prompt_file.write_text(PROMPT)

    def run_script(self, *args, stdin=None, home=None, cwd=None, journal_root="default"):
        env = {name: value for name, value in os.environ.items() if not name.startswith("HOKO_")}
        env["HOME"] = str(home or self.home)
        env["HOKO_STATE_DIR"] = str(self.state)
        if journal_root == "default":
            env["HOKO_JOURNAL_PATH"] = str(self.journal)
        elif journal_root is not None:
            env["HOKO_JOURNAL_PATH"] = str(journal_root)
        Path(env["HOME"]).mkdir(parents=True, exist_ok=True)
        return subprocess.run([sys.executable, str(SCRIPT), *args], input=stdin,
                              capture_output=True, text=True, env=env,
                              cwd=str(cwd) if cwd else str(self.home))

    def write(self, *args, **kwargs):
        return self.run_script("write", *args, **kwargs)

    def filed(self):
        result = self.write("--plan", str(self.plan), "--prompt-file", str(self.prompt_file))
        self.assertEqual(result.returncode, 0, result.stderr.strip())
        return Path(result.stdout.strip())


class TestWrite(JournalTestCase):
    def test_write_creates_plan_01_under_the_project_folder(self):
        entry = self.filed()
        folder = entry.parent
        self.assertEqual(entry.name, "plan-01.md")
        self.assertEqual(folder.parent, self.journal / "my-project")
        self.assertTrue(folder.name.endswith("-ship-a-dry-run-flag"), folder.name)
        self.assertIn(PROMPT, (folder / "prompt.md").read_text())
        self.assertEqual(entry.read_text(), PLAN.strip() + "\n")

    def test_a_second_write_does_not_collide(self):
        first = self.filed()
        second = self.write("--plan", str(self.plan), "--prompt-file", str(self.prompt_file))
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertNotEqual(Path(second.stdout.strip()).parent, first.parent)

    def test_fence_widens_past_inner_backticks(self):
        backticked = self.tmp / "backticks.prompt"
        backticked.write_text("look at ```this``` block")
        result = self.write("--plan", str(self.plan), "--prompt-file", str(backticked))
        entry = Path(result.stdout.strip())
        self.assertIn("````text", (entry.parent / "prompt.md").read_text())

    def test_an_empty_prompt_is_refused(self):
        empty = self.tmp / "empty.prompt"
        empty.write_text("   \n")
        self.assertNotEqual(self.write("--plan", str(self.plan), "--prompt-file", str(empty)).returncode, 0)

    def test_a_missing_plan_is_refused(self):
        self.assertNotEqual(
            self.write("--plan", str(self.tmp / "nope.md"), "--prompt-file", str(self.prompt_file)).returncode, 0)

    def test_project_override_and_stdin_prompt(self):
        override = self.write("--plan", str(self.plan), "--prompt-file", "-",
                              "--project", "Other Project", stdin="from stdin")
        self.assertEqual(override.returncode, 0, override.stderr.strip())
        self.assertEqual(Path(override.stdout.strip()).parent.parent, self.journal / "other-project")

    def test_an_h1_wins_over_the_goal_and_a_slug_override_wins_over_both(self):
        h1 = self.tmp / "some-generated-slug.md"
        h1.write_text("# Retire the legacy importer\n\n## Goal\nSomething else entirely.\n")
        h1_entry = Path(self.write("--plan", str(h1), "--prompt-file", str(self.prompt_file),
                                   cwd=self.repo).stdout.strip())
        self.assertTrue(h1_entry.parent.name.endswith("-retire-the-legacy-importer"), h1_entry.parent.name)
        override = Path(self.write("--plan", str(h1), "--prompt-file", str(self.prompt_file),
                                   "--slug", "Parse Hejlsberg", cwd=self.repo).stdout.strip())
        self.assertTrue(override.parent.name.endswith("-parse-hejlsberg"), override.parent.name)

    def test_a_plan_with_no_title_falls_back_to_its_filename(self):
        bare = self.tmp / "20260902-fallback-slug.md"
        bare.write_text("- just a bullet\n")
        entry = Path(self.write("--plan", str(bare), "--prompt-file", str(self.prompt_file),
                                cwd=self.repo).stdout.strip())
        self.assertTrue(entry.parent.name.endswith("-fallback-slug"), entry.parent.name)

    def test_a_long_goal_is_cut_at_a_word_boundary(self):
        wordy = self.tmp / "wordy.md"
        wordy.write_text("## Goal\n" + "Rework the whole ingestion pipeline so that every supplier "
                         "feed is normalised before matching, including the legacy ones.\n")
        entry = Path(self.write("--plan", str(wordy), "--prompt-file", str(self.prompt_file),
                                cwd=self.repo).stdout.strip())
        slug = entry.parent.name.split("-", 2)[2]
        self.assertLessEqual(len(slug), 60, slug)
        self.assertFalse(slug.endswith("-"), slug)

    def test_a_plans_own_project_line_names_the_entry_without_the_override(self):
        stamped = self.tmp / "stamped.md"
        stamped.write_text("Project: explicit-project\n" + PLAN)
        result = self.write("--plan", str(stamped), "--prompt-file", str(self.prompt_file))
        self.assertEqual(result.returncode, 0, result.stderr.strip())
        self.assertEqual(Path(result.stdout.strip()).parent.parent, self.journal / "explicit-project")

    def test_a_non_git_project_resolves_by_its_ai_dir(self):
        bare = self.tmp / "no-git-project"
        (bare / ".ai" / "plans").mkdir(parents=True)
        plan = bare / ".ai" / "plans" / "20260902090000-add-cache.md"
        plan.write_text(PLAN)
        result = self.write("--plan", str(plan), "--prompt-file", str(self.prompt_file))
        self.assertEqual(result.returncode, 0, result.stdout.strip() + result.stderr.strip())
        self.assertEqual(Path(result.stdout.strip()).parent.parent, self.journal / "no-git-project")

    def test_a_loose_plan_never_files_under_plans_or_ai(self):
        loose = self.tmp / "loose" / ".ai" / "plans"
        loose.mkdir(parents=True)
        plan = loose / "20260902090000-loose.md"
        plan.write_text(PLAN)
        result = self.write("--plan", str(plan), "--prompt-file", str(self.prompt_file), cwd=self.tmp)
        self.assertEqual(result.returncode, 0, result.stdout.strip() + result.stderr.strip())
        self.assertEqual(Path(result.stdout.strip()).parent.parent.name, "loose")

    def test_cwd_names_the_project_when_the_plan_is_outside_it(self):
        home_plans = self.home / ".ai" / "plans"
        home_plans.mkdir(parents=True)
        plan = home_plans / "elegant-hopping-book.md"
        plan.write_text(PLAN)
        unsorted = self.write("--plan", str(plan), "--prompt-file", str(self.prompt_file))
        self.assertEqual(Path(unsorted.stdout.strip()).parent.parent.name, "unsorted")
        from_cwd = self.write("--plan", str(plan), "--prompt-file", str(self.prompt_file), cwd=self.repo)
        self.assertEqual(Path(from_cwd.stdout.strip()).parent.parent, self.journal / "my-project")

    def test_the_recorded_project_wins_when_cwd_is_not_a_project_and_filing_rotates_the_anchor(self):
        home_plans = self.home / ".ai" / "plans"
        home_plans.mkdir(parents=True)
        plan = home_plans / "elegant-hopping-book.md"
        plan.write_text(PLAN)
        anchor = self.state / "abc123.prompt"
        anchor.write_text(PROMPT)
        anchor.with_suffix(".project").write_text(str(self.repo))

        result = self.write("--plan", str(plan), "--prompt-file", str(anchor))
        self.assertEqual(result.returncode, 0, result.stdout.strip() + result.stderr.strip())
        self.assertEqual(Path(result.stdout.strip()).parent.parent, self.journal / "my-project")
        self.assertFalse(anchor.exists())
        self.assertFalse(anchor.with_suffix(".project").exists())
        self.assertTrue((self.state / "abc123.prompt.used").exists())
        self.assertTrue((self.state / "abc123.project.used").exists())

    def test_hoko_json_supplies_the_journal_path_and_the_environment_beats_it(self):
        config_home = self.tmp / "config-home"
        (config_home / ".config" / "opencode").mkdir(parents=True)
        configured = self.tmp / "ConfigJournal"
        (config_home / ".config" / "opencode" / "hoko.json").write_text(
            json.dumps({"journalPath": str(configured)}))
        from_config = self.write("--plan", str(self.plan), "--prompt-file", str(self.prompt_file),
                                 home=config_home, journal_root=None)
        self.assertEqual(from_config.returncode, 0, from_config.stderr.strip())
        self.assertEqual(Path(from_config.stdout.strip()).parent.parent, configured / "my-project")
        from_env = self.write("--plan", str(self.plan), "--prompt-file", str(self.prompt_file),
                              home=config_home)
        self.assertEqual(Path(from_env.stdout.strip()).parent.parent, self.journal / "my-project")

    def test_an_unconfigured_journal_root_is_refused(self):
        bare_home = self.tmp / "bare-home"
        result = self.write("--plan", str(self.plan), "--prompt-file", str(self.prompt_file),
                            home=bare_home, journal_root=None)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("HOKO_JOURNAL_PATH is not set", result.stderr)
        self.assertFalse(any(bare_home.rglob("*.md")))


class TestPromptOnlyWrite(JournalTestCase):
    def test_a_stamp_and_slug_file_the_prompt_alone_under_the_tasks_folder_name(self):
        result = self.write("--stamp", "20261021-1530", "--slug", "fix-login-redirect",
                            "--project", "my-project", "--prompt-file", "-", stdin=PROMPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        folder = self.journal / "my-project" / "20261021-1530-fix-login-redirect"
        self.assertIn(PROMPT, (folder / "prompt.md").read_text())
        self.assertFalse((folder / "plan-01.md").exists())
        self.assertEqual(Path(result.stdout.strip()), folder / "plan-01.md")

    def test_a_folder_that_exists_already_gets_a_numbered_sibling(self):
        args = ("--stamp", "20261021-1530", "--slug", "same", "--project", "p", "--prompt-file", "-")
        first = self.write(*args, stdin=PROMPT)
        second = self.write(*args, stdin=PROMPT)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertNotEqual(Path(first.stdout.strip()).parent, Path(second.stdout.strip()).parent)

    def test_a_stamp_with_a_plan_is_refused(self):
        result = self.write("--stamp", "20261021-1530", "--slug", "x", "--plan", str(self.plan),
                            "--prompt-file", str(self.prompt_file))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("drop --plan", result.stderr)

    def test_a_stamp_that_is_not_a_timestamp_is_refused(self):
        result = self.write("--stamp", "yesterday", "--slug", "x", "--prompt-file", "-", stdin=PROMPT)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--stamp must look like", result.stderr)

    def test_a_stamp_without_a_slug_is_refused(self):
        result = self.write("--stamp", "20261021-1530", "--prompt-file", "-", stdin=PROMPT)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--slug", result.stderr)

    def test_neither_a_plan_nor_a_stamp_is_refused(self):
        result = self.write("--prompt-file", "-", stdin=PROMPT)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--plan", result.stderr)


class TestReport(JournalTestCase):
    def setUp(self):
        super().setUp()
        self.entry = self.filed()
        self.report_file = self.tmp / "final.md"
        self.report_file.write_text(REPORT)

    def journaled(self, name="journaled.md", text=None):
        plan = self.tmp / name
        plan.write_text(text or f"Journal: {self.entry}\n\n{PLAN}")
        return plan

    def report(self, plan, *args):
        return self.run_script("report", "--plan", str(plan), "--report-file", str(self.report_file), *args)

    def test_report_writes_round_01_next_to_the_plan(self):
        result = self.report(self.journaled())
        self.assertEqual(result.returncode, 0, result.stderr.strip())
        self.assertEqual(Path(result.stdout.strip()), self.entry.with_name("report-01.md"))
        self.assertEqual(self.entry.with_name("report-01.md").read_text(), REPORT.strip() + "\n")

    def test_report_reads_the_journal_line_of_the_header_not_a_fenced_one(self):
        plan = self.journaled("quoting-plan.md", f"# Plan\n{FENCED_LINES}Journal: {self.entry}\n\n{PLAN}")
        result = self.report(plan)
        self.assertEqual(result.returncode, 0, result.stderr.strip())
        self.assertEqual(Path(result.stdout.strip()), self.entry.with_name("report-01.md"))

    def test_a_plan_whose_only_journal_line_is_fenced_is_refused(self):
        plan = self.journaled("fenced-only.md", f"# Plan\n\n## Decisions\n\n{FENCED_LINES}\n{PLAN}")
        result = self.report(plan)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("has no Journal: line", result.stderr)

    def test_a_round_02_plan_writes_report_02(self):
        round2 = self.entry.with_name("plan-02.md")
        round2.write_text(PLAN)
        result = self.report(self.journaled("journaled-round2.md", f"Journal: {round2}\n\n{PLAN}"))
        self.assertEqual(result.returncode, 0, result.stderr.strip())
        self.assertEqual(Path(result.stdout.strip()), round2.with_name("report-02.md"))

    def test_a_second_report_of_the_same_round_overwrites_the_first(self):
        plan = self.journaled()
        again = self.run_script("report", "--plan", str(plan), "--report-file", "-",
                                stdin="a second pass over the same plan")
        self.assertEqual(again.returncode, 0, again.stderr.strip())
        self.assertEqual(self.entry.with_name("report-01.md").read_text().strip(),
                         "a second pass over the same plan")

    def test_an_empty_report_and_a_missing_plan_are_refused(self):
        empty = self.tmp / "empty.md"
        empty.write_text("\n  \n")
        self.assertNotEqual(self.report(self.journaled(), "--report-file", str(empty)).returncode, 0)
        self.assertNotEqual(self.report(self.tmp / "nope.md").returncode, 0)

    def test_a_plan_without_a_journal_line_is_refused(self):
        bare = self.tmp / "bare-plan.md"
        bare.write_text(PLAN)
        result = self.report(bare)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(str(bare), result.stderr)


class TestRegister(JournalTestCase):
    def register(self, *args):
        return self.run_script("register", *args)

    def test_register_appends_the_session_row_and_stamps_the_time(self):
        entry = self.filed().parent
        result = self.register("--entry", str(entry), "--session", "sess-1",
                               "--round", "1", "--role", "plan")
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = json.loads((entry / "sessions.json").read_text())
        self.assertEqual({k: v for k, v in rows[0].items() if k not in ("since", "transcript_path")},
                         {"session_id": "sess-1", "round": 1, "role": "plan"})
        self.assertRegex(rows[0]["since"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}\+00:00$")
        age = datetime.now(timezone.utc) - datetime.fromisoformat(rows[0]["since"])
        self.assertLess(abs(age.total_seconds()), 60)

    def test_a_repeated_registration_adds_no_duplicate_and_another_role_gets_a_row(self):
        entry = self.filed().parent
        for _ in range(2):
            self.register("--entry", str(entry), "--session", "sess-1", "--round", "1", "--role", "plan")
        self.register("--entry", str(entry), "--session", "sess-1", "--round", "1", "--role", "execute")
        rows = json.loads((entry / "sessions.json").read_text())
        self.assertEqual([row["role"] for row in rows], ["plan", "execute"])

    def test_since_and_the_transcript_are_recorded_verbatim(self):
        entry = self.filed().parent
        self.register("--entry", str(entry), "--session", "sess-3", "--round", "2", "--role", "plan",
                      "--since", "2026-10-06T10:00:00.000+00:00", "--transcript", "/t/sess-3.jsonl")
        row = json.loads((entry / "sessions.json").read_text())[0]
        self.assertEqual((row["since"], row["transcript_path"]),
                         ("2026-10-06T10:00:00.000+00:00", "/t/sess-3.jsonl"))
        self.assertFalse((entry / "sessions.json.tmp").exists())

    def test_register_refuses_an_entry_that_does_not_exist(self):
        self.assertNotEqual(self.register("--entry", str(self.tmp / "nope"), "--session", "s",
                                          "--round", "1", "--role", "plan").returncode, 0)

    def test_register_writes_into_the_entrys_analytics_folder_and_links_it(self):
        entry = self.filed().parent
        home_config = self.home / ".config" / "opencode"
        home_config.mkdir(parents=True)
        analytics_root = self.tmp / "analytics"
        (home_config / "hoko.json").write_text(json.dumps({
            "journalPath": str(self.journal), "analyticsPath": str(analytics_root)}))
        result = self.run_script("register", "--entry", str(entry), "--session", "sess-a",
                                 "--round", "1", "--role", "plan", journal_root=None)
        self.assertEqual(result.returncode, 0, result.stderr)
        folder = analytics_root / "my-project" / entry.name
        rows = json.loads((folder / "sessions.json").read_text())
        self.assertEqual([row["session_id"] for row in rows], ["sess-a"])
        self.assertFalse((entry / "sessions.json").exists())
        link = json.loads((folder / "entry.json").read_text())
        self.assertEqual((link["journal_entry"], link["session_ids"]), (str(entry), ["sess-a"]))


class TestRecord(JournalTestCase):
    def record(self, *args):
        return self.run_script("record", "--root", str(self.repo), *args)

    def registry(self):
        files = list(self.state.glob("sessions-*.json"))
        self.assertEqual(len(files), 1, files)
        return json.loads(files[0].read_text())

    def test_a_repeated_record_keeps_one_row_and_prints_the_registry_file(self):
        first = self.record("--session", "S1")
        second = self.record("--session", "S1")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(Path(second.stdout.strip()), Path(first.stdout.strip()))
        self.assertEqual([(row["session_id"], row["round"], row["role"]) for row in self.registry()],
                         [("S1", 1, "execute")])

    def test_a_record_without_a_session_exits_non_zero_and_writes_no_file(self):
        result = self.record()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--session", result.stderr)
        self.assertEqual(list(self.state.glob("sessions-*.json")), [])


class TestRecordedSessions(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.root = Path(self.tmpdir.name).resolve() / "project"
        self.root.mkdir()
        patch = mock.patch.object(journal, "STATE_DIR", Path(self.tmpdir.name) / "state")
        patch.start()
        self.addCleanup(patch.stop)

    def test_a_session_is_recorded_once_and_read_back(self):
        journal.record_session(self.root, "S1", "/t/S1.jsonl")
        journal.record_session(self.root, "S1", "/t/S1.jsonl")
        rows = journal.recorded_sessions(self.root)
        self.assertEqual([(row["session_id"], row["role"], row["round"]) for row in rows],
                         [("S1", "execute", 1)])
        self.assertRegex(rows[0]["since"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}\+00:00$")

    def test_after_keeps_only_sessions_whose_transcript_was_written_since(self):
        transcript = Path(self.tmpdir.name) / "S1.jsonl"
        transcript.write_text("{}\n")
        journal.record_session(self.root, "S1", str(transcript))
        later = datetime.fromtimestamp(transcript.stat().st_mtime, timezone.utc) + timedelta(minutes=1)
        earlier = later - timedelta(days=1)
        self.assertEqual(len(journal.recorded_sessions(self.root, after=earlier)), 1)
        self.assertEqual(journal.recorded_sessions(self.root, after=later), [])

    def test_the_registry_keeps_the_newest_hundred_rows(self):
        for index in range(101):
            journal.record_session(self.root, f"S{index}")
        ids = [row["session_id"] for row in journal.recorded_sessions(self.root)]
        self.assertEqual(len(ids), 100)
        self.assertEqual((ids[0], ids[-1]), ("S1", "S100"))

    def test_a_transcriptless_row_counts_from_its_own_since(self):
        journal.record_session(self.root, "S1")
        since = datetime.fromisoformat(journal.recorded_sessions(self.root)[0]["since"])
        self.assertEqual(len(journal.recorded_sessions(self.root, after=since)), 1)
        self.assertEqual(journal.recorded_sessions(self.root, after=since + timedelta(milliseconds=1)), [])

    def test_a_naive_since_is_read_as_utc_and_a_row_without_one_is_dropped(self):
        journal.recorded_sessions_file(self.root).write_text(json.dumps([
            {"session_id": "S1", "transcript_path": "", "since": "2026-10-21T10:00:00.000"},
            {"session_id": "S0", "transcript_path": ""},
        ]))
        rows = journal.recorded_sessions(self.root, after=datetime(2026, 10, 21, 10, 0, tzinfo=timezone.utc))
        self.assertEqual([row["session_id"] for row in rows], ["S1"])


class TestRegisterSessionInProcess(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.tmp = Path(self.tmpdir.name)
        self.entry = self.tmp / "my-project" / "20260101-0000-case"
        self.entry.mkdir(parents=True)
        self.analytics = self.tmp / "analytics"
        self.journal = self.tmp / "journal"
        config = self.tmp / "config"
        config.mkdir()
        (config / "hoko.json").write_text(json.dumps(
            {"analyticsPath": str(self.analytics), "journalPath": str(self.journal)}))
        # The developer's own HOKO_* must not decide a case that runs in this process.
        environment = mock.patch.dict(os.environ)
        environment.start()
        self.addCleanup(environment.stop)
        for name in list(os.environ):
            if name.startswith("HOKO_"):
                os.environ.pop(name)
        patch = mock.patch.object(settings, "CONFIG_DIRS", (config,))
        patch.start()
        self.addCleanup(patch.stop)

    def rows(self):
        return json.loads((analytics.folder_for(self.entry) / "sessions.json").read_text())

    def test_register_session_with_since_stores_it_verbatim(self):
        journal.register_session(self.entry, "S1", "/t/S1.jsonl", 2, "execute",
                                 since="2026-10-21T10:10:00.000Z")
        self.assertEqual(self.rows()[0]["since"], "2026-10-21T10:10:00.000Z")

    def test_register_session_without_since_stamps_the_current_time(self):
        journal.register_session(self.entry, "S1", "/t/S1.jsonl", 1, "execute")
        age = datetime.now(timezone.utc) - datetime.fromisoformat(self.rows()[0]["since"])
        self.assertLess(abs(age.total_seconds()), 60)


if __name__ == "__main__":
    unittest.main(verbosity=2)

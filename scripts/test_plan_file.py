#!/usr/bin/env python3
"""Tests for plan-file.py.

Copies the plugin's scripts to a temp dir and points HOKO_JOURNAL_PATH and HOME at
throwaway roots, so the real journal and config are never touched.
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ("plan-file.py", "journal.py", "settings.py")


def plugin_copy(tmp):
    plugin = tmp / "plugin"
    (plugin / "scripts").mkdir(parents=True)
    for name in SCRIPTS:
        (plugin / "scripts" / name).write_text(
            (PLUGIN_ROOT / "scripts" / name).read_text(encoding="utf-8"), encoding="utf-8")
    return plugin


def plan_text(title="Ship a dry-run flag"):
    return f"# {title}\n\n## Goal\n{title}.\n\n## Steps\n### 1. Do it\n- Files: cli.py\n"


class TestPlanFile(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.tmp = Path(self.tmpdir.name).resolve()
        self.plugin = plugin_copy(self.tmp)
        self.script = self.plugin / "scripts" / "plan-file.py"
        self.home = self.tmp / "home"
        self.state = self.tmp / "state"
        self.journal = self.tmp / "Journal"
        self.home.mkdir()
        self.state.mkdir()

    def repo(self, name="case-repo"):
        repo = self.tmp / name
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        return repo

    def anchor(self, session_id, text):
        digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]
        path = self.state / f"{digest}.prompt"
        path.write_text(text, encoding="utf-8")
        return path

    def run_file(self, plan, session=None, project=None, repo=None, journal="default"):
        env = dict(os.environ)
        for name in list(env):
            if name.startswith("HOKO_"):
                del env[name]
        env["HOME"] = str(self.home)
        env["HOKO_STATE_DIR"] = str(self.state)
        if journal == "default":
            env["HOKO_JOURNAL_PATH"] = str(self.journal)
        elif journal is not None:
            env["HOKO_JOURNAL_PATH"] = str(journal)
        args = [sys.executable, str(self.script), "file", "--plan", str(plan)]
        if session:
            args += ["--session", session]
        if project:
            args += ["--project", project]
        return subprocess.run(args, capture_output=True, text=True, env=env,
                              cwd=str(repo) if repo else str(self.home))

    def test_file_records_the_project_and_journal_lines(self):
        repo = self.repo()
        plan = self.tmp / "auto-generated-slug.md"
        plan.write_text(plan_text())

        result = self.run_file(plan, session="s1", repo=repo)
        self.assertEqual(result.returncode, 0, result.stderr.strip())
        entry = Path(result.stdout.strip())
        self.assertEqual(entry.name, "plan-01.md", entry.name)
        self.assertEqual(entry.parent.parent, self.journal / "case-repo")

        self.assertTrue((entry.parent / "prompt.md").is_file())
        self.assertIn("_Prompt not captured._", (entry.parent / "prompt.md").read_text())
        self.assertIn("Project: case-repo", entry.read_text())

        text = plan.read_text()
        self.assertIn("Project: case-repo", text)
        self.assertIn(f"Journal: {entry}", text)
        self.assertLess(text.index("Project: case-repo"), text.index(f"Journal: {entry}"))

    def test_the_session_prompt_anchor_fills_prompt_md(self):
        repo = self.repo()
        plan = self.tmp / "plan.md"
        plan.write_text(plan_text("Anchor the prompt"))
        anchor = self.anchor("s1", "add a --dry-run flag")

        result = self.run_file(plan, session="s1", repo=repo)
        self.assertEqual(result.returncode, 0, result.stderr.strip())
        entry = Path(result.stdout.strip())
        self.assertIn("add a --dry-run flag", (entry.parent / "prompt.md").read_text())
        self.assertFalse(anchor.exists(), "the write should retire the session anchor")
        self.assertTrue(anchor.with_name(anchor.name + ".used").exists())

    def test_file_registers_the_planning_session_as_round_one_plan(self):
        repo = self.repo()
        plan = self.tmp / "plan.md"
        plan.write_text(plan_text("Register the session"))

        result = self.run_file(plan, session="s1", repo=repo)
        self.assertEqual(result.returncode, 0, result.stderr.strip())
        entry = Path(result.stdout.strip())

        rows = json.loads((entry.parent / "sessions.json").read_text())
        self.assertEqual(len(rows), 1, str(rows))
        self.assertIn("since", rows[0])
        self.assertEqual({k: v for k, v in rows[0].items() if k != "since"},
                         {"session_id": "s1", "round": 1, "role": "plan"})

    def test_a_plan_whose_journal_line_names_an_existing_file_is_not_refiled(self):
        repo = self.repo()
        plan = self.tmp / "plan.md"
        plan.write_text(plan_text("File once"))

        first = self.run_file(plan, session="s1", repo=repo)
        self.assertEqual(first.returncode, 0, first.stderr.strip())
        filed = Path(first.stdout.strip())

        again = self.run_file(plan, session="s1", repo=repo)
        self.assertEqual(again.returncode, 0, again.stderr.strip())
        self.assertEqual(Path(again.stdout.strip()), filed)

        rounds = list((self.journal / "case-repo").glob("*"))
        self.assertEqual(len(rounds), 1, str(rounds))
        rows = json.loads((filed.parent / "sessions.json").read_text())
        self.assertEqual(len(rows), 1, str(rows))

    def test_a_plans_own_project_line_resolves_the_entry(self):
        repo = self.repo()
        plan = self.tmp / "plan.md"
        plan.write_text("Project: explicit-project\n" + plan_text("Own project"))

        result = self.run_file(plan, session="s1", repo=repo)
        self.assertEqual(result.returncode, 0, result.stderr.strip())
        entry = Path(result.stdout.strip())
        self.assertEqual(entry.parent.parent, self.journal / "explicit-project")

    def test_with_journaling_off_only_the_project_line_is_added(self):
        repo = self.repo()
        plan = self.tmp / "plan.md"
        plan.write_text(plan_text("Journaling off"))

        result = self.run_file(plan, session="s1", repo=repo, journal=None)
        self.assertEqual(result.returncode, 0, result.stderr.strip())
        self.assertEqual(Path(result.stdout.strip()), plan.resolve())

        text = plan.read_text()
        self.assertIn("Project: case-repo", text)
        self.assertNotIn("Journal:", text)
        self.assertFalse(self.journal.exists(), str(sorted(self.journal.rglob("*"))))


if __name__ == "__main__":
    unittest.main(verbosity=2)

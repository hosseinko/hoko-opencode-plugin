#!/usr/bin/env python3
"""Tests for plan-file.py.

Copies the plugin's scripts to a temp dir and points the plugin's own `hoko.json` at
throwaway journal and analytics roots, so the real journal is never touched.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_plan_format import FENCED_LINES, plan_with_fenced_header_lines

PLUGIN_ROOT = Path(__file__).resolve().parent.parent


def plan_text(title="Ship a dry-run flag"):
    return f"# {title}\n\n## Goal\n{title}.\n\n## Steps\n### 1. Do it\n- Files: cli.py\n"


class TestPlanFile(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.tmp = Path(self.tmpdir.name).resolve()
        self.plugin = self.tmp / "plugin"
        shutil.copytree(PLUGIN_ROOT / "scripts", self.plugin / "scripts",
                        ignore=shutil.ignore_patterns("__pycache__", "test_*.py"))
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

    def configure(self, journal="default", analytics=""):
        config = {"analyticsPath": str(analytics)}
        if journal == "default":
            config["journalPath"] = str(self.journal)
        elif journal is not None:
            config["journalPath"] = str(journal)
        (self.plugin / "hoko.json").write_text(json.dumps(config))
        return config

    def run_file(self, plan, session=None, project=None, repo=None, journal="default",
                 analytics="", since=None):
        self.configure(journal, analytics)
        env = {name: value for name, value in os.environ.items() if not name.startswith("HOKO_")}
        env["HOME"] = str(self.home)
        env["HOKO_STATE_DIR"] = str(self.state)
        args = [sys.executable, str(self.script), "file", "--plan", str(plan)]
        if session:
            args += ["--session", session]
        if project:
            args += ["--project", project]
        if since:
            args += ["--since", since]
        return subprocess.run(args, capture_output=True, text=True, env=env,
                              cwd=str(repo) if repo else str(self.home))

    def test_approval_stamps_the_project_and_journal_lines(self):
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

    def test_approval_renames_the_plan_into_the_repository_plans_directory(self):
        repo = self.repo()
        plan = self.tmp / "auto-generated-slug.md"
        plan.write_text(plan_text())

        result = self.run_file(plan, session="s1", repo=repo)
        self.assertEqual(result.returncode, 0, result.stderr.strip())
        copies = list((repo / ".ai" / "plans").glob("*.md"))
        self.assertEqual(len(copies), 1, str(copies))
        self.assertRegex(copies[0].name, r"^\d{8}-\d{4}-ship-a-dry-run-flag\.md$")
        self.assertIn("/.ai/", (repo / ".gitignore").read_text().splitlines())

    def test_a_plan_already_in_the_plans_directory_keeps_its_name(self):
        repo = self.repo()
        plans = repo / ".ai" / "plans"
        plans.mkdir(parents=True)
        plan = plans / "20260101-0000-existing.md"
        plan.write_text(plan_text("Keep the name"))

        result = self.run_file(plan, session="s1", repo=repo)
        self.assertEqual(result.returncode, 0, result.stderr.strip())
        self.assertEqual(sorted(p.name for p in plans.glob("*.md")), ["20260101-0000-existing.md"])
        self.assertIn("Journal:", plan.read_text())

    def test_approval_generates_the_progress_checklist(self):
        repo = self.repo()
        plan = self.tmp / "auto-generated-slug.md"
        plan.write_text(plan_text())

        result = self.run_file(plan, session="s1", repo=repo)
        self.assertEqual(result.returncode, 0, result.stderr.strip())
        repo_copy = next((repo / ".ai" / "plans").glob("*.md"))
        self.assertIn("## Progress", repo_copy.read_text())
        self.assertIn("- [ ] 1. Do it", repo_copy.read_text())

    def test_approval_registers_the_planning_session_in_the_entrys_analytics_folder(self):
        repo = self.repo()
        plan = self.tmp / "auto-generated-slug.md"
        plan.write_text(plan_text())
        analytics = self.tmp / "analytics"

        result = self.run_file(plan, session="s1", repo=repo, analytics=analytics)
        self.assertEqual(result.returncode, 0, result.stderr.strip())
        entry = Path(result.stdout.strip()).parent
        folder = analytics / "case-repo" / entry.name
        rows = json.loads((folder / "sessions.json").read_text())
        self.assertEqual([(row["session_id"], row["role"], row["round"]) for row in rows],
                         [("s1", "plan", 1)])
        self.assertFalse((entry / "sessions.json").exists())
        link = json.loads((folder / "entry.json").read_text())
        self.assertEqual((link["journal_entry"], link["session_ids"]), (str(entry), ["s1"]))
        self.assertEqual(link["project"], "case-repo")

    def test_the_session_prompt_anchor_fills_prompt_md(self):
        repo = self.repo()
        plan = self.tmp / "plan.md"
        plan.write_text(plan_text("Anchor the prompt"))
        import hashlib
        digest = hashlib.sha256(b"s1").hexdigest()[:16]
        anchor = self.state / f"{digest}.prompt"
        anchor.write_text("add a --dry-run flag")

        result = self.run_file(plan, session="s1", repo=repo)
        self.assertEqual(result.returncode, 0, result.stderr.strip())
        entry = Path(result.stdout.strip())
        self.assertIn("add a --dry-run flag", (entry.parent / "prompt.md").read_text())
        self.assertFalse(anchor.exists(), "the write should retire the session anchor")
        self.assertTrue(anchor.with_name(anchor.name + ".used").exists())

    def test_the_project_anchor_fills_prompt_md_and_survives_filing(self):
        repo = self.repo()
        plan = self.tmp / "plan.md"
        plan.write_text(plan_text("Anchor the cycle"))
        import hashlib
        digest = hashlib.sha256(str(repo).encode("utf-8")).hexdigest()[:16]
        anchor = self.state / f"project-{digest}.prompt"
        anchor.write_text("the project's own first prompt")

        result = self.run_file(plan, session="s1", repo=repo)
        self.assertEqual(result.returncode, 0, result.stderr.strip())
        entry = Path(result.stdout.strip()).parent
        self.assertIn("the project's own first prompt", (entry / "prompt.md").read_text())
        self.assertEqual(anchor.read_text(), "the project's own first prompt")

    def test_the_plan_row_records_the_capture_time_not_the_filing_time(self):
        repo = self.repo()
        plan = self.tmp / "plan.md"
        plan.write_text(plan_text("Capture time"))
        captured = "2020-01-02T03:04:05.006+00:00"

        result = self.run_file(plan, session="s1", repo=repo, since=captured)
        self.assertEqual(result.returncode, 0, result.stderr.strip())
        entry = Path(result.stdout.strip())
        rows = json.loads((entry.parent / "sessions.json").read_text())
        self.assertEqual(rows[0]["since"], captured)

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
        self.assertEqual(len(list((repo / ".ai" / "plans").glob("*.md"))), 1)

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
        self.assertEqual(len(list((repo / ".ai" / "plans").glob("*.md"))), 1)

    def test_a_journal_line_quoted_in_a_fence_does_not_stop_the_header_gaining_its_own(self):
        repo = self.repo()
        plan = self.tmp / "plan.md"
        plan.write_text(plan_with_fenced_header_lines())

        result = self.run_file(plan, session="s1", repo=repo)
        self.assertEqual(result.returncode, 0, result.stderr.strip())
        text = plan.read_text()
        header = text.split("\n## ", 1)[0]
        self.assertRegex(header, r"(?m)^Project: case-repo$")
        self.assertRegex(header, r"(?m)^Journal: .*plan-01\.md$")
        self.assertEqual(text.count(FENCED_LINES), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)

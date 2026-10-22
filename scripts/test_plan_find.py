#!/usr/bin/env python3
"""Tests for plan-find.py — a scratch repo and a scratch home per case."""

import os
import subprocess
import sys
import tempfile
import time
import unittest

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plan-find.py")


class PlanFindTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.root = os.path.join(self.tmpdir.name, "repo")
        self.home = os.path.join(self.tmpdir.name, "home")
        os.makedirs(self.root)
        os.makedirs(self.home)
        self.env = dict(os.environ)
        self.env["TMPDIR"] = self.tmpdir.name
        self.env["HOME"] = self.home

    def write(self, path, text, age=None):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        if age is not None:
            stamp = time.time() - age
            os.utime(path, (stamp, stamp))

    def repo_plan(self, name, text, age=None):
        self.write(os.path.join(self.root, ".opencode", "plans", name), text, age)

    def shared_plan(self, name, text, age=None):
        self.write(os.path.join(self.home, ".opencode", "plan", name), text, age)

    def run_find(self):
        return subprocess.run(
            [sys.executable, SCRIPT, "--root", self.root],
            capture_output=True, text=True, env=self.env,
        )


class TestRepositoryPlanWins(PlanFindTestCase):
    def test_a_repository_plan_is_chosen_over_a_newer_foreign_one(self):
        self.repo_plan("old-repo-plan.md", "# Repo plan\n", age=3600)
        self.shared_plan("new-foreign-plan.md", "# Foreign plan\n", age=0)
        proc = self.run_find()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("old-repo-plan.md", proc.stdout)
        self.assertNotIn("new-foreign-plan.md", proc.stdout)


class TestStatusComplete(PlanFindTestCase):
    def test_a_plan_already_marked_status_complete_is_skipped(self):
        self.repo_plan("done.md", "Status: complete\n\n# Done plan\n", age=10)
        self.repo_plan("open.md", "# Open plan\n", age=3600)
        proc = self.run_find()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("open.md", proc.stdout)
        self.assertNotIn("done.md", proc.stdout)

    def test_bold_status_complete_is_skipped_too(self):
        self.repo_plan("bold-done.md", "**Status:** complete\n\n# Done plan\n", age=10)
        self.repo_plan("open.md", "# Open plan\n", age=3600)
        proc = self.run_find()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("open.md", proc.stdout)
        self.assertNotIn("bold-done.md", proc.stdout)

    def test_status_complete_with_trailing_text_is_skipped_too(self):
        self.repo_plan("noted-done.md", "Status: complete — closed by review\n\n# Done plan\n", age=10)
        self.repo_plan("open.md", "# Open plan\n", age=3600)
        proc = self.run_find()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("open.md", proc.stdout)
        self.assertNotIn("noted-done.md", proc.stdout)


class TestHomeIsNeverARepositoryPlansDir(PlanFindTestCase):
    def test_home_opencode_plan_is_never_treated_as_repo_plans(self):
        # `--root` pointed straight at home: `root/.opencode/plan` is then literally
        # the same directory as the shared `~/.opencode/plan` and must be scored, not
        # auto-picked as though it were this repository's own plans.
        self.shared_plan("home-plan.md", "# Some plan\n\nProject: some-other-project\n")
        proc = subprocess.run(
            [sys.executable, SCRIPT, "--root", self.home],
            capture_output=True, text=True, env=self.env,
        )
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertTrue(proc.stdout.strip().startswith("0 "), proc.stdout)


class TestFallback(PlanFindTestCase):
    def test_a_matching_project_line_scores_one(self):
        # The repo root is named "repo", so its project slug is "repo".
        self.shared_plan(
            "hits-one.md",
            "# Some plan\n\nProject: repo\n\n## Goal\n",
        )
        proc = self.run_find()
        self.assertEqual(proc.returncode, 1)
        self.assertIn("hits-one.md", proc.stdout)
        self.assertTrue(proc.stdout.strip().startswith("1 "))

    def test_an_annotation_after_the_project_name_still_scores_one(self):
        self.shared_plan(
            "annotated.md",
            "# Some plan\n\nProject: repo (branch feature/rewrite-in-go)\n\n## Goal\n",
        )
        proc = self.run_find()
        self.assertEqual(proc.returncode, 1)
        self.assertIn("annotated.md", proc.stdout)
        self.assertTrue(proc.stdout.strip().startswith("1 "))

    def test_a_non_matching_project_line_scores_zero(self):
        self.shared_plan(
            "hits-zero.md",
            "# Some plan\n\nProject: some-other-project\n\n## Goal\n",
        )
        proc = self.run_find()
        self.assertEqual(proc.returncode, 1)
        self.assertTrue(proc.stdout.strip().startswith("0 "))

    def test_no_project_line_at_all_scores_zero(self):
        self.shared_plan("no-project-line.md", "# Some plan\n\n## Goal\n")
        proc = self.run_find()
        self.assertEqual(proc.returncode, 1)
        self.assertTrue(proc.stdout.strip().startswith("0 "))

    def test_every_candidate_scoring_zero_exits_non_zero_without_choosing_one(self):
        self.shared_plan("first.md", "# First\n\nProject: other-one\n", age=0)
        self.shared_plan("second.md", "# Second\n\nProject: other-two\n", age=10)
        proc = self.run_find()
        self.assertEqual(proc.returncode, 1)
        for line in proc.stdout.splitlines():
            self.assertTrue(line.startswith("0 "), line)


if __name__ == "__main__":
    unittest.main()

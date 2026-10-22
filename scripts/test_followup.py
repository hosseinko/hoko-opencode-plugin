#!/usr/bin/env python3
"""Tests for followup.py — the follow-up plan a review's findings render into."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import followup

HERE = Path(__file__).resolve().parent
PLAN_LINT = HERE / "plan-lint.py"

FINDINGS = [
    {"severity": "important", "file": "widget.py", "line": 12,
     "summary": "the cache is never cleared", "scenario": "two runs share a stale cache",
     "fix": "clear the cache when the run starts"},
    {"severity": "blocking", "file": "gadget.py", "line": 3,
     "summary": "the token is logged", "scenario": "a log scraper reads the token",
     "fix": "redact the token before logging"},
]


class FollowupTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.env = {name: value for name, value in os.environ.items()
                    if not name.startswith("HOKO_")}
        self.env["TMPDIR"] = self.tmpdir.name
        self.env["HOME"] = self.tmpdir.name

    def render(self, findings=None, title="Widget (round 2)", subject="widget"):
        return followup.render(followup.ordered(FINDINGS if findings is None else findings),
                               title, subject)

    def write_findings(self, findings=FINDINGS):
        path = os.path.join(self.tmpdir.name, "findings.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(findings, f)
        return path

    def lint_structurally(self, plan_path):
        return subprocess.run(
            [sys.executable, str(PLAN_LINT), "--plan", plan_path, "--structural"],
            capture_output=True, text=True, env=self.env,
        )


class TestRender(FollowupTestCase):
    def test_one_requirement_and_one_step_are_rendered_per_finding(self):
        text = self.render()
        self.assertEqual(text.count("- **R"), 2)
        self.assertEqual(text.count("### "), 2)
        self.assertIn("- [ ] 1. the token is logged", text)
        self.assertIn("- [ ] 2. the cache is never cleared", text)

    def test_each_step_names_its_finding_scenario_fix_and_requirement(self):
        text = self.render()
        self.assertIn("- Finding: blocking at `gadget.py`:3 — the token is logged", text)
        self.assertIn("- Scenario: a log scraper reads the token", text)
        self.assertIn("- Fix: redact the token before logging", text)
        self.assertIn("- Satisfies: R1", text)

    def test_the_goal_names_the_subject_the_review_covered(self):
        self.assertIn("strict review found over widget", self.render())

    def test_a_finding_with_no_line_is_located_by_its_file_alone(self):
        text = self.render([{"severity": "blocking", "file": "gadget.py", "line": None,
                             "summary": "the token is logged"}])
        self.assertIn("at `gadget.py` —", text)

    def test_a_finding_missing_every_field_still_renders_with_placeholders(self):
        text = self.render([{}])
        self.assertIn("- Finding: unrated at `unknown file`:unknown — no summary given", text)
        self.assertIn("- Scenario: not given", text)
        self.assertIn("- Fix: no fix given", text)

    def test_rendering_needs_a_finding(self):
        with self.assertRaises(followup.FollowupError):
            self.render([])

    def test_rendering_needs_a_title(self):
        with self.assertRaises(followup.FollowupError):
            self.render(title="  ")

    def test_a_rendered_plan_passes_the_structural_lint(self):
        path = os.path.join(self.tmpdir.name, "widget--r02.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.render())
        proc = self.lint_structurally(path)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


class TestOrdering(FollowupTestCase):
    def test_a_blocking_finding_renders_before_an_important_one(self):
        text = self.render(followup.ordered(FINDINGS))
        self.assertLess(text.index("gadget.py"), text.index("widget.py"))

    def test_a_finding_of_unknown_severity_sorts_last(self):
        ordered = followup.ordered(FINDINGS + [{"severity": "minor", "file": "note.py"}])
        self.assertEqual([f.get("file") for f in ordered], ["gadget.py", "widget.py", "note.py"])


class TestNaming(FollowupTestCase):
    def test_the_round_of_a_plan_stem_is_its_suffix_or_one(self):
        self.assertEqual(followup.parent_round("widget"), 1)
        self.assertEqual(followup.parent_round("widget--r03"), 3)
        self.assertEqual(followup.parent_round("plan-02"), 2)

    def test_a_round_one_stem_drops_the_round_suffix(self):
        self.assertEqual(followup.round_one_stem("widget--r03"), "widget")
        self.assertEqual(followup.round_one_stem("widget"), "widget")

    def test_the_title_carries_the_round_number(self):
        self.assertEqual(followup.round_title("Widget", 2), "Widget (round 2)")

    def test_the_parents_title_drops_a_previous_follow_up_prefix_and_round(self):
        text = "# Review follow-up: Widget (round 2)\n\n## Goal\n\nFix it.\n"
        self.assertEqual(followup.base_title(text, "widget--r02"), "Widget")

    def test_the_parents_title_falls_back_to_its_stem(self):
        self.assertEqual(followup.base_title("", "widget--r02"), "widget")

    def test_pick_round_skips_a_round_the_plans_directory_already_holds(self):
        plans_dir = Path(self.tmpdir.name)
        (plans_dir / "widget--r02.md").write_text("# x\n", encoding="utf-8")
        (plans_dir / "widget--r03.md").write_text("# x\n", encoding="utf-8")
        self.assertEqual(followup.pick_round(plans_dir, "widget", 2), 4)

    def test_pick_round_skips_a_round_the_journal_entry_already_holds(self):
        plans_dir = Path(self.tmpdir.name) / "plans"
        entry = Path(self.tmpdir.name) / "entry"
        plans_dir.mkdir()
        entry.mkdir()
        (entry / "plan-02.md").write_text("# x\n", encoding="utf-8")
        self.assertEqual(followup.pick_round(plans_dir, "widget", 2, entry), 3)


class TestWritePlan(FollowupTestCase):
    def test_the_follow_up_is_written_beside_its_own_progress_json_for_that_round(self):
        destination = Path(self.tmpdir.name) / "widget--r02.md"
        followup.write_plan(destination, self.render(), 2)

        self.assertTrue(destination.is_file())
        progress = json.loads(destination.with_name("widget--r02.progress.json")
                              .read_text(encoding="utf-8"))
        self.assertEqual(progress["rounds"][0]["round"], 2)
        self.assertEqual(progress["rounds"][0]["plan"], "widget--r02.md")
        self.assertEqual(progress["rounds"][0]["source"], "review")
        self.assertEqual([step["status"] for step in progress["rounds"][0]["steps"]],
                         ["pending", "pending"])


class TestFindingsFile(FollowupTestCase):
    def test_a_findings_file_of_the_expected_shape_is_read_back_unchanged(self):
        path = self.write_findings()
        with open(path, encoding="utf-8") as f:
            self.assertEqual(json.load(f), FINDINGS)


if __name__ == "__main__":
    unittest.main()

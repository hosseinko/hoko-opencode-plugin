#!/usr/bin/env python3
"""Tests for review-findings.py — a scratch repo, a findings file, and plan-lint.py as
the judge of whether the rendered plan is actually usable."""

import json
import os
import subprocess
import sys
import tempfile
import unittest

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "review-findings.py")
PLAN_LINT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plan-lint.py")

TWO_FINDINGS = [
    {
        "severity": "important",
        "file": "src/widget.py",
        "line": 12,
        "summary": "SQL query built by string formatting instead of binding",
        "fix": "Bind the parameter instead of formatting it into the query string",
    },
    {
        "severity": "blocking",
        "file": "src/gadget.py",
        "line": 30,
        "summary": "Missing null check crashes on an absent customer",
        "fix": "Guard the null case before dereferencing the customer",
    },
]

MIXED_SEVERITY_FINDINGS = [
    {
        "severity": "important",
        "file": "src/widget.py",
        "line": 12,
        "summary": "SQL query built by string formatting instead of binding",
        "scenario": "A username containing a quote reaches the query unescaped",
        "fix": "Bind the parameter instead of formatting it into the query string",
    },
    {
        "severity": "nit",
        "file": "src/widget.py",
        "line": 20,
        "summary": "Variable name could be clearer",
        "fix": "Rename it",
    },
    {
        "severity": "suggestion",
        "file": "src/widget.py",
        "line": 21,
        "summary": "Consider extracting a helper",
        "fix": "Extract a helper",
    },
    {
        "severity": "learning",
        "file": "src/widget.py",
        "line": 22,
        "summary": "This pattern is used elsewhere too",
        "fix": "n/a",
    },
    {
        "severity": "praise",
        "file": "src/widget.py",
        "line": 23,
        "summary": "Nice use of the existing helper",
        "fix": "n/a",
    },
    {
        "severity": "blocking",
        "file": "src/gadget.py",
        "line": 30,
        "summary": "Missing null check crashes on an absent customer",
        "fix": "Guard the null case before dereferencing the customer",
    },
]

ALL_NIT_FINDINGS = [
    {
        "severity": "nit",
        "file": "src/widget.py",
        "line": 20,
        "summary": "Variable name could be clearer",
        "fix": "Rename it",
    },
    {
        "severity": "suggestion",
        "file": "src/widget.py",
        "line": 21,
        "summary": "Consider extracting a helper",
        "fix": "Extract a helper",
    },
]


def read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def first_line(path):
    return read_text(path).splitlines()[0]


class ReviewFindingsTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.root = os.path.join(self.tmpdir.name, "repo")
        self.home = os.path.join(self.tmpdir.name, "home")
        os.makedirs(os.path.join(self.root, "src"))
        os.makedirs(self.home)
        for name in ("widget.py", "gadget.py"):
            with open(os.path.join(self.root, "src", name), "w", encoding="utf-8") as f:
                f.write("# placeholder\n")
        self.env = dict(os.environ)
        self.env["TMPDIR"] = self.tmpdir.name
        self.env["HOME"] = self.home

    def write_findings(self, name, content):
        path = os.path.join(self.tmpdir.name, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def run_render(self, findings_path):
        return subprocess.run(
            [sys.executable, SCRIPT, "--from", findings_path, "--root", self.root],
            capture_output=True, text=True, env=self.env,
        )

    def run_lint(self, plan_path):
        return subprocess.run(
            [sys.executable, PLAN_LINT, "--plan", plan_path, "--root", self.root],
            capture_output=True, text=True, env=self.env,
        )

    def plans_dir(self):
        return os.path.realpath(os.path.join(self.root, ".ai", "plans"))


class TestWritesProgressJsonBesideTheFollowUp(ReviewFindingsTestCase):
    def progress_of(self, plan_path):
        with open(os.path.splitext(plan_path)[0] + ".progress.json", encoding="utf-8") as f:
            return json.load(f)

    def test_a_follow_up_gets_a_progress_json_with_one_pending_entry_per_step(self):
        findings_path = self.write_findings("findings.json", json.dumps(TWO_FINDINGS))
        proc = self.run_render(findings_path)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

        document = self.progress_of(proc.stdout.strip())
        steps = document["rounds"][0]["steps"]
        self.assertEqual([s["n"] for s in steps], [1, 2])
        self.assertEqual({s["status"] for s in steps}, {"pending"})
        self.assertEqual(document["rounds"][0]["source"], "review")

    def test_a_follow_up_of_a_parent_records_its_round(self):
        plans = os.path.join(self.root, ".ai", "plans")
        os.makedirs(plans)
        parent = os.path.join(plans, "20260101000000-widget.md")
        with open(parent, "w", encoding="utf-8") as f:
            f.write("# Widget plan\n\n## Goal\n\nBuild the widget.\n")
        findings_path = self.write_findings("findings.json", json.dumps(TWO_FINDINGS))
        proc = subprocess.run(
            [sys.executable, SCRIPT, "--from", findings_path, "--root", self.root, "--plan", parent],
            capture_output=True, text=True, env=self.env,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

        document = self.progress_of(proc.stdout.strip())
        self.assertEqual(document["rounds"][0]["round"], 2)
        self.assertEqual(document["rounds"][0]["plan"], "20260101000000-widget--r02.md")
        self.assertEqual(document["title"], "Widget plan (round 2)")


class TestRendersAPlanPlanLintAccepts(ReviewFindingsTestCase):
    def test_a_two_finding_plan_passes_plan_lint(self):
        findings_path = self.write_findings("findings.json", json.dumps(TWO_FINDINGS))
        proc = self.run_render(findings_path)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        plan_path = proc.stdout.strip()
        self.assertTrue(os.path.isfile(plan_path), plan_path)
        self.assertTrue(os.path.realpath(plan_path).startswith(self.plans_dir()))

        lint_proc = self.run_lint(plan_path)
        self.assertEqual(lint_proc.returncode, 0, lint_proc.stdout + lint_proc.stderr)

    def test_the_rendered_plan_has_no_files_line_and_names_the_file_in_finding(self):
        findings_path = self.write_findings("findings.json", json.dumps(TWO_FINDINGS))
        proc = self.run_render(findings_path)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        plan_path = proc.stdout.strip()
        with open(plan_path, encoding="utf-8") as f:
            text = f.read()
        self.assertNotIn("- Files:", text)
        self.assertIn("- Finding: important at `src/widget.py`:12 — "
                       "SQL query built by string formatting instead of binding", text)

    def test_findings_are_ordered_most_severe_first(self):
        findings_path = self.write_findings("findings.json", json.dumps(TWO_FINDINGS))
        proc = self.run_render(findings_path)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        plan_path = proc.stdout.strip()
        with open(plan_path, encoding="utf-8") as f:
            text = f.read()
        blocking_at = text.index("gadget.py")
        important_at = text.index("widget.py")
        self.assertLess(blocking_at, important_at,
                         "the blocking finding should render before the important one")


class TestChainsIntoJournal(ReviewFindingsTestCase):
    PARENT_PLAN = (
        "# Widget plan\n\nProject: myproj\nJournal: {journal}\n\n## Goal\n\n"
        "Build the widget.\n\n## Decisions\n\n- Store widgets in SQLite, not in memory.\n"
        "\n## Test conventions\n\nRun `pytest` from the repo root.\n"
    )

    def setUp(self):
        super().setUp()
        self.journal_folder = os.path.join(self.tmpdir.name, "journal", "myproj", "20260101-0000-widget")
        os.makedirs(self.journal_folder)
        self.round_one = os.path.join(self.journal_folder, "plan-01.md")
        with open(self.round_one, "w", encoding="utf-8") as f:
            f.write(self.PARENT_PLAN.format(journal=self.round_one))
        self.current_plan = os.path.join(self.root, ".ai", "plans", "current.md")
        os.makedirs(os.path.dirname(self.current_plan))
        with open(self.current_plan, "w", encoding="utf-8") as f:
            f.write(self.PARENT_PLAN.format(journal=self.round_one))

    def run_render_with_plan(self, findings_path):
        return subprocess.run(
            [sys.executable, SCRIPT, "--from", findings_path, "--root", self.root,
             "--plan", self.current_plan],
            capture_output=True, text=True, env=self.env,
        )

    def run_lint_structural(self, plan_path):
        return subprocess.run(
            [sys.executable, PLAN_LINT, "--plan", plan_path, "--root", self.root, "--structural"],
            capture_output=True, text=True, env=self.env,
        )

    def test_follow_up_lands_as_plan_02_in_the_same_folder(self):
        findings_path = self.write_findings("findings.json", json.dumps(TWO_FINDINGS))
        proc = self.run_render_with_plan(findings_path)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

        round_two = os.path.join(self.journal_folder, "plan-02.md")
        self.assertTrue(os.path.isfile(round_two), round_two)

        with open(round_two, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("Project: myproj", text)
        self.assertIn(f"Journal: {round_two}", text)

    def test_follow_up_carries_project_and_journal_lines(self):
        findings_path = self.write_findings("findings.json", json.dumps(TWO_FINDINGS))
        proc = self.run_render_with_plan(findings_path)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

        plan_path = proc.stdout.strip()
        with open(plan_path, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("Project: myproj", text)
        round_two = os.path.join(self.journal_folder, "plan-02.md")
        self.assertIn(f"Journal: {round_two}", text)

    def test_without_plan_behaviour_is_unchanged(self):
        findings_path = self.write_findings("findings.json", json.dumps(TWO_FINDINGS))
        proc = self.run_render(findings_path)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

        plan_path = proc.stdout.strip()
        with open(plan_path, encoding="utf-8") as f:
            text = f.read()
        self.assertNotIn("Project:", text)
        self.assertNotIn("Journal:", text)
        self.assertFalse(os.path.exists(os.path.join(self.journal_folder, "plan-02.md")))

    def test_follow_up_copies_the_parents_decisions_and_test_conventions_sections(self):
        findings_path = self.write_findings("findings.json", json.dumps(TWO_FINDINGS))
        proc = self.run_render_with_plan(findings_path)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

        plan_path = proc.stdout.strip()
        with open(plan_path, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("## Decisions", text)
        self.assertIn("Store widgets in SQLite, not in memory.", text)
        self.assertIn("## Test conventions", text)
        self.assertIn("Run `pytest` from the repo root.", text)

    def test_follow_up_passes_plan_lint_structural(self):
        findings_path = self.write_findings("findings.json", json.dumps(TWO_FINDINGS))
        proc = self.run_render_with_plan(findings_path)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

        plan_path = proc.stdout.strip()
        lint_proc = self.run_lint_structural(plan_path)
        self.assertEqual(lint_proc.returncode, 0, lint_proc.stdout + lint_proc.stderr)

    def render_from(self, parent):
        proc = subprocess.run(
            [sys.executable, SCRIPT, "--from", self.write_findings(
                "findings.json", json.dumps(TWO_FINDINGS)), "--root", self.root,
             "--plan", parent],
            capture_output=True, text=True, env=self.env,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return proc.stdout.strip()

    def test_the_follow_up_takes_the_journals_next_free_round_in_name_and_title(self):
        path = self.render_from(self.current_plan)
        self.assertEqual(os.path.basename(path), "current--r02.md")
        self.assertEqual(first_line(path), "# Widget plan (round 2)")
        self.assertEqual(first_line(os.path.join(self.journal_folder, "plan-02.md")),
                         "# Widget plan (round 2)")

    def test_three_rounds_chain_through_the_journal_with_one_title_each(self):
        parent = self.current_plan
        names, titles = [], []
        for _ in range(3):
            parent = self.render_from(parent)
            names.append(os.path.basename(parent))
            titles.append(first_line(parent))
        self.assertEqual(names, ["current--r02.md", "current--r03.md", "current--r04.md"])
        self.assertEqual(titles, ["# Widget plan (round 2)", "# Widget plan (round 3)",
                                   "# Widget plan (round 4)"])
        for number in (2, 3, 4):
            filed = os.path.join(self.journal_folder, f"plan-{number:02d}.md")
            self.assertEqual(first_line(filed), f"# Widget plan (round {number})")

    def test_reviewing_one_parent_twice_files_two_rounds(self):
        first = self.render_from(self.current_plan)
        second = self.render_from(self.current_plan)
        self.assertEqual(os.path.basename(first), "current--r02.md")
        self.assertEqual(os.path.basename(second), "current--r03.md")
        self.assertEqual(first_line(second), "# Widget plan (round 3)")
        self.assertIn(f"Journal: {os.path.join(self.journal_folder, 'plan-03.md')}",
                      read_text(second))

    def test_an_existing_plan_02_makes_it_write_plan_03(self):
        round_two = os.path.join(self.journal_folder, "plan-02.md")
        with open(round_two, "w", encoding="utf-8") as f:
            f.write("# Already filed\n\nProject: myproj\nJournal: "
                     f"{round_two}\n\n## Goal\n\nAlready here.\n")

        findings_path = self.write_findings("findings.json", json.dumps(TWO_FINDINGS))
        proc = self.run_render_with_plan(findings_path)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

        round_three = os.path.join(self.journal_folder, "plan-03.md")
        self.assertTrue(os.path.isfile(round_three), round_three)

        with open(round_two, encoding="utf-8") as f:
            self.assertIn("Already here.", f.read(), "plan-02.md should not be overwritten")

        with open(round_three, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("Project: myproj", text)
        self.assertIn(f"Journal: {round_three}", text)

    def occupy(self, folder, name):
        with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
            f.write("# Already filed\n")

    def assertOneRound(self, path, number):
        self.assertEqual(os.path.basename(path), f"current--r{number:02d}.md")
        self.assertEqual(first_line(path), f"# Widget plan (round {number})")
        filed = os.path.join(self.journal_folder, f"plan-{number:02d}.md")
        self.assertEqual(first_line(filed), f"# Widget plan (round {number})")
        self.assertIn(f"Journal: {filed}", read_text(path))

    def test_R8_the_name_title_and_journal_copy_share_one_round_number(self):
        self.assertOneRound(self.render_from(self.current_plan), 2)

    def test_R9_a_round_taken_only_in_the_plans_directory_is_skipped_in_the_journal_too(self):
        self.occupy(os.path.dirname(self.current_plan), "current--r02.md")
        self.assertOneRound(self.render_from(self.current_plan), 3)

    def test_R9_a_round_taken_only_in_the_journal_is_skipped_in_the_plans_directory_too(self):
        self.occupy(self.journal_folder, "plan-02.md")
        self.assertOneRound(self.render_from(self.current_plan), 3)

    def test_R9_a_round_taken_in_both_places_takes_the_first_free_in_both(self):
        self.occupy(os.path.dirname(self.current_plan), "current--r02.md")
        self.occupy(self.journal_folder, "plan-03.md")
        self.assertOneRound(self.render_from(self.current_plan), 4)


class TestNamesAFollowUpAfterItsParent(ReviewFindingsTestCase):
    PARENT = "# Widget plan\n\n## Goal\n\nBuild the widget.\n"

    def setUp(self):
        super().setUp()
        self.plans = os.path.join(self.root, ".ai", "plans")
        os.makedirs(self.plans)
        self.findings_path = self.write_findings("findings.json", json.dumps(TWO_FINDINGS))

    def write_parent(self, name, text=None):
        path = os.path.join(self.plans, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.PARENT if text is None else text)
        return path

    def render_from(self, parent):
        proc = subprocess.run(
            [sys.executable, SCRIPT, "--from", self.findings_path, "--root", self.root,
             "--plan", parent],
            capture_output=True, text=True, env=self.env,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return proc.stdout.strip()

    def test_a_follow_up_is_named_round_one_stem_double_hyphen_round(self):
        parent = self.write_parent("20260101000000-widget.md")
        path = self.render_from(parent)
        self.assertEqual(os.path.realpath(path),
                         os.path.join(self.plans_dir(), "20260101000000-widget--r02.md"))
        self.assertEqual(first_line(path), "# Widget plan (round 2)")

    def test_three_rounds_keep_the_name_and_title_length_constant(self):
        parent = self.write_parent("20260101000000-widget.md")
        names, titles = [], []
        for _ in range(3):
            parent = self.render_from(parent)
            names.append(os.path.basename(parent))
            titles.append(first_line(parent))
        self.assertEqual(names, ["20260101000000-widget--r02.md",
                                  "20260101000000-widget--r03.md",
                                  "20260101000000-widget--r04.md"])
        self.assertEqual(titles, ["# Widget plan (round 2)", "# Widget plan (round 3)",
                                   "# Widget plan (round 4)"])

    def test_reviewing_one_parent_twice_uses_the_next_free_round_the_second_time(self):
        parent = self.write_parent("20260101000000-widget.md")
        first = self.render_from(parent)
        second = self.render_from(parent)
        self.assertEqual(os.path.basename(first), "20260101000000-widget--r02.md")
        self.assertEqual(os.path.basename(second), "20260101000000-widget--r03.md")
        self.assertEqual(first_line(second), "# Widget plan (round 3)")
        self.assertIn("Build", read_text(parent), "the parent must not be touched")

    def test_a_legacy_long_named_parent_gets_a_short_title_and_a_suffixed_name(self):
        stem = ("20260101000000-review-followup-20260101000000-review-followup-"
                "20260101000000-widget-final-review-final-review")
        parent = self.write_parent(
            f"{stem}.md",
            "# Review follow-up: Review follow-up: Widget plan\n\n## Goal\n\nFix it.\n")
        path = self.render_from(parent)
        self.assertEqual(os.path.basename(path), f"{stem}--r02.md")
        self.assertEqual(first_line(path), "# Widget plan (round 2)")

    def test_the_title_drops_a_trailing_round_and_every_leading_prefix(self):
        parent = self.write_parent(
            "20260101000000-widget--r04.md",
            "# Review follow-up: Review follow-up: Widget plan (round 4)\n\n## Goal\n\nx\n")
        path = self.render_from(parent)
        self.assertEqual(os.path.basename(path), "20260101000000-widget--r05.md")
        self.assertEqual(first_line(path), "# Widget plan (round 5)")

    def test_a_parent_without_a_title_is_titled_from_its_goal(self):
        parent = self.write_parent("20260101000000-widget.md", "## Goal\n\nBuild the widget.\n")
        path = self.render_from(parent)
        self.assertEqual(first_line(path), "# Build the widget (round 2)")

    def test_without_plan_the_name_and_title_are_today_s(self):
        proc = subprocess.run(
            [sys.executable, SCRIPT, "--from", self.findings_path, "--root", self.root],
            capture_output=True, text=True, env=self.env,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        path = proc.stdout.strip()
        self.assertRegex(os.path.basename(path), r"^\d{14}-review-followup-findings\.md$")
        self.assertEqual(first_line(path), "# Review follow-up: findings")


class TestRendersNullLineAsTheFileAlone(ReviewFindingsTestCase):
    def test_a_null_line_renders_as_the_file_alone(self):
        findings = json.loads(json.dumps(TWO_FINDINGS))
        findings[0]["line"] = None
        findings_path = self.write_findings("findings.json", json.dumps(findings))
        proc = self.run_render(findings_path)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

        plan_path = proc.stdout.strip()
        with open(plan_path, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("- Finding: important at `src/widget.py` — "
                       "SQL query built by string formatting instead of binding", text)
        self.assertNotIn("`src/widget.py`:None", text)


class TestKeepsOnlyActionableSeverities(ReviewFindingsTestCase):
    def test_mixed_severities_render_only_blocking_and_important_steps(self):
        findings_path = self.write_findings("findings.json", json.dumps(MIXED_SEVERITY_FINDINGS))
        proc = self.run_render(findings_path)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        plan_path = proc.stdout.strip()
        with open(plan_path, encoding="utf-8") as f:
            text = f.read()

        self.assertIn("gadget.py", text)
        self.assertIn("widget.py", text)
        self.assertEqual(text.count("### "), 2,
                          "only the blocking and important findings should get a step")
        self.assertNotIn("Variable name could be clearer", text)
        self.assertNotIn("Consider extracting a helper", text)
        self.assertNotIn("This pattern is used elsewhere too", text)
        self.assertNotIn("Nice use of the existing helper", text)

    def test_mixed_severities_report_the_skipped_count_on_stderr(self):
        findings_path = self.write_findings("findings.json", json.dumps(MIXED_SEVERITY_FINDINGS))
        proc = self.run_render(findings_path)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("skipped 4", proc.stderr)


class TestRendersScenario(ReviewFindingsTestCase):
    def test_a_scenario_renders_as_its_own_line(self):
        findings_path = self.write_findings("findings.json", json.dumps(MIXED_SEVERITY_FINDINGS))
        proc = self.run_render(findings_path)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        plan_path = proc.stdout.strip()
        with open(plan_path, encoding="utf-8") as f:
            text = f.read()
        self.assertIn(
            "- Scenario: A username containing a quote reaches the query unescaped",
            text,
        )

    def test_a_missing_scenario_renders_as_not_given(self):
        findings_path = self.write_findings("findings.json", json.dumps(TWO_FINDINGS))
        proc = self.run_render(findings_path)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        plan_path = proc.stdout.strip()
        with open(plan_path, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("- Scenario: not given", text)


class TestRefusesEmptyFindings(ReviewFindingsTestCase):
    def test_an_empty_findings_array_exits_non_zero_without_writing_a_file(self):
        findings_path = self.write_findings("findings.json", "[]")
        proc = self.run_render(findings_path)
        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse(os.path.isdir(self.plans_dir()))


class TestRefusesAllNonActionableFindings(ReviewFindingsTestCase):
    def test_an_all_nit_file_exits_non_zero_without_writing_a_plan(self):
        findings_path = self.write_findings("findings.json", json.dumps(ALL_NIT_FINDINGS))
        proc = self.run_render(findings_path)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("nothing to follow up on", proc.stderr)
        self.assertFalse(os.path.isdir(self.plans_dir()))


class TestRefusesMalformedInput(ReviewFindingsTestCase):
    def test_malformed_json_is_reported_on_stderr(self):
        findings_path = self.write_findings("findings.json", "{not json")
        proc = self.run_render(findings_path)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("not valid JSON", proc.stderr)
        self.assertFalse(os.path.isdir(self.plans_dir()))


if __name__ == "__main__":
    unittest.main()

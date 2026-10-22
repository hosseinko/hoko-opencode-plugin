#!/usr/bin/env python3
"""Tests for plan-lint.py — each case is a plan written to a scratch repo."""

import os
import subprocess
import sys
import tempfile
import unittest

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plan-lint.py")

CLEAN = """# Add a supplier feed reader

## Goal

Read supplier feeds without loading them whole.

## Requirements

- **R1** The reader shall emit one record per element.
- **R2** If the feed declares no encoding, then the reader shall assume UTF-8.

## Progress

- [ ] 1. Add the streaming reader
- [ ] 2. Wire it into the importer

## Steps

### 1. Add the streaming reader

- Satisfies: R1, R2

### 2. Wire it into the importer

- Satisfies: none — internal
"""

# An accepted `## Context` heading in place of `## Goal`, a banned word and a
# dangling citation — every finding here is advisory.
NATIVE_STYLE = CLEAN.replace("## Goal", "## Context").replace(
    "shall emit one record per element", "shall be robust").replace(
    "## Requirements\n", "## Requirements\n\nSee src/Gone.php:1 for context.\n")


class PlanLintTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.root = self.tmpdir.name
        os.makedirs(os.path.join(self.root, "src"))
        with open(os.path.join(self.root, "src", "Importer.php"), "w") as f:
            f.write("<?php\n" * 40)

    def write_plan(self, text=CLEAN, **edits):
        for old, new in edits.pop("replace", {}).items():
            text = text.replace(old, new)
        path = os.path.join(self.root, "plan.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path, text

    def run_lint(self, path, structural=False, rewrite=False):
        args = [sys.executable, SCRIPT, "--plan", path, "--root", self.root]
        if structural:
            args.append("--structural")
        if rewrite:
            args.append("--rewrite")
        return subprocess.run(args, capture_output=True, text=True)

    def lint(self, text=CLEAN, structural=False, rewrite=False, **edits):
        path, _ = self.write_plan(text, **edits)
        return self.run_lint(path, structural=structural, rewrite=rewrite)

    def assertClean(self, proc):
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(proc.stdout.strip(), "")

    def assertFinding(self, proc, fragment):
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn(fragment, proc.stdout)

    def assertNote(self, proc, fragment):
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("note: line", proc.stdout)
        self.assertIn(fragment, proc.stdout)


class TestAcceptsAGoodPlan(PlanLintTestCase):
    def test_clean_plan_passes(self):
        self.assertClean(self.lint())

    def test_a_named_component_is_not_implementation(self):
        self.assertClean(self.lint(replace={
            "The reader shall": "The JsonSchemaValidator shall"}))

    def test_handler_survives_the_handle_ban(self):
        self.assertClean(self.lint(replace={
            "The reader shall emit": "The feed handler shall emit"}))

    def test_a_spec_id_may_ride_along(self):
        self.assertClean(self.lint(replace={"**R1**": "**R1 (SPEC-012/REQ-3)**"}))


class TestStructure(PlanLintTestCase):
    def test_requirement_claimed_by_no_step(self):
        self.assertFinding(self.lint(replace={"- Satisfies: R1, R2": "- Satisfies: R1"}),
                           "R2 is claimed by no step")

    def test_requirement_claimed_twice(self):
        self.assertFinding(self.lint(replace={"- Satisfies: none — internal": "- Satisfies: R1"}),
                           "R1 is claimed twice")

    def test_claim_of_an_undeclared_requirement(self):
        self.assertFinding(self.lint(replace={"- Satisfies: R1, R2": "- Satisfies: R1, R2, R9"}),
                           "claims R9, which no requirement declares")

    def test_satisfies_that_says_nothing(self):
        self.assertNote(self.lint(replace={"- Satisfies: none — internal": "- Satisfies:"}),
                        "does not say `none — internal`")

    def test_progress_box_without_a_step(self):
        self.assertFinding(self.lint(replace={
            "- [ ] 2. Wire it into the importer": "- [ ] 2. Wire it into the importer\n- [ ] 3. Ship it"}),
            "box 3 with no step to match")

    def test_step_without_a_progress_box(self):
        self.assertFinding(self.lint(replace={"- [ ] 2. Wire it into the importer\n": ""}),
                           "step 2 has no box in `## Progress`")

    def test_box_title_drifted_from_the_heading(self):
        self.assertFinding(self.lint(replace={"- [ ] 1. Add the streaming reader": "- [ ] 1. Add the reader"}),
                           "the step heading reads")

    def test_missing_progress_section(self):
        self.assertFinding(self.lint(replace={"## Progress": "## Notes"}),
                           "no `## Progress` section")

    def test_step_without_a_files_line_has_no_finding(self):
        self.assertClean(self.lint())

    def test_step_without_a_satisfies_line(self):
        self.assertNote(self.lint(replace={"- Satisfies: none — internal\n": ""}),
                        "step 2 has no `Satisfies:` line")

    def test_a_context_section_stands_in_for_goal(self):
        self.assertClean(self.lint(replace={"## Goal": "## Context"}))

    def test_missing_both_goal_and_context_is_advisory(self):
        self.assertNote(self.lint(replace={"## Goal": "## Something Else"}),
                        "no `## Goal` section")

    def test_steps_numbered_with_a_gap(self):
        self.assertFinding(self.lint(replace={"### 2. Wire it into the importer": "### 3. Wire it into the importer"}),
                           "expected [1, 2]")

    def test_a_step_number_used_twice(self):
        self.assertFinding(self.lint(replace={"### 2. Wire it into the importer": "### 1. Wire it into the importer"}),
                           "step 1 appears twice")

    def test_no_steps_section(self):
        self.assertFinding(self.lint(replace={"## Steps": "## Notes"}),
                           "no `## Steps` section")

    def test_an_undeclared_satisfies_id_blocks_while_a_missing_goal_only_notes(self):
        undeclared = self.lint(replace={"- Satisfies: R1, R2": "- Satisfies: R1, R2, R9"})
        self.assertFinding(undeclared, "claims R9, which no requirement declares")
        missing_goal = self.lint(replace={"## Goal": "## Something Else"})
        self.assertNote(missing_goal, "no `## Goal` section")


SPEC = """---
id: SPEC-007
title: Login redirect
---

# Login redirect

## Requirements

- **REQ-1** When a session expires, the login page shall show the expiry notice.
- **REQ-2** When a user signs in, the login page shall redirect to the page they came from.
- **REQ-5** If the target is off-site, then the login page shall redirect to the dashboard.
"""

SPEC_PLAN = """# Add the redirect guard

Spec: specs/login.md (SPEC-007: REQ-2, REQ-5)

## Goal

Send a signed-in user back where they came from.

## Progress

- [ ] 1. Add the redirect guard
- [ ] 2. Cover the off-site target

## Steps

### 1. Add the redirect guard

- Satisfies: SPEC-007/REQ-2

### 2. Cover the off-site target

- Satisfies: SPEC-007/REQ-5
"""


class TestSpecReferences(PlanLintTestCase):
    """A plan with a `Spec:` line points at a spec's requirements instead of restating
    them, and `Satisfies:` claims `<spec id>/REQ-N`."""

    def write_spec(self, path="specs/login.md", text=SPEC):
        full = os.path.join(self.root, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(text)

    def setUp(self):
        super().setUp()
        self.write_spec()

    def test_a_listed_requirement_the_spec_contains_is_accepted_without_a_requirements_section(self):
        self.assertClean(self.lint(SPEC_PLAN))

    def test_a_task_local_spec_resolves_against_the_plans_own_folder(self):
        os.makedirs(os.path.join(self.root, "task"))
        with open(os.path.join(self.root, "task", "spec.md"), "w", encoding="utf-8") as f:
            f.write(SPEC)
        self.assertClean(self.lint(SPEC_PLAN, replace={"specs/login.md": "task/spec.md"}))

    def test_a_spec_at_an_absolute_path_resolves(self):
        self.assertClean(self.lint(SPEC_PLAN, replace={
            "specs/login.md": os.path.join(self.root, "specs", "login.md")}))

    def test_a_spec_id_that_differs_from_the_front_matter_blocks(self):
        self.assertFinding(self.lint(SPEC_PLAN.replace("SPEC-007", "SPEC-008")),
                           "front matter says SPEC-007")

    def test_a_spec_without_a_front_matter_id_blocks(self):
        self.write_spec(text=SPEC.replace("id: SPEC-007\n", ""))
        self.assertFinding(self.lint(SPEC_PLAN), "no `id:` in its front matter")

    def test_a_spec_file_that_does_not_exist_blocks(self):
        self.assertFinding(self.lint(SPEC_PLAN, replace={"specs/login.md": "specs/gone.md"}),
                           "there is no such file")

    def test_a_malformed_spec_line_blocks(self):
        self.assertFinding(self.lint(SPEC_PLAN, replace={"(SPEC-007: REQ-2, REQ-5)": "REQ-2, REQ-5"}),
                           "`Spec:` line is not")

    def test_a_claim_of_a_requirement_the_spec_line_does_not_list_blocks(self):
        self.assertFinding(self.lint(SPEC_PLAN, replace={"- Satisfies: SPEC-007/REQ-5": "- Satisfies: SPEC-007/REQ-1"}),
                           "claims SPEC-007/REQ-1, which the `Spec:` line does not list")

    def test_a_claim_naming_a_spec_no_line_names_blocks(self):
        self.assertFinding(self.lint(SPEC_PLAN, replace={"- Satisfies: SPEC-007/REQ-5": "- Satisfies: SPEC-009/REQ-5"}),
                           "no `Spec:` line names SPEC-009")

    def test_a_requirement_claimed_twice_blocks(self):
        self.assertFinding(self.lint(SPEC_PLAN, replace={"- Satisfies: SPEC-007/REQ-5": "- Satisfies: SPEC-007/REQ-2"}),
                           "SPEC-007/REQ-2 is claimed twice")

    def test_a_plan_may_claim_spec_requirements_and_its_own_r_ids(self):
        plan = SPEC_PLAN.replace(
            "## Progress", "## Requirements\n\n- **R1** The guard shall log each redirect.\n\n## Progress").replace(
            "- Satisfies: SPEC-007/REQ-5", "- Satisfies: SPEC-007/REQ-5, R1")
        self.assertClean(self.lint(plan))

    def test_a_claimed_requirement_absent_from_the_spec_blocks(self):
        plan = SPEC_PLAN.replace("REQ-2, REQ-5", "REQ-2, REQ-9").replace(
            "- Satisfies: SPEC-007/REQ-5", "- Satisfies: SPEC-007/REQ-9")
        self.assertFinding(self.lint(plan), "claims SPEC-007/REQ-9, which SPEC-007 does not contain")

    def test_a_listed_requirement_absent_from_the_spec_blocks(self):
        plan = SPEC_PLAN.replace("REQ-2, REQ-5", "REQ-2, REQ-9").replace(
            "- Satisfies: SPEC-007/REQ-5", "- Satisfies: none — internal")
        self.assertFinding(self.lint(plan), "lists REQ-9, which SPEC-007 does not contain")

    def test_a_requirement_absent_from_the_spec_is_not_also_reported_unclaimed(self):
        plan = SPEC_PLAN.replace("REQ-2, REQ-5", "REQ-2, REQ-9").replace(
            "- Satisfies: SPEC-007/REQ-5", "- Satisfies: none — internal")
        self.assertNotIn("SPEC-007/REQ-9 is claimed by no step", self.lint(plan).stdout)

    RETIRED_SPEC = SPEC.replace("- **REQ-5** If the target is off-site, then the login page shall "
                                "redirect to the dashboard.", "- **REQ-5** _Retired._")

    def test_a_listed_requirement_the_spec_marks_retired_blocks_as_retired(self):
        self.write_spec(text=self.RETIRED_SPEC)
        proc = self.lint(SPEC_PLAN, replace={"- Satisfies: SPEC-007/REQ-5": "- Satisfies: none — internal"})
        self.assertFinding(proc, "lists REQ-5, which SPEC-007 has retired")
        self.assertNotIn("does not contain", proc.stdout)
        self.assertNotIn("SPEC-007/REQ-5 is claimed by no step", proc.stdout)

    def test_a_claimed_requirement_the_spec_marks_retired_blocks_as_retired(self):
        self.write_spec(text=self.RETIRED_SPEC)
        plan = SPEC_PLAN.replace("REQ-2, REQ-5", "REQ-2")
        proc = self.lint(plan)
        self.assertFinding(proc, "`Satisfies:` claims SPEC-007/REQ-5, which SPEC-007 has retired")
        self.assertNotIn("does not contain", proc.stdout)
        self.assertNotIn("does not list", proc.stdout)

    def test_a_listed_requirement_no_step_claims_blocks(self):
        self.assertFinding(self.lint(SPEC_PLAN, replace={"- Satisfies: SPEC-007/REQ-5": "- Satisfies: none — internal"}),
                           "SPEC-007/REQ-5 is claimed by no step")

    def test_a_plan_without_a_spec_line_still_checks_r_ids_as_before(self):
        self.assertFinding(self.lint(replace={"- Satisfies: R1, R2": "- Satisfies: R1"}),
                           "R2 is claimed by no step")

    def test_a_spec_claim_in_a_plan_with_no_spec_line_blocks(self):
        self.assertFinding(self.lint(replace={"- Satisfies: none — internal": "- Satisfies: SPEC-007/REQ-2"}),
                           "no `Spec:` line names SPEC-007")

    def test_the_structural_preflight_enforces_the_spec_claims_too(self):
        proc = self.lint(SPEC_PLAN, structural=True, replace={
            "- Satisfies: SPEC-007/REQ-5": "- Satisfies: none — internal"})
        self.assertFinding(proc, "SPEC-007/REQ-5 is claimed by no step")


class TestVerifyTitledSteps(PlanLintTestCase):
    """Decisions: a step titled to verify rather than change comes back as a no-op,
    so the finding is advisory, never a denial."""

    def test_a_verify_titled_step_is_advisory(self):
        self.assertNote(self.lint(replace={
            "### 2. Wire it into the importer": "### 2. Verify the streaming reader",
            "- [ ] 2. Wire it into the importer": "- [ ] 2. Verify the streaming reader"}),
            "is titled to verify")

    def test_a_run_titled_step_is_advisory_too(self):
        self.assertNote(self.lint(replace={
            "### 2. Wire it into the importer": "### 2. Run the regression suite",
            "- [ ] 2. Wire it into the importer": "- [ ] 2. Run the regression suite"}),
            "is titled to run")


class TestStructuralFlag(PlanLintTestCase):
    """execute-plan's preflight: `--structural` reports only what would block
    approval, and never touches `## Progress`."""

    def test_structural_ignores_an_advisory_only_finding(self):
        proc = self.lint(structural=True, replace={
            "shall emit one record per element": "shall be robust"})
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(proc.stdout.strip(), "")

    def test_structural_still_denies_a_blocking_finding(self):
        proc = self.lint(structural=True, replace={"- Satisfies: R1, R2": "- Satisfies: R1"})
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("R2 is claimed by no step", proc.stdout)

    def test_structural_skips_the_progress_check(self):
        proc = self.lint(structural=True, replace={"## Progress": "## Notes"})
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(proc.stdout.strip(), "")


class TestNativeStylePlan(PlanLintTestCase):
    """A plan mixing a `## Context` heading with only advisory findings passes the CLI
    clean, notes and all."""

    def test_only_advisory_findings_exit_clean_with_notes(self):
        proc = self.lint(NATIVE_STYLE)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("note: line", proc.stdout)
        self.assertIn("says 'robust'", proc.stdout)
        self.assertIn("no such file", proc.stdout)


class TestFenceAndSectionScoping(PlanLintTestCase):
    """A `## `, `### N.` or `- [ ] N.` line inside fenced code, or outside its
    own section, is not a real one."""

    def test_a_box_under_verification_does_not_duplicate_progress(self):
        self.assertClean(self.lint(replace={
            "- Satisfies: none — internal\n":
                "- Satisfies: none — internal\n\n## Verification\n\n- [ ] 1. Run the whole suite\n"}))

    def test_a_box_inside_a_fence_within_progress_does_not_duplicate(self):
        self.assertClean(self.lint(replace={
            "- [ ] 2. Wire it into the importer\n":
                "- [ ] 2. Wire it into the importer\n\n```\n- [ ] 1. Example checkbox syntax\n```\n"}))

    def test_a_step_heading_inside_a_fence_within_steps_does_not_duplicate(self):
        self.assertClean(self.lint(replace={
            "- Satisfies: R1, R2\n":
                "- Satisfies: R1, R2\n\n```\n### 1. Not a real step\n```\n"}))

    def test_a_plan_whose_only_heading_is_fenced_is_not_a_plan(self):
        proc = self.lint("```\n## Goal\n```\n")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("not in the plan format", proc.stderr)

    def test_a_fenced_heading_does_not_count_as_a_section(self):
        proc = self.lint(CLEAN.replace(
            "## Goal\n", "```\n## Not a real section\n```\n\n## Goal\n"))
        self.assertClean(proc)


class TestRequirementProse(PlanLintTestCase):
    def test_missing_shall(self):
        self.assertFinding(self.lint(replace={"The reader shall emit": "The reader emits"}),
                           "has no ` shall `")

    def test_banned_word(self):
        self.assertNote(self.lint(replace={
            "shall emit one record per element": "shall be robust"}), "says 'robust'")

    def test_shall_handle_is_banned(self):
        self.assertNote(self.lint(replace={
            "shall emit one record per element": "shall handle bad input"}), "says 'handle'")

    def test_method_call_is_implementation(self):
        self.assertNote(self.lint(replace={
            "shall emit one record per element": "shall call Reader::next()"}),
            "names implementation")

    def test_duplicate_requirement_id(self):
        self.assertFinding(self.lint(replace={"- **R2** If": "- **R1** If"}),
                           "R1 is declared twice")


class TestPaths(PlanLintTestCase):
    def test_citation_past_the_end_of_the_file(self):
        self.assertNote(self.lint(replace={
            "## Goal\n": "## Goal\n\nSee src/Importer.php:900 for the loop.\n"}),
            "that file has 40 lines")

    def test_citation_to_a_file_that_is_gone(self):
        self.assertNote(self.lint(replace={
            "## Goal\n": "## Goal\n\nSee src/Gone.php:12 for the loop.\n"}),
            "no such file")

    def test_citation_inside_the_file_is_fine(self):
        self.assertClean(self.lint(replace={
            "## Goal\n": "## Goal\n\nSee src/Importer.php:12 for the loop.\n"}))


class TestUnusable(PlanLintTestCase):
    def test_not_a_plan(self):
        proc = self.lint("just some notes\n")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("not in the plan format", proc.stderr)

    def test_missing_file(self):
        proc = subprocess.run(
            [sys.executable, SCRIPT, "--plan", os.path.join(self.root, "nope.md")],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("cannot read", proc.stderr)


LIST_FORM = CLEAN.replace("### 1. Add the streaming reader\n", "1. **Add the streaming reader.** Read in chunks.\n").replace(
    "### 2. Wire it into the importer\n", "2. **Wire it into the importer.**\n")


class TestRewriteListSteps(PlanLintTestCase):
    def test_a_numbered_list_steps_section_is_rewritten_into_headings(self):
        path, _ = self.write_plan(LIST_FORM)
        proc = self.run_lint(path, rewrite=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(proc.stdout.strip(), "")
        with open(path, encoding="utf-8") as f:
            rewritten = f.read()
        self.assertIn("### 1. Add the streaming reader\nRead in chunks.\n", rewritten)
        self.assertIn("### 2. Wire it into the importer\n", rewritten)
        self.assertNotIn("**Add the streaming reader", rewritten)

    def test_a_plan_with_step_headings_is_left_byte_for_byte(self):
        path, text = self.write_plan()
        proc = self.run_lint(path, rewrite=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), text)

    def test_a_rewritten_plan_with_a_blocking_finding_still_exits_one(self):
        path, _ = self.write_plan(LIST_FORM.replace("- Satisfies: R1, R2", "- Satisfies: R1"))
        proc = self.run_lint(path, rewrite=True)
        self.assertFinding(proc, "R2 is claimed by no step")
        with open(path, encoding="utf-8") as f:
            self.assertIn("### 1. Add the streaming reader", f.read())

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root ignores file modes")
    def test_a_read_only_plan_file_is_linted_as_written_and_blocks(self):
        path, _ = self.write_plan(LIST_FORM)
        os.chmod(path, 0o444)
        self.addCleanup(os.chmod, path, 0o644)
        proc = self.run_lint(path, rewrite=True)
        self.assertFinding(proc, "no `### <N>. <title>` step headings")
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), LIST_FORM)


if __name__ == "__main__":
    unittest.main()

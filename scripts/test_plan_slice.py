#!/usr/bin/env python3
"""Tests for plan-slice.py — run each case as a subprocess against a scratch directory."""

import os
import subprocess
import sys
import tempfile
import unittest

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plan-slice.py")

PLAN = """# Add a supplier feed reader

Status: in progress

## Goal

Read supplier feeds without loading them whole.

## Decisions

- Stream with a SAX parser.

## Progress

- [x] 1. Add the streaming reader
- [ ] 2. Wire it into the importer

## Steps

### 1. Add the streaming reader

- Files: src/Reader.php
- Change: the SAX loop.

### 2. Wire it into the importer

- Files: src/Importer.php
- Satisfies: R1

## Open questions

- Does the vendor feed declare an encoding?
"""


class PlanSliceTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.out = os.path.join(self.tmpdir.name, "out")

    def plan(self, text=PLAN, name="20260101-plan.md"):
        path = os.path.join(self.tmpdir.name, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def slice_it(self, plan, step):
        return subprocess.run(
            [sys.executable, SCRIPT, "--plan", plan, "--step", str(step), "--out-dir", self.out],
            capture_output=True, text=True,
        )

    def sliced(self, plan, step):
        proc = self.slice_it(plan, step)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        with open(proc.stdout.strip(), encoding="utf-8") as f:
            return proc.stdout.strip(), f.read()


class TestSlice(PlanSliceTestCase):
    def test_carries_the_shared_sections(self):
        _, text = self.sliced(self.plan(), 2)
        for kept in ("# Add a supplier feed reader", "## Goal", "## Decisions",
                     "## Progress", "## Open questions"):
            self.assertIn(kept, text)

    def test_carries_a_section_the_template_never_named(self):
        plan = self.plan(PLAN.replace("## Goal", "## Context"))
        _, text = self.sliced(plan, 2)
        self.assertIn("## Context", text)
        self.assertIn("Read supplier feeds without loading them whole.", text)

    def test_carries_only_the_asked_for_step(self):
        _, text = self.sliced(self.plan(), 2)
        self.assertIn("### 2. Wire it into the importer", text)
        self.assertIn("src/Importer.php", text)
        self.assertNotIn("### 1. Add the streaming reader\n\n- Files", text)
        self.assertNotIn("the SAX loop", text)

    def test_progress_keeps_the_other_steps_visible(self):
        _, text = self.sliced(self.plan(), 2)
        self.assertIn("- [x] 1. Add the streaming reader", text)

    def test_names_the_plan_it_came_from(self):
        plan = self.plan()
        _, text = self.sliced(plan, 1)
        self.assertIn(plan, text)
        self.assertIn("Step 1 of 2", text)

    def test_drops_the_status_line(self):
        _, text = self.sliced(self.plan(), 1)
        self.assertNotIn("Status:", text)

    def test_a_heading_inside_a_fence_within_steps_does_not_truncate_the_steps_section(self):
        plan = self.plan(PLAN.replace(
            "- Files: src/Reader.php\n- Change: the SAX loop.\n",
            "- Files: src/Reader.php\n- Change: the SAX loop.\n\n```\n## Fake section\n```\n",
        ))
        _, text = self.sliced(plan, 2)
        self.assertIn("### 2. Wire it into the importer", text)
        self.assertIn("src/Importer.php", text)

    def test_reslicing_replaces_the_stale_copy(self):
        plan = self.plan()
        first, _ = self.sliced(plan, 2)
        with open(plan, "a", encoding="utf-8") as f:
            f.write("\n- Change: amended after a review finding.\n")
        second, text = self.sliced(plan, 2)
        self.assertEqual(first, second)
        self.assertIn("amended after a review finding", text)
        self.assertEqual(len(os.listdir(self.out)), 1)

    def test_default_out_dir_is_dot_slices_next_to_the_plan(self):
        # R12: without --out-dir, the slice lands under <repo>/.ai/plans/.slices/,
        # gitignored along with the plans directory instead of $TMPDIR.
        plans_dir = os.path.join(self.tmpdir.name, "repo", ".ai", "plans")
        os.makedirs(plans_dir, exist_ok=True)
        plan = os.path.join(plans_dir, "20260101-plan.md")
        with open(plan, "w", encoding="utf-8") as f:
            f.write(PLAN)
        proc = subprocess.run(
            [sys.executable, SCRIPT, "--plan", plan, "--step", "2"],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        destination = proc.stdout.strip()
        self.assertEqual(os.path.dirname(destination),
                          os.path.join(os.path.realpath(plans_dir), ".slices"))


class TestRefusesToGuess(PlanSliceTestCase):
    """Every failure must be loud: the caller falls back to the whole plan."""

    def assertRefused(self, proc, because):
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn(because, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "")

    def test_missing_plan_file(self):
        self.assertRefused(
            self.slice_it(os.path.join(self.tmpdir.name, "nope.md"), 1), "no plan file")

    def test_unknown_step(self):
        proc = self.slice_it(self.plan(), 7)
        self.assertRefused(proc, "no step 7")
        self.assertIn("it has 1, 2", proc.stderr)

    def test_no_steps_section(self):
        self.assertRefused(
            self.slice_it(self.plan("## Goal\n\nSomething.\n"), 1), "no `## Steps` section")

    def test_no_numbered_headings(self):
        self.assertRefused(
            self.slice_it(self.plan("## Steps\n\nJust prose, no headings.\n"), 1),
            "no `### <N>.` headings")

    def test_duplicate_step_numbers(self):
        self.assertRefused(
            self.slice_it(self.plan("## Steps\n\n### 1. One\n\n- Files: a\n\n### 1. Again\n\n- Files: b\n"), 1),
            "2 steps numbered 1")

    def test_heading_without_a_body(self):
        self.assertRefused(
            self.slice_it(self.plan("## Steps\n\n### 1. One\n\n### 2. Two\n\n- Files: b\n"), 1),
            "heading and no body")

    def test_not_a_plan_at_all(self):
        self.assertRefused(
            self.slice_it(self.plan("just some notes\n"), 1), "not in the plan format")


if __name__ == "__main__":
    unittest.main()

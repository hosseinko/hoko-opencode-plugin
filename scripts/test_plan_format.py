#!/usr/bin/env python3
"""Tests for plan_format.py — the shared grammar every plan parser reads by.

Unlike the other scripts, this one is a library, not a CLI, so it is imported and
called directly rather than run as a subprocess.
"""

import unittest

import plan_format

FENCED_PLAN = """\
# Some plan

## Goal

Do the thing.

## Example

```
## Not a real section
### 1. Not a real step
- [ ] 1. Not a real box
```

## Requirements

- **R1** The thing shall happen.

## Progress

- [ ] 1. Do it

## Steps

### 1. Do it

- Satisfies: R1
"""

STRAY_CONSTRUCTS_PLAN = """\
# Some plan

## Goal

Do the thing.

## Requirements

- **R1** The thing shall happen.

## Verification

- [ ] 1. This looks like a box but it is not one
### 1. This looks like a step but it is not one

## Progress

- [ ] 1. Do it

## Steps

### 1. Do it

- Satisfies: R1
"""


class TestSections(unittest.TestCase):
    def test_finds_top_level_sections_in_order(self):
        names = [name for name, _s, _e in plan_format.sections(FENCED_PLAN)]
        self.assertEqual(names, ["Goal", "Example", "Requirements", "Progress", "Steps"])

    def test_a_heading_inside_a_fence_is_not_a_section(self):
        names = [name for name, _s, _e in plan_format.sections(FENCED_PLAN)]
        self.assertNotIn("Not a real section", names)

    def test_no_sections_at_all(self):
        self.assertEqual(plan_format.sections("just some notes\n"), [])

    def test_section_span_is_case_insensitive_and_ignores_a_trailing_colon(self):
        span = plan_format.section_span("## Goal:\n\nText.\n", "goal")
        self.assertIsNotNone(span)

    def test_section_span_missing_section_is_none(self):
        self.assertIsNone(plan_format.section_span(FENCED_PLAN, "Decisions"))


class TestStepMatches(unittest.TestCase):
    def test_a_step_heading_inside_a_fence_is_ignored(self):
        numbers = [int(m.group(1)) for m in plan_format.step_matches(FENCED_PLAN)]
        self.assertEqual(numbers, [1])

    def test_a_step_heading_outside_steps_is_ignored(self):
        numbers = [int(m.group(1)) for m in plan_format.step_matches(STRAY_CONSTRUCTS_PLAN)]
        self.assertEqual(numbers, [1])

    def test_no_steps_section_gives_no_matches(self):
        self.assertEqual(plan_format.step_matches("## Goal\n\nText.\n"), [])


class TestStepHeadingVariants(unittest.TestCase):
    def _numbers(self, heading):
        text = f"## Steps\n\n{heading}\n\n- Satisfies: R1\n"
        return [int(m.group(1)) for m in plan_format.step_matches(text)]

    def test_accepts_dot_separator(self):
        self.assertEqual(self._numbers("### 1. Do it"), [1])

    def test_accepts_colon_separator(self):
        self.assertEqual(self._numbers("### 1: Do it"), [1])

    def test_accepts_close_paren_separator(self):
        self.assertEqual(self._numbers("### 1) Do it"), [1])

    def test_accepts_hyphen_separator(self):
        self.assertEqual(self._numbers("### 1 - Do it"), [1])

    def test_accepts_em_dash_separator(self):
        self.assertEqual(self._numbers("### 1 — Do it"), [1])

    def test_accepts_en_dash_separator(self):
        self.assertEqual(self._numbers("### 1 – Do it"), [1])

    def test_accepts_step_prefix_any_case(self):
        self.assertEqual(self._numbers("### Step 1: Do it"), [1])
        self.assertEqual(self._numbers("### STEP 1. Do it"), [1])

    def test_rejects_a_numberless_heading(self):
        self.assertEqual(self._numbers("### Do it"), [])


LIST_STEPS_PLAN = """\
# Some plan

## Goal

1. **Not a step.** This numbered item is outside Steps.

## Steps

1. **Rename compose file.** Move it and update the references.
   - Satisfies: R1
2. **Add the hook**
   More detail on the hook.

   1. **Nested item.** Indented, so a step body, not a step.
3. **Wire it up.**

```
4. **Fenced.** Not a step either.
```

## Verification

1. **Run the suite.** Not a step.
"""


class TestNormaliseListSteps(unittest.TestCase):
    def test_list_form_becomes_step_headings(self):
        out = plan_format.normalise_list_steps(LIST_STEPS_PLAN)
        steps = [(int(m.group(1)), m.group(2)) for m in plan_format.step_matches(out)]
        self.assertEqual(steps, [(1, "Rename compose file"), (2, "Add the hook"), (3, "Wire it up")])

    def test_text_after_the_bold_moves_to_the_next_line(self):
        out = plan_format.normalise_list_steps(LIST_STEPS_PLAN)
        self.assertIn("### 1. Rename compose file\nMove it and update the references.\n   - Satisfies: R1\n", out)

    def test_a_bold_only_item_gets_a_heading_with_no_extra_line(self):
        out = plan_format.normalise_list_steps(LIST_STEPS_PLAN)
        self.assertIn("### 3. Wire it up\n\n```", out)

    def test_continuation_lines_are_left_as_they_are(self):
        out = plan_format.normalise_list_steps(LIST_STEPS_PLAN)
        self.assertIn("### 2. Add the hook\n   More detail on the hook.\n", out)

    def test_an_indented_numbered_item_in_a_step_body_is_unchanged(self):
        out = plan_format.normalise_list_steps(LIST_STEPS_PLAN)
        self.assertIn("   1. **Nested item.** Indented, so a step body, not a step.\n", out)

    def test_a_numbered_item_inside_a_fence_is_unchanged(self):
        out = plan_format.normalise_list_steps(LIST_STEPS_PLAN)
        self.assertIn("```\n4. **Fenced.** Not a step either.\n```", out)

    def test_other_sections_are_unchanged(self):
        out = plan_format.normalise_list_steps(LIST_STEPS_PLAN)
        self.assertIn("1. **Not a step.** This numbered item is outside Steps.\n", out)
        self.assertIn("## Verification\n\n1. **Run the suite.** Not a step.\n", out)
        self.assertEqual(out.split("## Steps")[0], LIST_STEPS_PLAN.split("## Steps")[0])

    def test_a_plan_with_step_headings_is_returned_untouched(self):
        text = FENCED_PLAN + "\n1. **Stray.** A list item after the heading.\n"
        self.assertEqual(plan_format.normalise_list_steps(text), text)

    def test_a_plan_without_a_steps_section_is_returned_untouched(self):
        text = "## Goal\n\n1. **Not a step.** Text.\n"
        self.assertEqual(plan_format.normalise_list_steps(text), text)


class TestProgressBoxMatches(unittest.TestCase):
    def test_a_box_inside_a_fence_is_ignored(self):
        numbers = [int(m.group(2)) for m in plan_format.progress_box_matches(FENCED_PLAN)]
        self.assertEqual(numbers, [1])

    def test_a_box_outside_progress_is_ignored(self):
        numbers = [int(m.group(2)) for m in plan_format.progress_box_matches(STRAY_CONSTRUCTS_PLAN)]
        self.assertEqual(numbers, [1])

    def test_no_progress_section_gives_no_matches(self):
        self.assertEqual(plan_format.progress_box_matches("## Goal\n\nText.\n"), [])


class TestRequirementMatches(unittest.TestCase):
    def test_finds_requirements_only_under_requirements(self):
        rids = [m.group(1) for m in plan_format.requirement_matches(FENCED_PLAN)]
        self.assertEqual(rids, ["R1"])

    def test_a_requirement_line_outside_requirements_is_ignored(self):
        text = "## Goal\n\n- **R9** Something shall happen.\n\n## Requirements\n\n- **R1** The thing shall happen.\n"
        rids = [m.group(1) for m in plan_format.requirement_matches(text)]
        self.assertEqual(rids, ["R1"])


class TestSpecReferences(unittest.TestCase):
    def test_reads_the_path_id_and_requirements_of_a_spec_line(self):
        plan = "# T\nProject: p\nSpec: specs/login.md (SPEC-007: REQ-2, REQ-5)\n\n## Goal\n\nx\n"
        [ref] = plan_format.spec_references(plan)
        self.assertEqual((ref.line, ref.path, ref.spec_id, ref.reqs),
                         (3, "specs/login.md", "SPEC-007", ["REQ-2", "REQ-5"]))

    def test_several_spec_lines_come_back_in_file_order(self):
        plan = "# T\nSpec: a.md (SPEC-1: REQ-1)\nSpec: b.md (SPEC-2: REQ-3)\n\n## Goal\n"
        self.assertEqual([r.spec_id for r in plan_format.spec_references(plan)], ["SPEC-1", "SPEC-2"])

    def test_a_line_without_the_requirement_list_is_not_well_formed(self):
        [ref] = plan_format.spec_references("# T\nSpec: specs/login.md\n\n## Goal\n")
        self.assertFalse(ref.well_formed)
        self.assertEqual(ref.path, "specs/login.md")

    def test_a_spec_line_below_the_first_section_is_prose(self):
        self.assertEqual(plan_format.spec_references("# T\n\n## Goal\n\nSpec: a.md (SPEC-1: REQ-1)\n"), [])

    def test_a_spec_line_inside_a_fence_is_ignored(self):
        self.assertEqual(plan_format.spec_references("# T\n```\nSpec: a.md (SPEC-1: REQ-1)\n```\n## Goal\n"), [])

    def test_the_spec_id_is_read_from_front_matter(self):
        self.assertEqual(plan_format.spec_id("---\nid: SPEC-007\ntitle: x\n---\n# X\n"), "SPEC-007")

    def test_a_spec_without_front_matter_has_no_id(self):
        self.assertIsNone(plan_format.spec_id("# X\n\nid: SPEC-007\n"))

    def test_the_requirements_a_spec_declares_skip_fenced_examples(self):
        text = "- **REQ-1** A shall b.\n\n```\n- **REQ-9** Example.\n```\n- **REQ-2 (draft)** C shall d.\n"
        self.assertEqual(plan_format.spec_requirement_ids(text), {"REQ-1", "REQ-2"})

    RETIRED_TEXT = "- **REQ-1** A shall b.\n- **REQ-2** _Retired._\n\n```\n- **REQ-9** _Retired._\n```\n"

    def test_a_retired_requirement_is_not_a_live_one(self):
        self.assertEqual(plan_format.spec_requirement_ids(self.RETIRED_TEXT), {"REQ-1"})

    def test_the_retired_requirements_skip_fenced_examples(self):
        self.assertEqual(plan_format.retired_requirement_ids(self.RETIRED_TEXT), {"REQ-2"})


class TestIsComplete(unittest.TestCase):
    def test_status_complete_counts_as_finished(self):
        self.assertTrue(plan_format.is_complete("Status: complete\n\n# Plan\n"))

    def test_bold_status_complete_counts_as_finished(self):
        self.assertTrue(plan_format.is_complete("**Status:** complete\n\n# Plan\n"))

    def test_trailing_text_after_complete_still_counts(self):
        self.assertTrue(plan_format.is_complete("Status: complete — closed by review\n\n# Plan\n"))

    def test_status_in_progress_is_not_complete(self):
        self.assertFalse(plan_format.is_complete("Status: in progress\n\n# Plan\n"))

    def test_no_status_line_is_not_complete(self):
        self.assertFalse(plan_format.is_complete("# Plan\n\n## Goal\n\nText.\n"))

    def test_a_status_line_past_the_header_block_does_not_count(self):
        text = "# Plan\n\n## Goal\n\nSee the note below: Status: complete in the old plan.\n"
        self.assertFalse(plan_format.is_complete(text))


FENCED_LINES = (
    "```text\n"
    "Journal: /elsewhere/plan-09.md\n"
    "Base: deadbeef\n"
    "Status: complete\n"
    "```\n"
)


def plan_with_fenced_header_lines(header=""):
    """A plan whose `## Decisions` quotes another plan's header lines in a fence."""
    return (f"# Plan\n{header}\n## Goal\nShow the lines.\n\n## Decisions\n\n{FENCED_LINES}\n"
            "## Steps\n\n### 1. Do it\n\n- Files: `a.py`\n")


class TestHeaderLine(unittest.TestCase):
    def test_reads_the_value_of_a_header_line(self):
        text = "# Plan\nJournal:   /x/plan-01.md  \n\n## Goal\n"
        self.assertEqual(plan_format.header_line(text, "Journal"), "/x/plan-01.md")

    def test_a_missing_or_empty_line_is_none(self):
        self.assertIsNone(plan_format.header_line("# Plan\n\n## Goal\n", "Journal"))
        self.assertIsNone(plan_format.header_line("# Plan\nJournal:\n\n## Goal\n", "Journal"))

    def test_a_line_inside_a_fence_below_the_first_heading_is_not_read(self):
        text = plan_with_fenced_header_lines()
        self.assertIsNone(plan_format.header_line(text, "Journal"))

    def test_a_line_past_the_first_heading_is_not_read(self):
        text = "# Plan\n\n## Goal\nJournal: /x/plan-01.md\n"
        self.assertIsNone(plan_format.header_line(text, "Journal"))

    def test_a_fence_above_the_first_heading_hides_its_lines_but_not_the_real_one(self):
        text = f"# Plan\n{FENCED_LINES}Journal: /x/plan-01.md\n\n## Goal\n"
        self.assertEqual(plan_format.header_line(text, "Journal"), "/x/plan-01.md")
        self.assertIsNone(plan_format.header_line(f"# Plan\n{FENCED_LINES}\n## Goal\n", "Base"))

    def test_a_plan_with_no_heading_reads_the_whole_text_as_header(self):
        self.assertEqual(plan_format.header_line("Journal: /x/plan-01.md\n", "Journal"),
                         "/x/plan-01.md")


class TestEnsureHeaderLine(unittest.TestCase):
    def test_a_line_already_in_the_header_is_left_alone(self):
        text = "# Plan\nJournal: /x/plan-01.md\n\n## Goal\n"
        self.assertEqual(plan_format.ensure_header_line(text, "Journal", "/y/plan-02.md"), text)

    def test_an_empty_line_already_in_the_header_is_left_alone(self):
        text = "# Plan\nJournal:\n\n## Goal\n"
        self.assertEqual(plan_format.ensure_header_line(text, "Journal", "/y/plan-02.md"), text)

    def test_the_line_goes_under_the_title_when_no_anchor_is_listed(self):
        text = "# Plan\n\n## Goal\n"
        self.assertEqual(plan_format.ensure_header_line(text, "Project", "repo"),
                         "# Plan\nProject: repo\n\n## Goal\n")

    def test_the_line_goes_after_a_listed_anchor(self):
        text = "# Plan\nProject: repo\n\n## Goal\n"
        new_text = plan_format.ensure_header_line(text, "Journal", "/x/plan-01.md", after=("Project",))
        self.assertEqual(new_text, "# Plan\nProject: repo\nJournal: /x/plan-01.md\n\n## Goal\n")

    def test_the_line_goes_after_the_last_of_several_anchors(self):
        text = "Project: repo\nJournal: /x/plan-01.md\n# Plan\n\n## Goal\n"
        new_text = plan_format.ensure_header_line(text, "Base", "abc", after=("Journal", "Project"))
        self.assertTrue(new_text.startswith("Project: repo\nJournal: /x/plan-01.md\nBase: abc\n# Plan"))

    def test_missing_anchors_fall_back_to_the_title(self):
        text = "# Plan\n\n## Goal\n"
        new_text = plan_format.ensure_header_line(text, "Journal", "/x/plan-01.md", after=("Project",))
        self.assertEqual(new_text, "# Plan\nJournal: /x/plan-01.md\n\n## Goal\n")

    def test_no_title_puts_the_line_at_the_top(self):
        text = "## Goal\nDo it.\n"
        self.assertEqual(plan_format.ensure_header_line(text, "Project", "repo"),
                         "Project: repo\n## Goal\nDo it.\n")

    def test_a_title_inside_a_fence_is_not_the_title(self):
        text = "```md\n# Quoted\n```\n\n## Goal\n"
        new_text = plan_format.ensure_header_line(text, "Project", "repo")
        self.assertTrue(new_text.startswith("Project: repo\n```md\n"))

    def test_lines_in_a_fence_neither_count_as_present_nor_anchor_the_insert(self):
        text = plan_with_fenced_header_lines("Project: repo\n")
        new_text = plan_format.ensure_header_line(text, "Journal", "/x/plan-01.md", after=("Project",))
        self.assertTrue(new_text.startswith("# Plan\nProject: repo\nJournal: /x/plan-01.md\n"))
        self.assertIn(FENCED_LINES, new_text)
        self.assertEqual(new_text.count("Journal:"), 2)

    def test_a_header_with_no_trailing_newline_still_gets_a_line_of_its_own(self):
        self.assertEqual(plan_format.ensure_header_line("# Plan", "Project", "repo"),
                         "# Plan\nProject: repo\n")


class TestProjectName(unittest.TestCase):
    def test_the_first_token_of_the_project_line_is_the_name(self):
        self.assertEqual(plan_format.project_name("# T\n\nProject: my-repo\n"), "my-repo")

    def test_an_annotation_after_the_name_is_ignored(self):
        text = "# T\n\nProject: my-repo (branch feature/x)\n"
        self.assertEqual(plan_format.project_name(text), "my-repo")

    def test_a_project_line_quoted_in_a_fence_is_not_the_plans_own(self):
        text = "# T\n\n## Decisions\n\n```text\nProject: quoted\n```\n"
        self.assertIsNone(plan_format.project_name(text))
        self.assertEqual(plan_format.project_name("# T\nProject: real\n\n## D\n\n```\nProject: quoted\n```\n"), "real")

    def test_no_project_line_or_an_empty_one_is_none(self):
        self.assertIsNone(plan_format.project_name("# T\n\n## Goal\n"))
        self.assertIsNone(plan_format.project_name("# T\n\nProject:\n\n## Goal\n"))


class TestBase(unittest.TestCase):
    def test_read_base_missing_is_none(self):
        self.assertIsNone(plan_format.read_base("# Plan\n\n## Goal\n"))

    def test_read_base_present(self):
        self.assertEqual(plan_format.read_base("Base: abc123\n\n# Plan\n\n## Goal\n"), "abc123")

    def test_write_base_inserts_after_journal(self):
        text = "Project: repo\nJournal: /x/plan-01.md\n\n# Plan\n\n## Goal\n"
        new_text = plan_format.write_base(text, "abc123")
        self.assertIn("Journal: /x/plan-01.md\nBase: abc123\n", new_text)
        self.assertEqual(plan_format.read_base(new_text), "abc123")

    def test_write_base_inserts_after_project_without_a_journal_line(self):
        text = "Project: repo\n\n# Plan\n\n## Goal\n"
        new_text = plan_format.write_base(text, "abc123")
        self.assertIn("Project: repo\nBase: abc123\n", new_text)

    def test_write_base_inserts_after_the_title_with_no_header_lines(self):
        text = "# Plan\n\n## Goal\n"
        new_text = plan_format.write_base(text, "abc123")
        self.assertIn("# Plan\nBase: abc123\n", new_text)

    def test_write_base_updates_an_existing_line_in_place(self):
        text = "Base: old-sha\n\n# Plan\n\n## Goal\n"
        new_text = plan_format.write_base(text, "new-sha")
        self.assertEqual(plan_format.read_base(new_text), "new-sha")
        self.assertNotIn("old-sha", new_text)

    def test_a_fenced_base_line_is_neither_read_nor_updated(self):
        text = plan_with_fenced_header_lines("Journal: /x/plan-01.md\n")
        self.assertIsNone(plan_format.read_base(text))
        new_text = plan_format.write_base(text, "abc123")
        self.assertEqual(plan_format.read_base(new_text), "abc123")
        self.assertTrue(new_text.startswith("# Plan\nJournal: /x/plan-01.md\nBase: abc123\n"))
        self.assertIn(FENCED_LINES, new_text)


class TestWriteStatusComplete(unittest.TestCase):
    def test_inserts_after_base_when_present(self):
        text = "Project: repo\nJournal: /x/plan-01.md\nBase: abc123\n\n# Plan\n\n## Goal\n"
        new_text = plan_format.write_status_complete(text)
        self.assertIn("Base: abc123\nStatus: complete\n", new_text)
        self.assertTrue(plan_format.is_complete(new_text))

    def test_inserts_after_journal_without_a_base_line(self):
        text = "Project: repo\nJournal: /x/plan-01.md\n\n# Plan\n\n## Goal\n"
        new_text = plan_format.write_status_complete(text)
        self.assertIn("Journal: /x/plan-01.md\nStatus: complete\n", new_text)

    def test_inserts_after_the_title_with_no_header_lines(self):
        text = "# Plan\n\n## Goal\n"
        new_text = plan_format.write_status_complete(text)
        self.assertIn("# Plan\nStatus: complete\n", new_text)
        self.assertTrue(plan_format.is_complete(new_text))

    def test_updates_an_existing_status_line_in_place(self):
        text = "Status: in progress\n\n# Plan\n\n## Goal\n"
        new_text = plan_format.write_status_complete(text)
        self.assertTrue(plan_format.is_complete(new_text))
        self.assertNotIn("in progress", new_text)

    def test_updates_an_existing_bold_status_line_in_place(self):
        text = "**Status:** in progress\n\n# Plan\n\n## Goal\n"
        new_text = plan_format.write_status_complete(text)
        self.assertIn("Status: complete", new_text)
        self.assertNotIn("in progress", new_text)

    def test_a_fenced_status_line_neither_completes_the_plan_nor_is_rewritten(self):
        text = plan_with_fenced_header_lines("Base: abc123\n").replace("Status: complete\n", "Status: open\n")
        self.assertFalse(plan_format.is_complete(text))
        new_text = plan_format.write_status_complete(text)
        self.assertTrue(plan_format.is_complete(new_text))
        self.assertTrue(new_text.startswith("# Plan\nBase: abc123\nStatus: complete\n"))
        self.assertIn("Status: open\n", new_text)


IRREVERSIBLE_PLAN = """\
# Some plan

## Steps

### 1. Add the column

- Change: add it.

### 2. Drop the old column

- Change: drop it.
- Irreversible: drops the legacy_name column
- Tests: prove it.

### 3. Quote an example

- Change: show the format.

```
- Irreversible: only an example
```

## Verification

- Irreversible: not under a step
"""


class TestIrreversibleSteps(unittest.TestCase):
    def test_reads_the_number_and_text_of_each_marked_step(self):
        self.assertEqual(plan_format.irreversible_steps(IRREVERSIBLE_PLAN),
                         [(2, "drops the legacy_name column")])

    def test_an_irreversible_line_inside_fenced_code_is_ignored(self):
        text = IRREVERSIBLE_PLAN.replace("- Irreversible: drops the legacy_name column\n", "")
        self.assertEqual(plan_format.irreversible_steps(text), [])

    def test_a_plan_with_no_steps_section_has_none(self):
        self.assertEqual(plan_format.irreversible_steps("# Plan\n\n## Goal\n\n- Irreversible: x\n"), [])

    def test_an_irreversible_line_with_no_text_is_not_a_mark(self):
        text = IRREVERSIBLE_PLAN.replace("drops the legacy_name column", "")
        self.assertEqual(plan_format.irreversible_steps(text), [])

    def test_every_marked_step_is_listed_in_order(self):
        text = IRREVERSIBLE_PLAN.replace("- Change: add it.\n", "- Change: add it.\n- Irreversible: sends a mail\n")
        self.assertEqual(plan_format.irreversible_steps(text),
                         [(1, "sends a mail"), (2, "drops the legacy_name column")])


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Every agent declares its tool rules in the V2 permission map, the final reviewer's git
access, and the specifier and planner's Refine checks question."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENTS = ROOT / "agents"
FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---", re.S)
V1_PERMISSIONS = re.compile(r"^permissions:", re.M)
GIT_COMMANDS = ("git diff*", "git log*", "git show*", "git status*", "git rev-parse*")


def read(path):
    return path.read_text(encoding="utf-8")


def front_matter(path):
    match = FRONT_MATTER.match(read(path))
    if match is None:
        raise AssertionError(f"{path.relative_to(ROOT)} has no front matter")
    return match.group(1)


def permission_block(path):
    lines = front_matter(path).splitlines()
    for index, line in enumerate(lines):
        if line != "permission:":
            continue
        block = []
        for following in lines[index + 1:]:
            if following and not following.startswith(" "):
                break
            block.append(following)
        return block
    return None


def permission_map(path):
    block = permission_block(path)
    if block is None:
        return None
    rules = {}
    key = None
    for line in block:
        if not line.strip():
            continue
        if line.startswith("  ") and not line.startswith("    "):
            key, _, value = line.strip().partition(":")
            rules[key] = value.strip() if value.strip() else {}
            continue
        pattern, _, effect = line.strip().partition(":")
        rules[key][pattern.strip().strip('"')] = effect.strip()
    return rules


class AgentPermissionTestCase(unittest.TestCase):
    """REQ-9 — every agent declares its tool rules under the V2 permission map."""

    def test_every_agent_declares_its_tool_rules_under_the_permission_map(self):
        v1 = []
        without = []
        for path in sorted(AGENTS.glob("*.md")):
            text = front_matter(path)
            if V1_PERMISSIONS.search(text):
                v1.append(path.name)
            if permission_block(path) is None:
                without.append(path.name)
        self.assertEqual([], v1, "agents still using the V1 permissions list: " + ", ".join(v1))
        # plan.md declares no rules: the plugin layers the plan agent's permissions at runtime.
        self.assertEqual(["plan.md"], without, "agents with no permission map: " + ", ".join(without))


class FinalReviewerShellTestCase(unittest.TestCase):
    """REQ-10 — the final reviewer runs exactly the five git commands it reviews with."""

    def test_the_final_reviewer_denies_every_shell_command_but_the_five_git_commands(self):
        bash = permission_map(AGENTS / "hoko-final-reviewer.md")["bash"]
        expected = {"*": "deny", **{command: "allow" for command in GIT_COMMANDS}}
        self.assertEqual(expected, bash)


class RefineChecksTestCase(unittest.TestCase):
    """REQ-11 and REQ-12 — Refine asks the CRAP/Mutation/Skip question and records its answer."""

    def test_SPEC_LOCAL_REQ_11_the_specifier_asks_one_multi_select_crap_mutation_or_skip_question(self):
        text = read(AGENTS / "hoko-specifier.md")
        self.assertIn("multi-select", text)
        for option in ("- `CRAP`", "- `Mutation`", "- `Skip`"):
            self.assertIn(option, text)
        self.assertIn('"multiple": true', text)

    def test_SPEC_LOCAL_REQ_12_the_specifier_records_the_selection_in_the_scope_checks_list(self):
        text = read(AGENTS / "hoko-specifier.md")
        self.assertIn("`checks`", text)
        self.assertIn('"checks": ["crap", "mutation"]', text)
        self.assertIn("`[]` for `Skip`", text)


class PlannerQaLineTestCase(unittest.TestCase):
    """REQ-14 — the planner writes the plan's QA: line from the scope's checks list."""

    def test_SPEC_LOCAL_REQ_14_the_planner_takes_the_qa_line_from_the_scopes_checks(self):
        text = read(AGENTS / "hoko-planner.md")
        self.assertIn("`scope.json`'s `checks` list", text)
        self.assertIn("`QA: none`", text)


class QaCheckScopeTestCase(unittest.TestCase):
    """REQ-16 — the QA agent and its skill take the changed-file list as the scope of both checks."""

    def test_SPEC_LOCAL_REQ_16_the_qa_agent_and_skill_scope_both_checks_to_the_changed_files(self):
        for path in (AGENTS / "hoko-quality-assurance.md",
                     ROOT / "skills" / "hoko-quality-assurance" / "SKILL.md"):
            text = " ".join(read(path).split())
            where = path.relative_to(ROOT).as_posix()
            self.assertIn("that list and nothing wider is the scope of both the CRAP index and "
                          "mutation testing", text, where)
            self.assertIn("When the list is empty, report both as absent rather than widening them.",
                          text, where)


class ReadExclusionTestCase(unittest.TestCase):
    """REQ-22 to REQ-25 — one read-exclusion list, and the repository before the web."""

    EXCLUDED = (
        "node_modules", "vendor", "dist", "build", ".next", "target", "coverage",
        ".git", "__pycache__", ".venv", ".ai/plans", ".ai/analytics",
    )
    ECOSYSTEM = (".gradle", ".bundle", ".terraform", "_build", "deps", "bin", "obj")

    def setUp(self):
        self.text = " ".join(read(ROOT / "instructions" / "read-exclusion.md").split())

    def test_SPEC_LOCAL_REQ_22_the_instructions_name_every_excluded_folder(self):
        for folder in self.EXCLUDED + self.ECOSYSTEM:
            self.assertIn(f"`{folder}`", self.text, folder)
        self.assertIn("the journal tree `journalPath` (`HOKO_JOURNAL_PATH`) resolves to", self.text)

    def test_SPEC_LOCAL_REQ_23_an_excluded_folder_is_reached_only_by_a_path_the_caller_names(self):
        self.assertIn("A file in an excluded folder is reached only by a path the caller names.",
                      self.text)
        self.assertIn("never reached by a recursive `grep`, `glob` or `find`", self.text)

    def test_SPEC_LOCAL_REQ_24_the_web_is_reached_only_when_no_repository_file_answers(self):
        self.assertIn("A stage reaches the web only when no file in this repository answers the "
                      "question.", self.text)

    def test_SPEC_LOCAL_REQ_25_a_web_answer_names_the_repository_file_it_ruled_out_first(self):
        self.assertIn("it names the repository file it ruled out first", self.text)


class ReadmeLayoutTestCase(unittest.TestCase):
    """The README's instructions section names every standing rules file."""

    def test_the_readme_lists_the_read_exclusion_instruction_file(self):
        self.assertIn("read-exclusion.md", read(ROOT / "README.md"))


if __name__ == "__main__":
    unittest.main(verbosity=2)

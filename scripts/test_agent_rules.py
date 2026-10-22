#!/usr/bin/env python3
"""Every agent declares its tool rules in the V2 permission map, and the final reviewer's git access."""

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


if __name__ == "__main__":
    unittest.main(verbosity=2)

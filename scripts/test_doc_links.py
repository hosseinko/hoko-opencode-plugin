#!/usr/bin/env python3
"""Every hoko-* name and relative link the docs use resolves, and no Claude path survives."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC_DIRS = ("agents", "commands", "skills", "docs")
DOC_FILES = ("README.md", "MIGRATION-V2.md")

FENCE = re.compile(r"```.*?```", re.S)
INLINE_CODE = re.compile(r"`[^`\n]*`")
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
NAME = re.compile(r"`(hoko-[a-z0-9-]+)`")
SCRIPT = re.compile(r"(?<![\w.-])([a-z][a-z0-9_-]*\.py)\b")
COMMENT = re.compile(r"<!--.*?-->", re.S)
FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---", re.S)
FRONT_MATTER_NAME = re.compile(r"^name:\s*(\S+)\s*$", re.M)

CLAUDE_ONLY = ("CLAUDE_PLUGIN_ROOT", "SendMessage", "AskUserQuestion", "ExitPlanMode", "~/.claude")

RETIRED_ROLES = ("step-gate", "deep reviewer")


def directory_docs():
    for base in DOC_DIRS:
        yield from sorted((ROOT / base).rglob("*.md"))


def markdown_files():
    yield from directory_docs()
    for name in DOC_FILES:
        yield ROOT / name


def read(path):
    return path.read_text(encoding="utf-8")


def without_code(text):
    text = FENCE.sub("", text)
    return INLINE_CODE.sub("", text)


def link_targets(path):
    return LINK.findall(without_code(read(path)))


def named(path):
    return NAME.findall(read(path))


def scripts_in(path):
    return SCRIPT.findall(read(path))


def script_exists(name):
    return any(ROOT.glob(f"skills/**/scripts/{name}")) or (ROOT / "scripts" / name).is_file()


def resolves(name):
    return ((ROOT / "agents" / f"{name}.md").is_file()
            or (ROOT / "skills" / name / "SKILL.md").is_file()
            or (ROOT / "scripts" / f"{name}.py").is_file()
            or (ROOT / "commands" / "hoko" / f"{name.removeprefix('hoko-')}.md").is_file())


class DocLinksTestCase(unittest.TestCase):
    def test_every_named_relative_link_resolves_to_an_existing_file(self):
        broken = []
        for path in markdown_files():
            for target in link_targets(path):
                if "://" in target or target.startswith("mailto:") or target.startswith("#"):
                    continue
                file_part = target.split("#", 1)[0]
                if not file_part:
                    continue
                if not (path.parent / file_part).resolve().is_file():
                    broken.append(f"{path.relative_to(ROOT)} -> {target}")
        self.assertEqual([], broken, "broken markdown links:\n" + "\n".join(broken))

    def test_the_readme_links_the_hoko_json_example(self):
        self.assertIn("hoko.json.example", link_targets(ROOT / "README.md"))
        self.assertTrue((ROOT / "hoko.json.example").is_file())

    def test_every_named_agent_skill_and_script_resolves_to_a_file_in_this_repo(self):
        dangling = []
        for path in markdown_files():
            for name in named(path):
                if not resolves(name):
                    dangling.append(f"{path.relative_to(ROOT)} -> {name}")
            for name in scripts_in(path):
                if not script_exists(name):
                    dangling.append(f"{path.relative_to(ROOT)} -> scripts/{name}")
        self.assertEqual([], dangling, "dangling names:\n" + "\n".join(dangling))

    def test_no_claude_only_token_survives_outside_a_comment(self):
        found = []
        for path in markdown_files():
            text = COMMENT.sub("", read(path))
            for token in CLAUDE_ONLY:
                if token in text:
                    found.append(f"{path.relative_to(ROOT)} -> {token}")
        self.assertEqual([], found, "Claude-only tokens:\n" + "\n".join(found))

    def test_no_document_names_a_retired_role_in_prose(self):
        found = []
        for path in directory_docs():
            prose = without_code(read(path)).lower()
            for role in RETIRED_ROLES:
                if role in prose:
                    found.append(f"{path.relative_to(ROOT)} -> {role}")
        self.assertEqual([], found, "retired roles in prose:\n" + "\n".join(found))


class PlanAgentPromptTestCase(unittest.TestCase):
    """R1 — the plan agent describes the loop the engine runs, not the one it replaced."""

    def setUp(self):
        self.prompt = read(ROOT / "agents" / "plan.md")

    def test_the_plan_agent_describes_one_executor_per_step_then_quality_assurance_then_one_final_reviewer(self):
        for name in ("`plan-file.py file`", "`plan-progress.py init`", "`hoko-plan-executor`",
                     "`step-commit.py`", "`hoko-quality-assurance`", "`hoko-final-reviewer`",
                     "`<Base>..HEAD`", "pull request"):
            self.assertIn(name, self.prompt)


class TaskPipelineTestCase(unittest.TestCase):
    """R24 — /hoko/task runs the whole pipeline and writes no implementation code."""

    def setUp(self):
        self.command = read(ROOT / "commands" / "hoko" / "task.md")
        self.skill = read(ROOT / "skills" / "hoko-task" / "SKILL.md")
        self.flat = " ".join(self.skill.split())

    def test_the_task_command_hands_the_run_to_the_conductor_on_the_build_agent(self):
        self.assertIn("agent: build", self.command)
        self.assertIn("`hoko-task` skill", self.command)

    def test_when_hoko_task_is_invoked_the_conductor_runs_the_pipeline_from_start(self):
        self.assertIn('task.py" start', self.flat)
        self.assertIn('task.py" next', self.flat)
        self.assertIn("plan-progress.py\" start", self.flat)

    def test_when_hoko_task_is_invoked_the_conductor_reaches_finish_or_stop(self):
        self.assertIn('task.py" finish', self.flat)
        self.assertIn('task.py" stop', self.flat)
        self.assertIn("step-commit.py", self.flat)

    def test_the_conductor_dispatches_every_stage_agent_the_state_machine_names(self):
        import task

        agents = set(task.AGENTS.values()) | {"hoko-plan-executor", "hoko-researcher"}
        missing = sorted(agent for agent in agents if f"`{agent}`" not in self.flat)
        self.assertEqual([], missing, "stages the conductor cannot dispatch: " + ", ".join(missing))

    def test_the_conductor_launches_stages_with_the_subagent_tool_and_records_the_session(self):
        self.assertIn("`subagent` tool", self.flat)
        self.assertIn("--agent-session", self.flat)
        self.assertIn("--resume-failed", self.flat)

    def test_the_conductor_asks_the_user_with_the_question_tool(self):
        self.assertIn("`question` tool", self.flat)

    def test_the_conductor_writes_no_implementation_code(self):
        self.assertIn("You write no implementation code", self.flat)
        self.assertIn("The conductor does not modify or open a source or spec file", self.flat)

    def test_the_conductor_bans_writes_only_and_keeps_its_preflight_interpreter_call_legal(self):
        self.assertIn("`python3 -c` that writes one", self.flat)
        self.assertIn("python3 -c 'import time; print(int(time.time() * 1000))'", self.flat)


class SkillFrontMatterTestCase(unittest.TestCase):
    """Every skill names itself after the directory opencode keys it by."""

    def test_each_skill_front_matter_name_matches_its_directory(self):
        mismatched = []
        for path in sorted((ROOT / "skills").glob("*/SKILL.md")):
            match = FRONT_MATTER.match(read(path))
            self.assertIsNotNone(match, f"{path.relative_to(ROOT)} has no front matter")
            name = FRONT_MATTER_NAME.search(match.group(1))
            self.assertIsNotNone(name, f"{path.relative_to(ROOT)} declares no name")
            if name.group(1) != path.parent.name:
                mismatched.append(f"{path.parent.name} -> {name.group(1)}")
        self.assertEqual([], mismatched, "skill names that do not match their directory:\n" + "\n".join(mismatched))


if __name__ == "__main__":
    unittest.main(verbosity=2)

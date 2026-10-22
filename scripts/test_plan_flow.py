#!/usr/bin/env python3
"""Tests for plan-flow.py — run the grill subcommand against a scratch tree."""

import os
import subprocess
import sys
import tempfile
import unittest

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plan-flow.py")


class PlanFlowTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.env = dict(os.environ)
        self.env["TMPDIR"] = self.tmpdir.name

    def grill(self, *args, cwd=None):
        return subprocess.run(
            [sys.executable, SCRIPT, "grill", *args],
            capture_output=True, text=True, env=self.env, cwd=cwd,
        )

    def repo(self, agents_md=None):
        root = os.path.join(self.tmpdir.name, "repo")
        os.makedirs(os.path.join(root, ".git"), exist_ok=True)
        if agents_md is not None:
            with open(os.path.join(root, "AGENTS.md"), "w", encoding="utf-8") as f:
                f.write(agents_md)
        return root


class TestGrillCommand(PlanFlowTestCase):
    def test_grill_prints_the_protocol(self):
        proc = self.grill()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(proc.stdout.startswith("You are now in plan mode."))

    def test_grill_fills_in_the_runtime_placeholders(self):
        proc = self.grill()
        self.assertEqual(proc.returncode, 0)
        self.assertNotRegex(proc.stdout, r"__[A-Z_]+__")

    def test_grill_names_the_scripts_under_hoko_root(self):
        proc = self.grill()
        self.assertIn("${HOKO_ROOT}/scripts/plan-lint.py", proc.stdout)
        self.assertIn("${HOKO_ROOT}/scripts/in-service.py", proc.stdout)
        self.assertIn("${HOKO_ROOT}/scripts/commands.py", proc.stdout)

    def test_grill_reads_the_conventions_of_the_named_root(self):
        root = self.repo("Run the suite with `pytest`.\n")
        proc = self.grill("--root", root)
        self.assertIn("The root `AGENTS.md` records how the suite runs.", proc.stdout)

    def test_grill_names_the_project_of_the_named_root(self):
        proc = self.grill("--root", self.repo())
        self.assertIn("`Project: repo`", proc.stdout)

    def test_grill_without_a_subcommand_says_how_to_call_it(self):
        proc = subprocess.run(
            [sys.executable, SCRIPT], capture_output=True, text=True, env=self.env)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("usage: plan-flow.py grill", proc.stderr)


class TestConventionsNote(PlanFlowTestCase):
    """What the planner is told it may take on trust."""

    def test_no_agents_md_says_absent(self):
        self.assertIn("**The repository root has no `AGENTS.md`.**",
                      self.grill("--root", self.repo()).stdout)

    def test_agents_md_without_a_command_says_silent(self):
        root = self.repo("# Project\n\nA service that geocodes.\n")
        self.assertIn("**The root `AGENTS.md` does not record how the suite runs.**",
                      self.grill("--root", root).stdout)

    def test_agents_md_naming_only_exec_in_service_is_silent(self):
        root = self.repo("## Tests\n\n`bin/exec-in-service phpfpm vendor/bin/phpunit`\n")
        self.assertIn("**The root `AGENTS.md` does not record how the suite runs.**",
                      self.grill("--root", root).stdout)

    def test_agents_md_naming_the_in_service_runner_is_trusted(self):
        root = self.repo(
            "## Tests\n\n"
            "`python3 scripts/in-service.py --root . --service phpfpm -- vendor/bin/phpunit`\n"
        )
        self.assertIn("**The root `AGENTS.md` records how the suite runs.**",
                      self.grill("--root", root).stdout)

    def test_agents_md_naming_docker_compose_dash_f_exec_is_trusted(self):
        root = self.repo(
            "## Tests\n\n"
            "`docker compose -f docker-compose.debug.yml exec -T phpfpm vendor/bin/phpunit`\n"
        )
        self.assertIn("**The root `AGENTS.md` records how the suite runs.**",
                      self.grill("--root", root).stdout)

    def assertNoNote(self, text):
        for marker in ("**The repository root has no",
                       "**The root `AGENTS.md` does not record",
                       "**The root `AGENTS.md` records"):
            self.assertNotIn(marker, text)

    def test_outside_a_repository_says_nothing(self):
        self.assertNoNote(self.grill("--root", self.tmpdir.name).stdout)

    def test_a_subdirectory_finds_the_root(self):
        root = self.repo("run: `pytest -q`\n")
        nested = os.path.join(root, "src", "deep")
        os.makedirs(nested, exist_ok=True)
        self.assertIn("**The root `AGENTS.md` records how the suite runs.**",
                      self.grill("--root", nested).stdout)


class TestProtocolContent(PlanFlowTestCase):
    def grill_text(self):
        proc = self.grill()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout

    def test_the_protocol_carries_no_claude_only_tokens(self):
        text = self.grill_text()
        for token in ("ExitPlanMode", "AskUserQuestion", "CLAUDE.md", "~/.claude",
                      "hoko:", "${CLAUDE_PLUGIN_ROOT}"):
            self.assertNotIn(token, text)

    def test_the_protocol_asks_with_the_opencode_question_tool(self):
        self.assertIn("The `question` tool when the answer is a choice", self.grill_text())

    def test_the_protocol_states_it_adds_to_opencodes_plan_mode_phases(self):
        text = self.grill_text()
        self.assertIn("adds to opencode's own plan-mode phases", text)
        self.assertIn("rather than replacing them", text)

    def test_the_protocol_still_carries_the_core_planning_rules(self):
        text = self.grill_text()
        self.assertIn("If / Then", text)
        self.assertIn("hoko-research", text)
        self.assertIn("plan-lint.py", text)
        for heading in ("## Goal", "## Requirements", "## Steps"):
            self.assertIn(heading, text)

    def test_the_protocol_generates_progress_rather_than_asking_for_it(self):
        text = " ".join(self.grill_text().split())
        self.assertIn("`## Progress` is not part of what you write", text)
        self.assertIn("the approval step generates it from the `### <N>.` headings", text)

    def test_the_step_template_carries_no_files_line(self):
        self.assertNotIn("- Files:", self.grill_text())

    def test_the_step_template_carries_the_irreversible_line(self):
        text = " ".join(self.grill_text().split())
        self.assertIn("- Irreversible: <what cannot be undone", text)

    def test_the_protocol_names_the_ticket_header_line_without_jira(self):
        text = self.grill_text()
        self.assertIn("Ticket: <KEY>", text)
        self.assertNotIn("Atlassian", text)
        self.assertNotIn("Jira", text)

    def test_the_protocol_records_the_qa_checks_as_a_header_line(self):
        text = self.grill_text()
        for line in ("`QA: crap, mutation`", "`QA: crap`", "`QA: mutation`", "`QA: none`"):
            self.assertIn(line, text)

    def test_the_plan_is_written_under_the_repository_plans_directory(self):
        text = self.grill_text()
        self.assertIn('${HOKO_PLANS_DIR:-.ai/plans}', text)
        self.assertIn("hoko_execute", text)


class TestSpecsSetting(PlanFlowTestCase):
    """Whether the grilling protocol offers `hoko-feature-specs`, per the `specs` setting."""

    def test_default_lacks_the_feature_specs_offer(self):
        self.env["HOKO_SPECS"] = "0"
        self.assertNotIn("hoko-feature-specs", self.grill().stdout)

    def test_specs_enabled_contains_the_feature_specs_offer(self):
        self.env["HOKO_SPECS"] = "1"
        self.assertIn("hoko-feature-specs", self.grill().stdout)


class TestQaChecksQuestion(PlanFlowTestCase):
    """The always-asked CRAP / mutation question."""

    def qa_step(self):
        text = self.grill().stdout
        return text.split("**3. Ask which QA checks")[1].split("**4. Write the plan")[0]

    def test_the_protocol_asks_which_of_crap_and_mutation_the_run_gets(self):
        self.assertIn("multi-select", self.qa_step())
        self.assertIn("- `CRAP`", self.qa_step())
        self.assertIn("- `Mutation`", self.qa_step())
        self.assertIn("never skip it", self.qa_step())

    def test_both_checks_are_pre_selected_by_default(self):
        self.env["HOKO_CRAP"] = "1"
        self.env["HOKO_MUTATION"] = "1"
        self.assertEqual(self.grill().stdout.count("pre-selected, recommended"), 2)

    def test_a_check_the_settings_turn_off_is_not_pre_selected(self):
        self.env["HOKO_CRAP"] = "1"
        self.env["HOKO_MUTATION"] = "0"
        text = self.grill().stdout
        self.assertEqual(text.count("pre-selected, recommended"), 1)
        self.assertIn("not pre-selected: the settings turn it off", text)

    def test_the_planner_checks_each_check_has_a_tool_and_names_a_missing_one(self):
        step = self.qa_step()
        self.assertIn("has a tool each check can run on", step)
        self.assertIn("${HOKO_ROOT}/scripts/commands.py --root", step)
        self.assertIn("complexity", step)
        self.assertIn("name\nthe missing tool and its install command", step)

    def test_installing_a_missing_tool_needs_a_yes_recorded_as_a_plan_step(self):
        step = self.qa_step()
        self.assertIn("needs the user's explicit yes", step)
        self.assertIn("a step that installs\nit", step)
        self.assertIn("install nothing", step)

    def test_in_docker_the_install_step_targets_the_image_never_the_host(self):
        step = self.qa_step()
        self.assertIn("When the project runs in Docker", step)
        self.assertIn("dev or\ntest image, never on the host", step)


class TestMalformedInput(PlanFlowTestCase):
    def test_garbage_arguments_fail_loudly(self):
        proc = subprocess.run(
            [sys.executable, SCRIPT, "grill", "--root"], capture_output=True, text=True,
            env=self.env)
        self.assertNotEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()

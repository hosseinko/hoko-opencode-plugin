#!/usr/bin/env python3
"""Tests for settings.py — precedence, defaults, coercion and the command-line form."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import settings

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = PLUGIN_ROOT / "scripts" / "settings.py"


def env_file(directory, lines):
    (Path(directory) / "hoko.env").write_text("\n".join(lines) + "\n", encoding="utf-8")


def plugin_copy(tmp, config, env_lines=None):
    """A throwaway copy of the plugin, so the real hoko.json is never read."""
    plugin = Path(tmp) / "plugin"
    (plugin / "scripts").mkdir(parents=True)
    (plugin / "scripts" / "settings.py").write_text(
        SCRIPT.read_text(encoding="utf-8"), encoding="utf-8"
    )
    if config is not None:
        (plugin / "hoko.json").write_text(json.dumps(config), encoding="utf-8")
    if env_lines is not None:
        env_file(plugin, env_lines)
    return plugin


def home_copy(tmp, config, env_lines=None):
    home = Path(tmp) / "home"
    config_dir = home / ".config" / "opencode"
    config_dir.mkdir(parents=True, exist_ok=True)
    if config is not None:
        (config_dir / "hoko.json").write_text(json.dumps(config), encoding="utf-8")
    if env_lines is not None:
        env_file(config_dir, env_lines)
    return home


def read(plugin, key, home=None, env=None):
    environment = dict(os.environ)
    environment["HOME"] = str(home or Path(plugin).parent / "empty-home")
    for name in list(environment):
        if name.startswith("HOKO_"):
            del environment[name]
    environment.update(env or {})
    proc = subprocess.run(
        [sys.executable, str(Path(plugin) / "scripts" / "settings.py"), key],
        capture_output=True,
        text=True,
        env=environment,
    )
    return proc


class KeyCase(unittest.TestCase):
    """Each read gets a fresh throwaway plugin, so one case cannot see another's config."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def value(self, key, config=None, env=None, repo_env=None):
        root = tempfile.mkdtemp(dir=self.tmp.name)
        return read(plugin_copy(root, config, repo_env), key, env=env)

    def layered(self, key, plugin_config=None, home_config=None, env=None,
                repo_env=None, home_env=None):
        root = tempfile.mkdtemp(dir=self.tmp.name)
        home = home_copy(tempfile.mkdtemp(dir=self.tmp.name), home_config, home_env)
        return read(plugin_copy(root, plugin_config, repo_env), key, home=home, env=env)


class TestSettings(KeyCase):
    def test_defaults_apply_without_any_config(self):
        self.assertEqual(self.value("coverageMin").stdout.strip(), "85")
        self.assertEqual(self.value("plansDir").stdout.strip(), ".ai/plans")
        self.assertEqual(self.value("commitAuto").stdout.strip(), "false")
        self.assertEqual(self.value("journalPath").stdout.strip(), "")
        self.assertEqual(self.value("finalReview").stdout.strip(), "")
        self.assertEqual(self.value("specs").stdout.strip(), "false")
        self.assertEqual(self.value("loopGuard").stdout.strip(), "true")

    def test_r1_the_settings_resolve_plugin_config_then_home_config_then_the_environment(self):
        plugin = {"loopLimit": 4}
        home = {"loopLimit": 6}
        self.assertEqual(self.layered("loopLimit", plugin).stdout.strip(), "4")
        self.assertEqual(self.layered("loopLimit", plugin, home).stdout.strip(), "6")
        self.assertEqual(
            self.layered("loopLimit", plugin, home, {"HOKO_LOOP_LIMIT": "8"}).stdout.strip(),
            "8",
        )

    def test_r1_an_environment_override_is_coerced_to_the_settings_own_type(self):
        self.assertEqual(self.value("events", env={"HOKO_EVENTS": "off"}).stdout.strip(), "false")
        self.assertEqual(self.value("crapMax", env={"HOKO_CRAP_MAX": "45"}).stdout.strip(), "45")
        self.assertEqual(
            self.value("analyticsPath", env={"HOKO_ANALYTICS_PATH": "/a"}).stdout.strip(), "/a"
        )
        pricing = self.value("pricing", env={"HOKO_PRICING": '{"m": {"input": 1}}'})
        self.assertEqual(json.loads(pricing.stdout), {"m": {"input": 1}})

    def test_plugin_config_overrides_the_default(self):
        self.assertEqual(self.value("coverageMin", {"coverageMin": 70}).stdout.strip(), "70")

    def test_environment_overrides_every_config(self):
        proc = self.layered("coverageMin", {"coverageMin": 70}, {"coverageMin": 95},
                            env={"HOKO_COVERAGE_MIN": "50"})
        self.assertEqual(proc.stdout.strip(), "50")

    def test_unknown_keys_in_config_are_ignored(self):
        config = {"nonsense": "x", "coverageMin": 70}
        self.assertEqual(self.value("coverageMin", config).stdout.strip(), "70")

    def test_unknown_key_is_refused(self):
        proc = self.value("nonsense")
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(proc.stdout.strip(), "")

    def test_malformed_config_falls_back_to_the_default(self):
        root = tempfile.mkdtemp(dir=self.tmp.name)
        plugin = plugin_copy(root, None)
        (Path(plugin) / "hoko.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(read(plugin, "coverageMin").stdout.strip(), "85")

    def test_reviewer_model_is_the_key_the_reviewer_reads(self):
        self.assertEqual(self.value("reviewerModel").stdout.strip(), "")
        self.assertEqual(self.value("reviewerModel", {"reviewerModel": "haiku"}).stdout.strip(), "haiku")

    def test_the_stale_review_model_key_is_refused(self):
        proc = self.value("reviewModel")
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(proc.stdout.strip(), "")


class TestModelKeys(KeyCase):
    """R4 — a model is a hoko.json key, read from the same file as the rest."""

    MODEL_KEYS = ("planModel", "buildModel", "executorModel", "reviewerModel",
                  "finalReview", "qaModel", "researchModel")

    def test_r4_every_model_key_reads_from_the_repository_hoko_json(self):
        for key in self.MODEL_KEYS:
            with self.subTest(key=key):
                self.assertEqual(self.value(key).stdout.strip(), "")
                proc = self.value(key, {key: "provider/model"})
                self.assertEqual(proc.stdout.strip(), "provider/model")

    def test_r4_every_model_key_reads_from_the_machine_hoko_json(self):
        for key in self.MODEL_KEYS:
            with self.subTest(key=key):
                proc = self.layered(key, home_config={key: "provider/machine"})
                self.assertEqual(proc.stdout.strip(), "provider/machine")


class TestFileLayers(KeyCase):
    """R5 — the two hoko.json files, the two hoko.env files, then the environment."""

    def test_r5_the_settings_resolve_repository_json_then_machine_json_then_repository_env_then_machine_env_then_the_environment(self):
        repo_json = {"coverageMin": 60}
        machine_json = {"coverageMin": 65}
        repo_env = ["HOKO_COVERAGE_MIN=70"]
        machine_env = ["HOKO_COVERAGE_MIN=75"]
        self.assertEqual(self.layered("coverageMin", repo_json).stdout.strip(), "60")
        self.assertEqual(self.layered("coverageMin", repo_json, machine_json).stdout.strip(), "65")
        self.assertEqual(self.layered("coverageMin", repo_json, machine_json,
                                      repo_env=repo_env).stdout.strip(), "70")
        self.assertEqual(self.layered("coverageMin", repo_json, machine_json,
                                      repo_env=repo_env, home_env=machine_env).stdout.strip(), "75")
        self.assertEqual(self.layered("coverageMin", repo_json, machine_json,
                                      env={"HOKO_COVERAGE_MIN": "80"},
                                      repo_env=repo_env, home_env=machine_env).stdout.strip(), "80")

    def test_r5_a_repository_hoko_env_line_overrides_the_machine_hoko_json(self):
        proc = self.layered("plansDir", home_config={"plansDir": "machine/plans"},
                            repo_env=["HOKO_PLANS_DIR=repo/plans"])
        self.assertEqual(proc.stdout.strip(), "repo/plans")

    def test_r5_a_machine_hoko_env_line_overrides_the_repository_one(self):
        proc = self.layered("plansDir", repo_env=["HOKO_PLANS_DIR=repo/plans"],
                            home_env=["HOKO_PLANS_DIR=machine/plans"])
        self.assertEqual(proc.stdout.strip(), "machine/plans")

    def test_an_empty_string_in_a_file_never_overrides(self):
        for home in ({"plansDir": ""}, None):
            with self.subTest(home=home):
                proc = self.layered("plansDir", {"plansDir": "docs/plans"}, home)
                self.assertEqual(proc.stdout.strip(), "docs/plans")

    def test_an_empty_hoko_env_value_never_overrides(self):
        proc = self.layered("plansDir", {"plansDir": "docs/plans"},
                            repo_env=["HOKO_PLANS_DIR="])
        self.assertEqual(proc.stdout.strip(), "docs/plans")

    def test_only_the_environment_clears_a_configured_value(self):
        proc = self.layered("plansDir", {"plansDir": "docs/plans"},
                            env={"HOKO_PLANS_DIR": ""})
        self.assertEqual(proc.stdout.strip(), ".ai/plans")

    def test_an_unknown_key_in_a_hoko_env_line_is_ignored(self):
        proc = self.layered("plansDir", repo_env=["HOKO_NONSENSE=x", "HOKO_PLANS_DIR=docs/plans"])
        self.assertEqual(proc.stdout.strip(), "docs/plans")

    def test_a_malformed_hoko_env_contributes_nothing(self):
        root = tempfile.mkdtemp(dir=self.tmp.name)
        plugin = plugin_copy(root, {"plansDir": "docs/plans"})
        (plugin / "hoko.env").write_bytes(b"\xff\xfe not utf-8")
        self.assertEqual(read(plugin, "plansDir").stdout.strip(), "docs/plans")


class TestExampleFile(unittest.TestCase):
    def test_r7_hoko_json_example_names_every_supported_key_with_its_default(self):
        example = json.loads((PLUGIN_ROOT / "hoko.json.example").read_text(encoding="utf-8"))
        self.assertEqual(example, settings.DEFAULTS)


class TestAnalyticsPath(KeyCase):
    def test_r1_analytics_path_prints_empty_with_no_source(self):
        proc = self.value("analyticsPath")
        self.assertEqual((proc.returncode, proc.stdout), (0, "\n"))

    def test_analytics_path_reads_the_plugin_config(self):
        self.assertEqual(
            self.value("analyticsPath", {"analyticsPath": "/from/config"}).stdout.strip(),
            "/from/config",
        )

    def test_analytics_path_reads_the_environment(self):
        proc = self.value("analyticsPath", env={"HOKO_ANALYTICS_PATH": "/from/env"})
        self.assertEqual(proc.stdout.strip(), "/from/env")


class TestEvents(KeyCase):
    def test_events_defaults_to_on(self):
        self.assertEqual(self.value("events").stdout.strip(), "true")

    def test_events_takes_a_config_override(self):
        self.assertEqual(self.value("events", {"events": False}).stdout.strip(), "false")

    def test_events_coerces_an_environment_override(self):
        self.assertEqual(self.value("events", env={"HOKO_EVENTS": "off"}).stdout.strip(), "false")
        self.assertEqual(self.value("events", env={"HOKO_EVENTS": "YES"}).stdout.strip(), "true")


class TestEventsDir(KeyCase):
    def test_events_dir_defaults_to_the_ai_runs_folder(self):
        self.assertEqual(self.value("eventsDir").stdout.strip(), ".ai/runs")

    def test_events_dir_takes_a_config_override(self):
        self.assertEqual(self.value("eventsDir", {"eventsDir": ".x/runs"}).stdout.strip(), ".x/runs")

    def test_events_dir_takes_the_environment_override(self):
        proc = self.value("eventsDir", env={"HOKO_EVENTS_DIR": "/var/hoko/events"})
        self.assertEqual(proc.stdout.strip(), "/var/hoko/events")


class TestLoopLimit(KeyCase):
    def test_r1_loop_limit_prints_3_when_no_source_sets_it(self):
        proc = self.value("loopLimit")
        self.assertEqual(proc.stdout.strip(), "3")
        self.assertEqual(proc.stderr, "")

    def test_loop_limit_takes_a_config_override(self):
        self.assertEqual(self.value("loopLimit", {"loopLimit": 5}).stdout.strip(), "5")

    def test_loop_limit_takes_the_environment_override(self):
        self.assertEqual(self.value("loopLimit", env={"HOKO_LOOP_LIMIT": "7"}).stdout.strip(), "7")

    def test_loop_limit_is_coerced_from_the_environment_as_an_integer(self):
        proc = self.value("loopLimit", env={"HOKO_LOOP_LIMIT": "9"})
        self.assertEqual(proc.stdout.strip(), "9")
        self.assertNotIn("hoko settings:", proc.stderr)

    def test_loop_limit_outside_0_to_10_prints_the_default_with_a_note(self):
        for bad in (-1, 11, "5", True, 2.5):
            proc = self.value("loopLimit", {"loopLimit": bad})
            self.assertEqual(proc.stdout.strip(), "3", bad)
            self.assertIn("loopLimit", proc.stderr, bad)
        proc = self.value("loopLimit", env={"HOKO_LOOP_LIMIT": "99"})
        self.assertEqual(proc.stdout.strip(), "3")
        self.assertIn("loopLimit", proc.stderr)

    def test_loop_limit_keeps_the_ends_of_the_range(self):
        self.assertEqual(self.value("loopLimit", {"loopLimit": 0}).stdout.strip(), "0")
        self.assertEqual(self.value("loopLimit", {"loopLimit": 10}).stdout.strip(), "10")


class TestPlanGate(KeyCase):
    def test_plan_gate_is_on_unless_a_source_turns_it_off(self):
        self.assertEqual(self.value("planGate").stdout.strip(), "true")
        self.assertEqual(
            self.value("planGate", env={"HOKO_PLAN_GATE": "false"}).stdout.strip(), "false"
        )

    def test_plan_gate_takes_a_config_override(self):
        self.assertEqual(self.value("planGate", {"planGate": False}).stdout.strip(), "false")

    def test_plan_gate_takes_the_home_config_override(self):
        proc = self.layered("planGate", home_config={"planGate": False})
        self.assertEqual(proc.stdout.strip(), "false")


class TestCrap(KeyCase):
    def test_crap_defaults_to_on(self):
        self.assertEqual(self.value("crap").stdout.strip(), "true")

    def test_crap_takes_a_config_override(self):
        self.assertEqual(self.value("crap", {"crap": False}).stdout.strip(), "false")

    def test_crap_coerces_an_environment_override(self):
        self.assertEqual(self.value("crap", env={"HOKO_CRAP": "off"}).stdout.strip(), "false")


class TestMutation(KeyCase):
    def test_mutation_defaults_to_on(self):
        self.assertEqual(self.value("mutation").stdout.strip(), "true")

    def test_mutation_takes_a_config_override(self):
        self.assertEqual(self.value("mutation", {"mutation": False}).stdout.strip(), "false")

    def test_mutation_coerces_an_environment_override(self):
        self.assertEqual(
            self.value("mutation", env={"HOKO_MUTATION": "false"}).stdout.strip(), "false"
        )


class TestCrapMax(KeyCase):
    def test_crap_max_defaults_to_30(self):
        self.assertEqual(self.value("crapMax").stdout.strip(), "30")

    def test_crap_max_takes_a_config_override(self):
        self.assertEqual(self.value("crapMax", {"crapMax": 45}).stdout.strip(), "45")

    def test_crap_max_is_coerced_from_the_environment_as_an_integer(self):
        self.assertEqual(self.value("crapMax", env={"HOKO_CRAP_MAX": "12"}).stdout.strip(), "12")
        self.assertEqual(
            self.value("crapMax", env={"HOKO_CRAP_MAX": "many"}).stdout.strip(), "30"
        )


class TestMutationMin(KeyCase):
    def test_mutation_min_defaults_to_70(self):
        self.assertEqual(self.value("mutationMin").stdout.strip(), "70")

    def test_mutation_min_takes_a_config_override(self):
        self.assertEqual(self.value("mutationMin", {"mutationMin": 60}).stdout.strip(), "60")

    def test_mutation_min_is_coerced_from_the_environment_as_an_integer(self):
        self.assertEqual(
            self.value("mutationMin", env={"HOKO_MUTATION_MIN": "55"}).stdout.strip(), "55"
        )


class TestPricing(KeyCase):
    def test_pricing_defaults_to_no_overrides(self):
        self.assertEqual(self.value("pricing").stdout.strip(), "{}")

    def test_pricing_reads_an_object_from_the_config(self):
        config = {"pricing": {"some-model": {"input": 1}}}
        self.assertEqual(json.loads(self.value("pricing", config).stdout),
                         {"some-model": {"input": 1}})

    def test_env_pricing_is_parsed_as_json_and_a_bad_value_falls_back(self):
        good = self.value("pricing", env={"HOKO_PRICING": '{"some-model": {"input": 2}}'})
        self.assertEqual(json.loads(good.stdout), {"some-model": {"input": 2}})
        for bad in ("not json", "[1]"):
            proc = self.value("pricing", env={"HOKO_PRICING": bad})
            self.assertEqual(proc.stdout.strip(), "{}", bad)


class TestEffortsAreGone(KeyCase):
    def test_r2_the_efforts_setting_is_refused(self):
        proc = self.value("efforts")
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(proc.stdout.strip(), "")

    def test_r2_a_per_stage_effort_key_is_refused(self):
        for key in ("efforts.qa", "efforts.nonsense"):
            proc = self.value(key)
            self.assertEqual(proc.returncode, 2, key)
            self.assertEqual(proc.stdout.strip(), "", key)

    def test_r2_the_settings_list_names_no_effort_key(self):
        proc = self.value("nonsense")
        self.assertEqual(proc.returncode, 2)
        self.assertNotIn("effort", proc.stderr)

    def test_r2_a_config_carrying_efforts_changes_no_setting(self):
        config = {"efforts": {"qa": "max"}, "coverageMin": 70}
        self.assertEqual(self.value("coverageMin", config).stdout.strip(), "70")
        self.assertEqual(self.value("efforts.qa", config).returncode, 2)


class TestFinalReview(KeyCase):
    def test_final_review_defaults_to_inherit(self):
        self.assertEqual(self.value("finalReview").stdout.strip(), "")

    def test_final_review_takes_a_config_override(self):
        self.assertEqual(
            self.value("finalReview", {"finalReview": "provider/model"}).stdout.strip(),
            "provider/model",
        )

    def test_final_review_takes_the_environment_override(self):
        proc = self.value("finalReview", env={"HOKO_FINAL_REVIEW": "provider/other"})
        self.assertEqual(proc.stdout.strip(), "provider/other")


if __name__ == "__main__":
    unittest.main(verbosity=2)

#!/usr/bin/env python3
"""Tests for settings.py — precedence, defaults, coercion and the command-line form."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = PLUGIN_ROOT / "scripts" / "settings.py"


def plugin_copy(tmp, config):
    """A throwaway copy of the plugin, so the real hoko.json is never read."""
    plugin = Path(tmp) / "plugin"
    (plugin / "scripts").mkdir(parents=True)
    (plugin / "scripts" / "settings.py").write_text(
        SCRIPT.read_text(encoding="utf-8"), encoding="utf-8"
    )
    if config is not None:
        (plugin / "hoko.json").write_text(json.dumps(config), encoding="utf-8")
    return plugin


def home_copy(tmp, config):
    home = Path(tmp) / "home"
    (home / ".config" / "opencode").mkdir(parents=True, exist_ok=True)
    if config is not None:
        (home / ".config" / "opencode" / "hoko.json").write_text(
            json.dumps(config), encoding="utf-8"
        )
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

    def value(self, key, config=None, env=None):
        root = tempfile.mkdtemp(dir=self.tmp.name)
        return read(plugin_copy(root, config), key, env=env)

    def layered(self, key, plugin_config=None, home_config=None, env=None):
        root = tempfile.mkdtemp(dir=self.tmp.name)
        home = home_copy(tempfile.mkdtemp(dir=self.tmp.name), home_config)
        return read(plugin_copy(root, plugin_config), key, home=home, env=env)


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

    def test_review_model_is_still_a_setting(self):
        self.assertEqual(self.value("reviewModel").stdout.strip(), "")
        self.assertEqual(self.value("reviewModel", {"reviewModel": "haiku"}).stdout.strip(), "haiku")


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


class TestEfforts(KeyCase):
    def test_efforts_default_per_stage(self):
        expected = {"refine": "high", "spec": "high", "plan": "high",
                    "implement": "high", "qa": "medium", "review": "high"}
        for stage, effort in expected.items():
            proc = self.value("efforts." + stage)
            self.assertEqual(proc.stdout.strip(), effort, stage)
            self.assertEqual(proc.stderr, "")

    def test_efforts_takes_a_config_override(self):
        self.assertEqual(
            self.value("efforts.implement", {"efforts": {"implement": "low"}}).stdout.strip(),
            "low",
        )

    def test_efforts_prints_the_default_for_a_stage_another_stage_overrides_around(self):
        config = {"efforts": {"implement": "low"}}
        self.assertEqual(self.value("efforts.qa", config).stdout.strip(), "medium")
        self.assertEqual(self.value("efforts.review", config).stdout.strip(), "high")

    def test_efforts_merge_across_sources_per_key(self):
        env = {"HOKO_EFFORTS": json.dumps({"plan": "medium"})}
        results = {stage: self.layered("efforts." + stage,
                                       {"efforts": {"implement": "low"}},
                                       {"efforts": {"qa": "high"}},
                                       env=env).stdout.strip()
                   for stage in ("implement", "qa", "plan", "review")}
        self.assertEqual(results, {"implement": "low", "qa": "high",
                                   "plan": "medium", "review": "high"})

    def test_efforts_accept_every_documented_level(self):
        for level in ("low", "medium", "high", "xhigh", "max"):
            proc = self.value("efforts.qa", {"efforts": {"qa": level}})
            self.assertEqual(proc.stdout.strip(), level)
            self.assertEqual(proc.stderr, "")

    def test_an_unknown_effort_prints_that_stages_default_with_a_note(self):
        config = {"efforts": {"qa": "extreme", "plan": "low"}}
        proc = self.value("efforts.qa", config)
        self.assertEqual(proc.stdout.strip(), "medium")
        self.assertIn("efforts.qa", proc.stderr)
        self.assertEqual(self.value("efforts.plan", config).stdout.strip(), "low")
        env = {"HOKO_EFFORTS": json.dumps({"review": "ultra"})}
        self.assertEqual(self.value("efforts.review", env=env).stdout.strip(), "high")

    def test_a_per_stage_override_that_is_not_json_is_ignored(self):
        env = {"HOKO_EFFORTS": "[1]"}
        self.assertEqual(self.value("efforts.plan", env=env).stdout.strip(), "high")

    def test_efforts_prints_the_whole_object_without_a_stage(self):
        merged = json.loads(self.value("efforts", {"efforts": {"plan": "low"}}).stdout)
        self.assertEqual(merged["plan"], "low")
        self.assertEqual(merged["qa"], "medium")

    def test_a_stage_that_does_not_exist_is_refused(self):
        for key in ("efforts.nonsense", "coverageMin.qa"):
            proc = self.value(key)
            self.assertEqual(proc.returncode, 2, key)
            self.assertEqual(proc.stdout.strip(), "", key)


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

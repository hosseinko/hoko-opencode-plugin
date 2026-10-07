#!/usr/bin/env python3
"""Tests for settings.py — precedence, defaults, and the command-line form."""

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


class TestSettings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_defaults_apply_without_any_config(self):
        plugin = plugin_copy(self.tmp.name, None)
        self.assertEqual(read(plugin, "coverageMin").stdout.strip(), "85")
        self.assertEqual(read(plugin, "plansDir").stdout.strip(), ".ai/plans")
        self.assertEqual(read(plugin, "commitAuto").stdout.strip(), "0")
        self.assertEqual(read(plugin, "journalPath").stdout.strip(), "")
        self.assertEqual(read(plugin, "finalReview").stdout.strip(), "")
        self.assertEqual(read(plugin, "specs").stdout.strip(), "0")

    def test_plugin_config_overrides_the_default(self):
        plugin = plugin_copy(self.tmp.name, {"coverageMin": 70})
        self.assertEqual(read(plugin, "coverageMin").stdout.strip(), "70")

    def test_home_config_overrides_the_plugin(self):
        plugin = plugin_copy(self.tmp.name, {"coverageMin": 70, "plansDir": ".ai/plans"})
        home = home_copy(self.tmp.name, {"coverageMin": 95})
        self.assertEqual(read(plugin, "coverageMin", home=home).stdout.strip(), "95")
        self.assertEqual(read(plugin, "plansDir", home=home).stdout.strip(), ".ai/plans")

    def test_environment_overrides_every_config(self):
        plugin = plugin_copy(self.tmp.name, {"coverageMin": 70})
        home = home_copy(self.tmp.name, {"coverageMin": 95})
        proc = read(plugin, "coverageMin", home=home, env={"HOKO_COVERAGE_MIN": "50"})
        self.assertEqual(proc.stdout.strip(), "50")

    def test_env_override_true_turns_a_boolean_setting_on(self):
        plugin = plugin_copy(self.tmp.name, {"loopGuard": False})
        proc = read(plugin, "loopGuard", env={"HOKO_LOOP_GUARD": "true"})
        self.assertEqual(proc.stdout.strip(), "1")

    def test_env_override_false_turns_a_boolean_setting_off(self):
        plugin = plugin_copy(self.tmp.name, {"loopGuard": True})
        proc = read(plugin, "loopGuard", env={"HOKO_LOOP_GUARD": "false"})
        self.assertEqual(proc.stdout.strip(), "0")

    def test_env_override_accepts_yes_no_on_off_case_insensitively(self):
        plugin = plugin_copy(self.tmp.name, None)
        self.assertEqual(read(plugin, "commitAuto", env={"HOKO_COMMIT_AUTO": "YES"}).stdout.strip(), "1")
        self.assertEqual(read(plugin, "commitAuto", env={"HOKO_COMMIT_AUTO": "On"}).stdout.strip(), "1")
        self.assertEqual(read(plugin, "commitAuto", env={"HOKO_COMMIT_AUTO": "no"}).stdout.strip(), "0")
        self.assertEqual(read(plugin, "commitAuto", env={"HOKO_COMMIT_AUTO": "OFF"}).stdout.strip(), "0")

    def test_env_override_coerces_an_int_setting(self):
        plugin = plugin_copy(self.tmp.name, None)
        proc = read(plugin, "coverageMin", env={"HOKO_COVERAGE_MIN": "42"})
        self.assertEqual(proc.stdout.strip(), "42")

    def test_env_override_leaves_a_string_setting_untouched(self):
        plugin = plugin_copy(self.tmp.name, None)
        proc = read(plugin, "journalPath", env={"HOKO_JOURNAL_PATH": "~/notes/journal"})
        self.assertEqual(proc.stdout.strip(), "~/notes/journal")

    def test_env_override_that_does_not_parse_falls_back_to_the_default(self):
        plugin = plugin_copy(self.tmp.name, None)
        self.assertEqual(read(plugin, "coverageMin", env={"HOKO_COVERAGE_MIN": "many"}).stdout.strip(), "85")
        self.assertEqual(read(plugin, "loopGuard", env={"HOKO_LOOP_GUARD": "maybe"}).stdout.strip(), "1")

    def test_true_commit_auto_renders_as_one(self):
        plugin = plugin_copy(self.tmp.name, {"commitAuto": True})
        self.assertEqual(read(plugin, "commitAuto").stdout.strip(), "1")

    def test_pricing_defaults_to_no_overrides(self):
        plugin = plugin_copy(self.tmp.name, None)
        self.assertEqual(read(plugin, "pricing").stdout.strip(), "{}")

    def test_pricing_reads_an_object_from_the_config(self):
        plugin = plugin_copy(self.tmp.name, {"pricing": {"some-model": {"input": 1}}})
        self.assertEqual(json.loads(read(plugin, "pricing").stdout), {"some-model": {"input": 1}})

    def test_env_pricing_is_parsed_as_json_and_a_bad_value_falls_back(self):
        plugin = plugin_copy(self.tmp.name, None)
        good = read(plugin, "pricing", env={"HOKO_PRICING": '{"some-model": {"input": 2}}'})
        self.assertEqual(json.loads(good.stdout), {"some-model": {"input": 2}})
        for bad in ("not json", "[1]"):
            self.assertEqual(read(plugin, "pricing", env={"HOKO_PRICING": bad}).stdout.strip(), "{}")

    def test_unknown_keys_in_config_are_ignored(self):
        plugin = plugin_copy(self.tmp.name, {"nonsense": "x", "coverageMin": 70})
        self.assertEqual(read(plugin, "coverageMin").stdout.strip(), "70")

    def test_unknown_key_is_refused(self):
        plugin = plugin_copy(self.tmp.name, None)
        proc = read(plugin, "nonsense")
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(proc.stdout.strip(), "")

    def test_malformed_config_falls_back_to_the_default(self):
        plugin = plugin_copy(self.tmp.name, None)
        (Path(plugin) / "hoko.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(read(plugin, "coverageMin").stdout.strip(), "85")


if __name__ == "__main__":
    unittest.main(verbosity=2)

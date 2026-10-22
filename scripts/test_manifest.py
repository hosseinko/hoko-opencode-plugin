#!/usr/bin/env python3
"""The package manifest and the two plugin entrypoints agree with what the README says."""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "package.json"
PLUGIN = ROOT / "plugin"

TEST_SCRIPT = "bun plugin/test_hoko.ts && python3 scripts/run_tests.py"


class PackageManifestTestCase(unittest.TestCase):
    def setUp(self):
        self.package = json.loads(PACKAGE.read_text(encoding="utf-8"))

    def test_the_test_script_runs_the_plugin_suite_then_the_python_one(self):
        self.assertEqual(TEST_SCRIPT, self.package.get("scripts", {}).get("test"))

    def test_the_package_is_an_es_module(self):
        self.assertEqual("module", self.package.get("type"))

    def test_the_plugin_has_no_runtime_dependencies(self):
        for field in ("dependencies", "peerDependencies"):
            self.assertFalse(self.package.get(field), f"{field} would add a runtime install step")

    def test_the_suite_declares_one_pinned_dependency_for_the_renderer(self):
        dev = self.package.get("devDependencies", {})
        self.assertEqual(["solid-js"], sorted(dev), "the suite's only dependency is the renderer's")
        self.assertRegex(dev["solid-js"], r"^\d+\.\d+\.\d+$", "the version is pinned, not a range")


class PluginEntrypointTestCase(unittest.TestCase):
    def test_the_server_plugin_declares_the_hoko_id(self):
        self.assertRegex((PLUGIN / "hoko.ts").read_text(encoding="utf-8"), r'\bid:\s*"hoko"')

    def test_the_terminal_plugin_declares_its_own_id(self):
        self.assertRegex((PLUGIN / "tui.ts").read_text(encoding="utf-8"), r'\bid:\s*"hoko\.tui"')

    def test_the_entrypoints_do_not_share_an_id(self):
        ids = [re.search(r'\bid:\s*"([^"]+)"', (PLUGIN / name).read_text(encoding="utf-8")).group(1)
               for name in ("hoko.ts", "tui.ts")]
        self.assertEqual(len(ids), len(set(ids)), ids)

    def test_the_directory_entrypoint_reexports_the_server_plugin(self):
        self.assertIn('export { default } from "./hoko.ts"', (PLUGIN / "index.ts").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)

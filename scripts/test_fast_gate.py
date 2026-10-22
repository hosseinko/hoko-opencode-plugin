#!/usr/bin/env python3
"""Tests for fast-gate.py — a scratch git repo per case, run as a subprocess."""

import os
import subprocess
import sys
import tempfile
import unittest

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fast-gate.py")


class FastGateTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.env = dict(os.environ)
        self.env["TMPDIR"] = self.tmpdir.name
        self.env["HOME"] = self.tmpdir.name
        self.env["GIT_AUTHOR_NAME"] = "Test"
        self.env["GIT_AUTHOR_EMAIL"] = "test@example.com"
        self.env["GIT_COMMITTER_NAME"] = "Test"
        self.env["GIT_COMMITTER_EMAIL"] = "test@example.com"

    def git(self, root, *args):
        result = subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, env=self.env,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def repo(self, name="repo"):
        path = os.path.join(self.tmpdir.name, name)
        os.makedirs(path, exist_ok=True)
        self.git(path, "init", "-q")
        self.write(path, ".gitkeep", "")
        self.git(path, "add", ".gitkeep")
        self.git(path, "commit", "-q", "-m", "initial")
        return path

    def write(self, root, relpath, text):
        path = os.path.join(root, relpath)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def commit(self, root, message="commit"):
        self.git(root, "add", "-A")
        self.git(root, "commit", "-q", "-m", message)

    def makefile(self, root, analyse="true", unit="true", suite=None):
        lines = [f"analyse:\n\t{analyse}\n"]
        if unit is not None:
            lines.append(f"unit:\n\t{unit}\n")
        if suite is not None:
            lines.append(f"test:\n\t{suite}\n")
        self.write(root, "Makefile", "\n".join(lines))
        self.commit(root, "add makefile")

    def run_gate(self, root):
        args = [sys.executable, SCRIPT, "--root", root]
        return subprocess.run(args, capture_output=True, text=True, env=self.env)


class TestGreenRun(FastGateTestCase):
    def test_a_green_run_exits_zero_and_names_both_commands(self):
        root = self.repo()
        self.makefile(root)
        proc = self.run_gate(root)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("analyse: make analyse — pass", proc.stdout)
        self.assertIn("tests: make unit — pass", proc.stdout)

    def test_a_changed_file_no_plan_names_still_passes_when_both_gates_are_green(self):
        root = self.repo()
        self.makefile(root)
        self.write(root, "scripts/unexpected.py", "content")
        proc = self.run_gate(root)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


class TestRedGate(FastGateTestCase):
    def test_a_red_analyser_exits_one(self):
        root = self.repo()
        self.makefile(root, analyse="false")
        proc = self.run_gate(root)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("analyse: make analyse — fail", proc.stdout)

    def test_a_red_test_gate_exits_one(self):
        root = self.repo()
        self.makefile(root, unit="false")
        proc = self.run_gate(root)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("tests: make unit — fail", proc.stdout)

    def test_a_failing_gate_prints_the_output_tail_and_the_log_path(self):
        root = self.repo()
        self.makefile(root, analyse="echo boom && false")
        proc = self.run_gate(root)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("boom", proc.stdout)
        self.assertIn("analyse: log at", proc.stdout)


class TestSuiteFallback(FastGateTestCase):
    def test_the_suite_command_runs_as_the_test_gate_when_there_is_no_unit_command(self):
        root = self.repo()
        self.makefile(root, unit=None, suite="true")
        proc = self.run_gate(root)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("tests: make test — pass", proc.stdout)


class TestOneGateSkipped(FastGateTestCase):
    def test_one_gate_skipped_while_the_other_runs_still_exits_zero(self):
        root = self.repo()
        self.makefile(root, unit=None, suite=None)
        proc = self.run_gate(root)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("analyse: make analyse — pass", proc.stdout)
        self.assertIn("tests: no command found — skipped", proc.stdout)
        self.assertNotIn("warning: nothing was checked", proc.stdout)


class TestBothGatesSkipped(FastGateTestCase):
    def test_both_gates_skipped_prints_unchecked_and_exits_two(self):
        root = self.repo()
        proc = self.run_gate(root)
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("analyse: no command found — skipped", proc.stdout)
        self.assertIn("tests: no command found — skipped", proc.stdout)
        self.assertIn("unchecked: no gate command found", proc.stdout)


if __name__ == "__main__":
    unittest.main()

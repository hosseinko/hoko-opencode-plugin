#!/usr/bin/env python3
"""Tests for gate.py — run each case as a subprocess against a scratch TMPDIR."""

import os
import subprocess
import sys
import tempfile
import unittest

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gate.py")


class GateTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.env = dict(os.environ)
        self.env["TMPDIR"] = self.tmpdir.name
        self.env["HOME"] = self.tmpdir.name

    def run_gate(self, command, cwd=None):
        args = [sys.executable, SCRIPT, "--command", command]
        if cwd:
            args += ["--cwd", cwd]
        return subprocess.run(args, capture_output=True, text=True, env=self.env)


class TestExitStatus(GateTestCase):
    def test_a_passing_command_exits_zero(self):
        proc = self.run_gate("echo hello")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("hello", proc.stdout)
        self.assertIn("exit: 0", proc.stdout)

    def test_a_failing_command_reports_its_own_exit_status_not_tails(self):
        proc = self.run_gate("echo boom && exit 7")
        self.assertEqual(proc.returncode, 7)
        self.assertIn("exit: 7", proc.stdout)

    def test_a_command_not_found_reports_a_nonzero_status(self):
        proc = self.run_gate("this-command-does-not-exist-anywhere")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn(f"exit: {proc.returncode}", proc.stdout)


class TestOutput(GateTestCase):
    def test_only_the_last_forty_lines_are_printed(self):
        proc = self.run_gate("seq 1 100")
        self.assertEqual(proc.returncode, 0)
        lines = [l for l in proc.stdout.splitlines() if l.strip().isdigit()]
        self.assertEqual(lines[0], "61")
        self.assertEqual(lines[-1], "100")

    def test_stderr_is_captured_into_the_reported_log(self):
        proc = self.run_gate("echo oops 1>&2 && exit 3")
        self.assertEqual(proc.returncode, 3)
        self.assertIn("oops", proc.stdout)

    def test_runs_in_the_given_cwd(self):
        sub = os.path.join(self.tmpdir.name, "sub")
        os.makedirs(sub)
        with open(os.path.join(sub, "marker.txt"), "w", encoding="utf-8") as f:
            f.write("here")
        proc = self.run_gate("cat marker.txt", cwd=sub)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("here", proc.stdout)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Tests for run_tests.py — the runner is driven as a subprocess over a scratch suite
folder, with its own scratch TMPDIR so the per-worker temp dirs can be inspected."""

import os
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "run_tests.py"
MAKEFILE = SCRIPT.parent.parent / "Makefile"

PASSING = """
    import unittest

    class TestPassing(unittest.TestCase):
        def test_one(self):
            self.assertEqual(1, 1)

        def test_two(self):
            self.assertTrue(True)
"""

FAILING = """
    import unittest

    class TestFailing(unittest.TestCase):
        def test_fails(self):
            self.assertEqual(1, 2)

        def test_passes(self):
            self.assertTrue(True)
"""

ERRORING = """
    import unittest

    class TestErroring(unittest.TestCase):
        def test_errors(self):
            return 1 / 0
"""

BROKEN_IMPORT = """
    import module_that_does_not_exist
"""

DYING = """
    import os
    import unittest

    class TestDying(unittest.TestCase):
        def test_kills_the_worker(self):
            os._exit(3)

        def test_survives(self):
            self.assertTrue(True)
"""

FIXTURE = """
    import os
    import unittest
    from pathlib import Path

    COUNTER = Path(os.environ["FIXTURE_COUNTER"])

    class TestWithFixture(unittest.TestCase):
        @classmethod
        def setUpClass(cls):
            with COUNTER.open("a") as handle:
                handle.write("built\\n")

        def test_a(self):
            self.assertTrue(True)

        def test_b(self):
            self.assertTrue(True)

        def test_c(self):
            self.assertTrue(True)

        def test_d(self):
            self.assertTrue(True)
"""

TEMP_DIRS = """
    import os
    import tempfile
    import unittest
    from pathlib import Path

    SEEN = Path(os.environ["SEEN_TEMP_DIRS"])

    class TestTempDirs(unittest.TestCase):
        def test_a(self):
            self.record()

        def test_b(self):
            self.record()

        def record(self):
            with SEEN.open("a") as handle:
                handle.write(os.environ["TMPDIR"] + "|" + tempfile.gettempdir() + "\\n")
"""

GO_SUITE = """
    import os
    from pathlib import Path

    MARKER = Path(os.environ["GO_SUITE_MARKER"])

    def main():
        MARKER.write_text("ran")
        print("ok   go_check builds gofmt, go vet, golangci-lint, govulncheck in order")
        print("all passed")

    if __name__ == "__main__":
        main()
"""

GO_SUITE_FAILING = """
    import sys

    def main():
        print("FAIL go_check exits 0 when every check passes")
        sys.exit(1)

    if __name__ == "__main__":
        main()
"""


class RunnerCase(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name).resolve()
        self.suite = self.root / "suite"
        self.suite.mkdir()
        self.tmpdir = self.root / "tmp"
        self.tmpdir.mkdir()
        self.script = SCRIPT

    def add(self, name, source):
        (self.suite / f"{name}.py").write_text(textwrap.dedent(source), encoding="utf-8")

    def run_runner(self, *extra, **env):
        environment = dict(os.environ, TMPDIR=str(self.tmpdir), **env)
        return subprocess.run(
            [sys.executable, str(self.script), "--start-dir", str(self.suite), *extra],
            capture_output=True,
            text=True,
            env=environment,
            timeout=120,
        )

    def discover_count(self, **env):
        proc = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", str(self.suite), "-p", "test_*.py"],
            capture_output=True,
            text=True,
            env=dict(os.environ, **env),
        )
        return int(re.search(r"Ran (\d+) tests?", proc.stderr).group(1))

    @staticmethod
    def ran(proc):
        return int(re.search(r"Ran (\d+) tests? in \d+\.\d+s", proc.stdout).group(1))


class TestRunTests(RunnerCase):
    def test_all_passing_tests_exit_zero(self):
        self.add("test_passing", PASSING)
        proc = self.run_runner()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.ran(proc), 2)
        self.assertTrue(proc.stdout.rstrip().endswith("OK"))

    def test_a_failing_test_exits_one_with_its_id_and_traceback(self):
        self.add("test_passing", PASSING)
        self.add("test_failing", FAILING)
        proc = self.run_runner()
        self.assertEqual(proc.returncode, 1)
        self.assertIn("FAIL: test_failing.TestFailing.test_fails", proc.stdout)
        self.assertIn("AssertionError: 1 != 2", proc.stdout)
        self.assertEqual(self.ran(proc), 4)
        self.assertIn("FAILED (failures=1)", proc.stdout)

    def test_an_erroring_test_exits_one_with_its_id_and_traceback(self):
        self.add("test_erroring", ERRORING)
        proc = self.run_runner()
        self.assertEqual(proc.returncode, 1)
        self.assertIn("ERROR: test_erroring.TestErroring.test_errors", proc.stdout)
        self.assertIn("ZeroDivisionError", proc.stdout)
        self.assertIn("FAILED (errors=1)", proc.stdout)

    def test_a_module_that_fails_to_import_exits_one(self):
        self.add("test_passing", PASSING)
        self.add("test_broken", BROKEN_IMPORT)
        proc = self.run_runner()
        self.assertEqual(proc.returncode, 1)
        self.assertIn("test_broken", proc.stdout)
        self.assertIn("ModuleNotFoundError", proc.stdout)
        self.assertIn("FAILED (errors=1)", proc.stdout)

    def test_a_worker_that_dies_exits_one_and_the_other_tests_still_run(self):
        self.add("test_dying", DYING)
        self.add("test_passing", PASSING)
        proc = self.run_runner("--jobs", "2")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("ERROR: test_dying.TestDying.test_kills_the_worker", proc.stdout)
        self.assertIn("exit code 3", proc.stdout)
        self.assertEqual(self.ran(proc), 4)
        self.assertIn("FAILED (errors=1)", proc.stdout)

    def test_a_setupclass_class_builds_its_fixture_once(self):
        counter = self.root / "counter"
        self.add("test_fixture", FIXTURE)
        proc = self.run_runner("--jobs", "4", FIXTURE_COUNTER=str(counter))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.ran(proc), 4)
        self.assertEqual(counter.read_text(encoding="utf-8").splitlines(), ["built"])

    def test_the_reported_count_equals_the_discovered_count(self):
        self.add("test_passing", PASSING)
        self.add("test_failing", FAILING)
        self.add("test_fixture", FIXTURE)
        self.add("test_erroring", ERRORING)
        env = {"FIXTURE_COUNTER": str(self.root / "counter")}
        proc = self.run_runner(**env)
        self.assertEqual(self.ran(proc), self.discover_count(**env))

    def test_jobs_one_gives_the_same_result(self):
        self.add("test_passing", PASSING)
        self.add("test_failing", FAILING)
        self.add("test_fixture", FIXTURE)
        env = {"FIXTURE_COUNTER": str(self.root / "counter")}
        parallel = self.run_runner("--jobs", "4", **env)
        single = self.run_runner("--jobs", "1", **env)
        self.assertEqual(single.returncode, parallel.returncode)
        self.assertEqual(self.ran(single), self.ran(parallel))
        self.assertIn("FAIL: test_failing.TestFailing.test_fails", single.stdout)
        self.assertIn("FAILED (failures=1)", single.stdout)

    def test_each_worker_gets_its_own_temp_dir_removed_on_exit(self):
        seen = self.root / "seen"
        self.add("test_temp_dirs", TEMP_DIRS)
        proc = self.run_runner("--jobs", "2", SEEN_TEMP_DIRS=str(seen))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        recorded = [line.split("|") for line in seen.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(recorded), 2)
        for env_tmp, python_tmp in recorded:
            self.assertEqual(env_tmp, python_tmp)
            self.assertEqual(Path(env_tmp).parent, self.tmpdir)
            self.assertFalse(Path(env_tmp).exists())
        self.assertNotEqual(recorded[0][0], recorded[1][0])
        self.assertEqual(list(self.tmpdir.iterdir()), [])

    def test_jobs_below_one_is_rejected(self):
        self.add("test_passing", PASSING)
        proc = self.run_runner("--jobs", "0")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--jobs must be at least 1", proc.stderr)


class DefaultRootsCase(RunnerCase):
    """The runner in a throwaway copy of the repository, discovering its default roots."""

    def setUp(self):
        super().setUp()
        repo = self.repo = self.root / "repo"
        self.suite = repo / "scripts"
        self.suite.mkdir(parents=True)
        self.script = self.suite / "run_tests.py"
        self.script.write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
        (repo / "Makefile").write_text(MAKEFILE.read_text(encoding="utf-8"), encoding="utf-8")
        self.go_suite = repo / "skills" / "hoko-senior-go-developer" / "scripts"
        self.go_suite.mkdir(parents=True)

    def add_go_suite(self, source):
        (self.go_suite / "test_go_scripts.py").write_text(
            textwrap.dedent(source), encoding="utf-8"
        )

    def run_default(self, *extra, **env):
        environment = dict(os.environ, TMPDIR=str(self.tmpdir), **env)
        return subprocess.run(
            [sys.executable, str(self.script), *extra],
            capture_output=True,
            text=True,
            env=environment,
            timeout=120,
        )


class TestDefaultRoots(DefaultRootsCase):
    def test_bun_run_test_runs_every_python_suite_including_the_one_under_skills(self):
        marker = self.root / "go-suite-ran"
        self.add("test_passing", PASSING)
        self.add_go_suite(GO_SUITE)
        proc = self.run_default(GO_SUITE_MARKER=str(marker))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(marker.read_text(encoding="utf-8"), "ran")
        self.assertEqual(self.ran(proc), 3)

    def test_a_failing_suite_under_skills_fails_the_run_with_its_output(self):
        self.add("test_passing", PASSING)
        self.add_go_suite(GO_SUITE_FAILING)
        proc = self.run_default()
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn(f"ERROR: {self.go_suite / 'test_go_scripts.py'}", proc.stdout)
        self.assertIn("FAIL go_check exits 0 when every check passes", proc.stdout)
        self.assertIn("FAILED (errors=1)", proc.stdout)

    def test_make_test_serial_runs_every_python_suite_including_the_one_under_skills(self):
        marker = self.root / "go-suite-ran"
        self.add("test_passing", PASSING)
        self.add_go_suite(GO_SUITE)
        proc = subprocess.run(
            ["make", "-C", str(self.repo), "test-serial"],
            capture_output=True,
            text=True,
            env=dict(os.environ, TMPDIR=str(self.tmpdir), GO_SUITE_MARKER=str(marker)),
            timeout=120,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(marker.read_text(encoding="utf-8"), "ran")
        self.assertEqual(self.ran(proc), 3)

    def test_the_pattern_selects_suites_from_both_roots(self):
        marker = self.root / "go-suite-ran"
        self.add("test_passing", PASSING)
        self.add_go_suite(GO_SUITE)
        only_go = self.run_default("--pattern", "test_go_scripts.py", GO_SUITE_MARKER=str(marker))
        self.assertEqual(only_go.returncode, 0, only_go.stdout + only_go.stderr)
        self.assertEqual(self.ran(only_go), 1)
        self.assertTrue(marker.exists())
        marker.unlink()
        only_scripts = self.run_default("--pattern", "test_passing.py", GO_SUITE_MARKER=str(marker))
        self.assertEqual(only_scripts.returncode, 0, only_scripts.stdout + only_scripts.stderr)
        self.assertEqual(self.ran(only_scripts), 2)
        self.assertFalse(marker.exists())

    def test_start_dir_narrows_discovery_to_that_folder(self):
        marker = self.root / "go-suite-ran"
        self.add("test_passing", PASSING)
        self.add_go_suite(GO_SUITE)
        proc = self.run_runner(GO_SUITE_MARKER=str(marker))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.ran(proc), 2)
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)

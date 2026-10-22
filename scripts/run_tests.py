#!/usr/bin/env python3
"""Parallel runner for the plugin's unittest suites, behind `make test`.

Discovers exactly what `python3 -m unittest discover -s scripts -p 'test_*.py'`
discovers, spreads it over long-lived worker processes and prints a unittest-style
summary. Exits 0 only when every unit passed.

Work units: a class that defines `setUpClass`, or every class of a module that defines
`setUpModule`, runs whole in one worker so its fixture is built once; every other test
is its own unit.

Usage: run_tests.py [--jobs N] [--start-dir DIR] [--pattern GLOB]
"""

import argparse
import multiprocessing
import multiprocessing.connection
import os
import shutil
import sys
import tempfile
import time
import unittest
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
LINE = "=" * 70
THIN = "-" * 70


@dataclass
class Unit:
    label: str
    names: list
    size: int
    whole: bool


@dataclass
class Outcome:
    ran: int = 0
    failures: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    skipped: int = 0
    expected_failures: int = 0
    unexpected_successes: list = field(default_factory=list)


def worker_main(conn, start_dir, tmp_dir):
    # TMPDIR must be settled before any test module is imported: journal.STATE_DIR and
    # other hook state derive from the temp dir at import time.
    os.environ["TMPDIR"] = tmp_dir
    tempfile.tempdir = None
    sys.path.insert(0, start_dir)
    loader = unittest.TestLoader()
    while True:
        names = conn.recv()
        if names is None:
            return
        suite = unittest.TestSuite(loader.loadTestsFromName(name) for name in names)
        result = unittest.TestResult()
        result.buffer = True
        suite.run(result)
        conn.send(
            Outcome(
                ran=result.testsRun,
                failures=[(test.id(), tb) for test, tb in result.failures],
                errors=[(test.id(), tb) for test, tb in result.errors],
                skipped=len(result.skipped),
                expected_failures=len(result.expectedFailures),
                unexpected_successes=[test.id() for test in result.unexpectedSuccesses],
            )
        )


def class_suites(suite):
    children = list(suite)
    if children and all(isinstance(child, unittest.TestCase) for child in children):
        yield children
        return
    for child in children:
        if isinstance(child, unittest.TestSuite):
            yield from class_suites(child)


def class_name(test):
    cls = type(test)
    return f"{cls.__module__}.{cls.__qualname__}"


def has_fixture(cls):
    return cls.setUpClass.__func__ is not unittest.TestCase.setUpClass.__func__


def has_module_fixture(cls):
    module = sys.modules.get(cls.__module__)
    return module is not None and hasattr(module, "setUpModule")


def plan_units(suite):
    """Split a discovered suite into work units and the discovery-time import failures."""
    units = []
    module_units = {}
    import_failures = []
    for tests in class_suites(suite):
        cls = type(tests[0])
        if cls.__module__ == unittest.loader.__name__ and cls.__name__ == "_FailedTest":
            import_failures.extend(tests)
        elif has_module_fixture(cls):
            unit = module_units.get(cls.__module__)
            if unit is None:
                unit = module_units[cls.__module__] = Unit(cls.__module__, [], 0, True)
                units.append(unit)
            unit.names.append(class_name(tests[0]))
            unit.size += len(tests)
        elif has_fixture(cls):
            units.append(Unit(class_name(tests[0]), [class_name(tests[0])], len(tests), True))
        else:
            units.extend(Unit(test.id(), [test.id()], 1, False) for test in tests)
    units.sort(key=lambda unit: not unit.whole)
    return units, import_failures


class Worker:
    def __init__(self, context, start_dir):
        self.tmp_dir = tempfile.mkdtemp(prefix="hoko-tests-")
        self.conn, child = context.Pipe()
        self.process = context.Process(
            target=worker_main, args=(child, start_dir, self.tmp_dir), daemon=True
        )
        self.process.start()
        child.close()
        self.unit = None

    def assign(self, unit):
        self.unit = unit
        self.conn.send(unit.names)

    def stop(self):
        try:
            self.conn.send(None)
        except OSError:
            pass
        self.process.join(10)
        if self.process.is_alive():
            self.process.kill()
            self.process.join()
        self.conn.close()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)


def run_units(units, jobs, start_dir):
    context = multiprocessing.get_context("spawn")
    total = Outcome()
    pending = deque(units)
    workers = [Worker(context, start_dir) for _ in range(min(jobs, len(units)))]

    def feed(worker):
        if pending:
            worker.assign(pending.popleft())
        else:
            worker.unit = None

    try:
        for worker in workers:
            feed(worker)
        while any(worker.unit for worker in workers):
            busy = [worker for worker in workers if worker.unit]
            multiprocessing.connection.wait(
                [worker.conn for worker in busy] + [worker.process.sentinel for worker in busy]
            )
            for index, worker in enumerate(workers):
                if not worker.unit:
                    continue
                outcome = collect(worker)
                if outcome is None:
                    continue
                merge(total, worker.unit, outcome)
                if not worker.process.is_alive():
                    workers[index] = worker = replace(context, worker, start_dir)
                feed(worker)
    finally:
        for worker in workers:
            worker.stop()
    return total


def collect(worker):
    try:
        if worker.conn.poll():
            return worker.conn.recv()
    except (EOFError, OSError):
        pass
    if worker.process.is_alive():
        return None
    worker.process.join()
    unit = worker.unit
    return Outcome(
        ran=unit.size,
        errors=[(unit.label, f"worker process died with exit code {worker.process.exitcode}\n")],
    )


def replace(context, dead, start_dir):
    dead.stop()
    return Worker(context, start_dir)


def merge(total, unit, outcome):
    total.ran += outcome.ran
    total.failures += outcome.failures
    total.errors += outcome.errors
    total.skipped += outcome.skipped
    total.expected_failures += outcome.expected_failures
    total.unexpected_successes += outcome.unexpected_successes
    clean = not (outcome.failures or outcome.errors or outcome.unexpected_successes)
    if clean and outcome.ran != unit.size:
        total.errors.append((unit.label, f"ran {outcome.ran} of {unit.size} discovered tests\n"))


def run_import_failures(failed, total):
    for test in failed:
        result = unittest.TestResult()
        test.run(result)
        total.ran += result.testsRun
        total.errors += [(item.id(), tb) for item, tb in result.errors]
        total.failures += [(item.id(), tb) for item, tb in result.failures]


def report(total, elapsed):
    for kind, entries in (("ERROR", total.errors), ("FAIL", total.failures)):
        for name, traceback in entries:
            print(f"{LINE}\n{kind}: {name}\n{THIN}\n{traceback}")
    for name in total.unexpected_successes:
        print(f"{LINE}\nUNEXPECTED SUCCESS: {name}\n")
    print(THIN)
    print(f"Ran {total.ran} tests in {elapsed:.3f}s\n")
    notes = []
    if total.failures:
        notes.append(f"failures={len(total.failures)}")
    if total.errors:
        notes.append(f"errors={len(total.errors)}")
    if total.unexpected_successes:
        notes.append(f"unexpected successes={len(total.unexpected_successes)}")
    extras = []
    if total.skipped:
        extras.append(f"skipped={total.skipped}")
    if total.expected_failures:
        extras.append(f"expected failures={total.expected_failures}")
    if notes:
        print(f"FAILED ({', '.join(notes + extras)})")
    else:
        print(f"OK ({', '.join(extras)})" if extras else "OK")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the unittest suites in parallel.")
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 1, help="worker processes")
    parser.add_argument("--start-dir", default=str(HERE), help="folder to discover suites in")
    parser.add_argument("--pattern", default="test_*.py", help="test file glob")
    args = parser.parse_args(argv)
    if args.jobs < 1:
        parser.error("--jobs must be at least 1")

    start_dir = str(Path(args.start_dir).resolve())
    began = time.monotonic()
    suite = unittest.TestLoader().discover(start_dir, pattern=args.pattern, top_level_dir=start_dir)
    units, import_failures = plan_units(suite)
    total = run_units(units, args.jobs, start_dir) if units else Outcome()
    run_import_failures(import_failures, total)
    report(total, time.monotonic() - began)
    failed = total.failures or total.errors or total.unexpected_successes
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Tests for crap.py — fixture reports built inline, a scratch git repo for the range."""

import json
import os
import subprocess
import sys
import tempfile
import unittest

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "crap.py")

SOURCE = "".join(f"line {n}\n" for n in range(1, 21))


def clover(methods, path="/ignored/src/Foo.php", statements=()):
    """methods: (line, name, attributes) tuples; statements: (line, count) tuples."""
    rows = []
    for line, name, attributes in methods:
        extra = "".join(f' {key}="{value}"' for key, value in attributes.items())
        rows.append(f'<line num="{line}" type="method" name="{name}" visibility="public"{extra} count="1"/>')
    for line, count in statements:
        rows.append(f'<line num="{line}" type="stmt" count="{count}"/>')
    return (
        '<?xml version="1.0"?><coverage generated="1"><project timestamp="1">'
        f'<package name="App"><file name="{path}">' + "".join(rows) + "</file></package></project></coverage>"
    )


def cobertura(methods, filename="src/Foo.php"):
    """methods: (name, complexity, [(line, hits)]) tuples."""
    rows = []
    for name, complexity, lines in methods:
        body = "".join(f'<line number="{n}" hits="{h}"/>' for n, h in lines)
        attributes = "" if complexity is None else f' complexity="{complexity}"'
        rows.append(f'<method name="{name}" signature="()"{attributes}><lines>{body}</lines></method>')
    return (
        '<?xml version="1.0"?><coverage line-rate="0.5" branch-rate="0" version="1"><sources><source>/x</source></sources>'
        f'<packages><package name="App"><classes><class name="Foo" filename="{filename}">'
        "<methods>" + "".join(rows) + "</methods></class></classes></package></packages></coverage>"
    )


class CrapTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.env = dict(os.environ)
        self.env["HOME"] = self.tmpdir.name
        self.env["GIT_AUTHOR_NAME"] = "Test"
        self.env["GIT_AUTHOR_EMAIL"] = "test@example.com"
        self.env["GIT_COMMITTER_NAME"] = "Test"
        self.env["GIT_COMMITTER_EMAIL"] = "test@example.com"
        self.root = os.path.join(self.tmpdir.name, "repo")
        os.makedirs(self.root)
        self.git("init", "-q")
        self.write("src/Foo.php", SOURCE)
        self.write("src/Other.php", SOURCE)
        self.commit("base")

    def git(self, *args):
        result = subprocess.run(
            ["git", *args], cwd=self.root, capture_output=True, text=True, env=self.env,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def write(self, relpath, text):
        path = os.path.join(self.root, relpath)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)

    def change_lines(self, relpath, numbers):
        lines = SOURCE.splitlines(keepends=True)
        for n in numbers:
            lines[n - 1] = f"changed {n}\n"
        self.write(relpath, "".join(lines))
        self.commit("change")

    def report(self, text, name="report.xml"):
        path = os.path.join(self.tmpdir.name, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def run_crap(self, report, maximum="30", diff_range="HEAD~1..HEAD"):
        args = [sys.executable, SCRIPT, "--report", report, "--range", diff_range,
                "--max", maximum, "--root", self.root]
        return subprocess.run(args, capture_output=True, text=True, env=self.env)

    def result(self, report, **kwargs):
        proc = self.run_crap(report, **kwargs)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return json.loads(proc.stdout)


class TestChangedMethodsOverTheThreshold(CrapTestCase):
    def test_a_changed_clover_method_over_the_threshold_is_printed_with_its_score(self):
        self.change_lines("src/Foo.php", [5])
        report = self.report(clover(
            [(3, "risky", {"complexity": 10})],
            statements=[(4, 0), (5, 0), (6, 0)],
        ))
        out = self.result(report)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["findings"], [{
            "file": "src/Foo.php", "line": 3, "method": "risky",
            "complexity": 10.0, "coverage": 0.0, "crap": 110.0,
        }])

    def test_a_partly_covered_method_is_scored_with_the_cubed_uncovered_share(self):
        self.change_lines("src/Foo.php", [5])
        report = self.report(clover(
            [(3, "risky", {"complexity": 4})],
            statements=[(4, 1), (5, 0)],
        ))
        out = self.result(report, maximum="5")
        self.assertEqual(out["findings"][0]["crap"], 6.0)
        self.assertEqual(out["findings"][0]["coverage"], 0.5)

    def test_a_changed_method_at_or_below_the_threshold_is_not_printed(self):
        self.change_lines("src/Foo.php", [5])
        report = self.report(clover(
            [(3, "risky", {"complexity": 10})],
            statements=[(4, 0), (5, 0)],
        ))
        self.assertEqual(self.result(report, maximum="110")["findings"], [])

    def test_a_method_the_run_did_not_touch_is_not_printed_however_high_its_score(self):
        self.change_lines("src/Foo.php", [5])
        report = self.report(clover(
            [(3, "touched", {"complexity": 1}), (10, "neglected", {"complexity": 40})],
            statements=[(4, 1), (5, 1), (11, 0), (12, 0)],
        ))
        self.assertEqual(self.result(report)["findings"], [])

    def test_a_method_in_a_file_the_run_did_not_touch_is_not_printed(self):
        self.change_lines("src/Foo.php", [5])
        report = self.report(clover(
            [(3, "risky", {"complexity": 10})],
            path="/ignored/src/Other.php", statements=[(4, 0), (5, 0)],
        ))
        self.assertEqual(self.result(report)["findings"], [])

    def test_a_change_to_the_last_method_reaches_it_through_its_trailing_statements(self):
        self.change_lines("src/Foo.php", [19])
        report = self.report(clover(
            [(3, "first", {"complexity": 1}), (10, "last", {"complexity": 10})],
            statements=[(4, 1), (11, 0), (19, 0)],
        ))
        findings = self.result(report)["findings"]
        self.assertEqual([f["method"] for f in findings], ["last"])

    def test_findings_are_listed_worst_first(self):
        self.change_lines("src/Foo.php", [5, 12])
        report = self.report(clover(
            [(3, "bad", {"complexity": 7}), (10, "worse", {"complexity": 12})],
            statements=[(4, 0), (5, 0), (11, 0), (12, 0)],
        ))
        findings = self.result(report)["findings"]
        self.assertEqual([f["method"] for f in findings], ["worse", "bad"])

    def test_a_cobertura_method_is_matched_by_its_relative_filename_and_scored(self):
        self.change_lines("src/Foo.php", [5])
        report = self.report(cobertura([
            ("risky", 10, [(4, 0), (5, 0), (6, 0)]),
            ("safe", 10, [(10, 0), (11, 0)]),
        ]))
        out = self.result(report)
        self.assertEqual(out["status"], "ok")
        self.assertEqual([(f["file"], f["method"], f["crap"]) for f in out["findings"]],
                         [("src/Foo.php", "risky", 110.0)])

    def test_an_absolute_report_path_inside_the_root_is_matched(self):
        self.change_lines("src/Foo.php", [5])
        report = self.report(clover(
            [(3, "risky", {"complexity": 10})],
            path=os.path.realpath(os.path.join(self.root, "src/Foo.php")),
            statements=[(4, 0), (5, 0)],
        ))
        self.assertEqual(len(self.result(report)["findings"]), 1)


class TestReportedCrapValue(CrapTestCase):
    def test_a_per_method_crap_value_is_used_instead_of_a_computed_one(self):
        self.change_lines("src/Foo.php", [5])
        report = self.report(clover(
            [(3, "reported", {"complexity": 2, "crap": 50})],
            statements=[(4, 1), (5, 1)],
        ))
        findings = self.result(report)["findings"]
        self.assertEqual([(f["method"], f["crap"]) for f in findings], [("reported", 50.0)])

    def test_a_low_per_method_crap_value_wins_over_a_high_computed_score(self):
        self.change_lines("src/Foo.php", [5])
        report = self.report(clover(
            [(3, "reported", {"complexity": 10, "crap": 4})],
            statements=[(4, 0), (5, 0)],
        ))
        self.assertEqual(self.result(report)["findings"], [])


class TestAbsentGate(CrapTestCase):
    def test_a_clover_report_without_complexity_is_reported_as_absent(self):
        self.change_lines("src/Foo.php", [5])
        report = self.report(clover([(3, "risky", {})], statements=[(4, 0), (5, 0)]))
        out = self.result(report)
        self.assertEqual(out["status"], "absent")
        self.assertEqual(out["findings"], [])

    def test_a_cobertura_report_without_complexity_is_reported_as_absent(self):
        self.change_lines("src/Foo.php", [5])
        report = self.report(cobertura([("risky", None, [(4, 0), (5, 0)])]))
        self.assertEqual(self.result(report)["status"], "absent")

    def test_an_unreadable_report_is_reported_as_absent(self):
        self.change_lines("src/Foo.php", [5])
        report = self.report("not xml at all")
        self.assertEqual(self.result(report)["status"], "absent")

    def test_a_missing_report_is_reported_as_absent(self):
        self.change_lines("src/Foo.php", [5])
        self.assertEqual(self.result(os.path.join(self.tmpdir.name, "none.xml"))["status"], "absent")


class TestUsage(CrapTestCase):
    def test_a_range_git_cannot_resolve_exits_two(self):
        report = self.report(clover([(3, "risky", {"complexity": 10})]))
        proc = self.run_crap(report, diff_range="nope..HEAD")
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(proc.stdout, "")


if __name__ == "__main__":
    unittest.main()

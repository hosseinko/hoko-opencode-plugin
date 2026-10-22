#!/usr/bin/env python3
"""
crap.py — scores the methods a run changed for CRAP (change risk anti-pattern), so the
final quality gate can flag complex code that its tests barely cover.

Ships with the `hoko` plugin.

    crap.py --report <clover.xml|cobertura.xml> --range <base>..HEAD --max <n> [--root <repo>]

Parses a clover or cobertura coverage report with the standard library only, finds the
lines `git diff -U0 <range>` changed, and keeps the methods whose line span overlaps one
of them. A method's score is `complexity² × (1 − coverage)³ + complexity`, with coverage
as a fraction. When the report already carries a per-method `crap` value (PHPUnit's
clover does), that value is used as it stands. Complexity comes from the report's own
`complexity` attribute.

Clover names only a method's first line, so the method is taken to run up to the line
before the next method, and its coverage is the share of statements in that span that ran.

Prints one JSON object:

    {"status": "ok", "findings": [{"file", "line", "method", "complexity", "coverage",
                                   "crap"}, ...]}

`findings` holds every changed method scoring above `--max`, worst first. When the report
carries no complexity data — or cannot be read — the status is `absent` and `findings`
is empty: nothing was scored, which is not the same as nothing being over the threshold.

Exit 0 on a printed result, 2 on a usage error or a range git cannot resolve.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

HUNK = re.compile(r"^@@ -\S+ \+(\d+)(?:,(\d+))? @@")


def changed_lines(root, diff_range):
    proc = subprocess.run(
        ["git", "-c", "core.quotepath=off", "diff", "-U0", "--no-color", "--no-ext-diff",
         "--src-prefix=a/", "--dst-prefix=b/", diff_range, "--"],
        cwd=root, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"git diff {diff_range} failed")

    changed = {}
    current = None
    for line in proc.stdout.splitlines():
        if line.startswith("+++ "):
            target = line[4:]
            current = target[2:] if target.startswith("b/") else None
            if current is not None:
                changed.setdefault(current, set())
            continue
        match = HUNK.match(line)
        if match and current is not None:
            start = int(match.group(1))
            count = 1 if match.group(2) is None else int(match.group(2))
            changed[current].update(range(start, start + count))
    return {path: lines for path, lines in changed.items() if lines}


def match_changed(report_path, root, changed):
    candidate = report_path
    if os.path.isabs(candidate):
        try:
            candidate = os.path.relpath(candidate, root)
        except ValueError:
            pass
    candidate = candidate.replace(os.sep, "/")
    if candidate.startswith("./"):
        candidate = candidate[2:]
    if candidate in changed:
        return candidate
    for path in changed:
        if candidate.endswith("/" + path) or path.endswith("/" + candidate):
            return path
    return None


def crap_score(complexity, coverage):
    return complexity ** 2 * (1 - coverage) ** 3 + complexity


def number(value):
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def clover_methods(tree):
    for file_node in tree.iter("file"):
        name = file_node.get("name") or file_node.get("path")
        if not name:
            continue
        lines = []
        for node in file_node.iter("line"):
            num = number(node.get("num"))
            if num is not None:
                lines.append((int(num), node))
        lines.sort(key=lambda item: item[0])

        starts = [(num, node) for num, node in lines if node.get("type") == "method"]
        statements = [(num, node) for num, node in lines if node.get("type") != "method"]
        last_line = lines[-1][0] if lines else 0

        for index, (start, node) in enumerate(starts):
            end = starts[index + 1][0] - 1 if index + 1 < len(starts) else max(last_line, start)
            end = max(end, start)
            span = [n for num, n in statements if start <= num <= end]
            if span:
                covered = sum(1 for n in span if (number(n.get("count")) or 0) > 0)
                coverage = covered / len(span)
            else:
                coverage = 1.0 if (number(node.get("count")) or 0) > 0 else 0.0
            yield {
                "file": name,
                "method": node.get("name") or f"line {start}",
                "start": start,
                "end": end,
                "complexity": number(node.get("complexity")),
                "coverage": coverage,
                "crap": number(node.get("crap")),
            }


def cobertura_methods(tree):
    for class_node in tree.iter("class"):
        name = class_node.get("filename")
        if not name:
            continue
        for method in class_node.iter("method"):
            numbers = []
            hits = []
            for node in method.iter("line"):
                num = number(node.get("number"))
                if num is not None:
                    numbers.append(int(num))
                    hits.append((number(node.get("hits")) or 0) > 0)
            if not numbers:
                continue
            coverage = number(method.get("line-rate"))
            if coverage is None:
                coverage = sum(hits) / len(hits)
            yield {
                "file": name,
                "method": method.get("name") or f"line {min(numbers)}",
                "start": min(numbers),
                "end": max(numbers),
                "complexity": number(method.get("complexity")),
                "coverage": coverage,
                "crap": number(method.get("crap")),
            }


def read_methods(report):
    tree = ET.parse(report).getroot()
    if tree.tag != "coverage":
        raise ValueError("not a clover or cobertura coverage report")
    if tree.find(".//packages") is not None or tree.get("line-rate") is not None:
        return list(cobertura_methods(tree))
    return list(clover_methods(tree))


def score(methods, root, changed, maximum):
    findings = []
    for method in methods:
        complexity = method["complexity"]
        if complexity is None:
            continue
        path = match_changed(method["file"], root, changed)
        if path is None:
            continue
        touched = changed[path]
        if not any(method["start"] <= line <= method["end"] for line in touched):
            continue
        value = method["crap"] if method["crap"] is not None else crap_score(complexity, method["coverage"])
        if value > maximum:
            findings.append({
                "file": path,
                "line": method["start"],
                "method": method["method"],
                "complexity": complexity,
                "coverage": round(method["coverage"], 4),
                "crap": round(value, 2),
            })
    findings.sort(key=lambda f: (-f["crap"], f["file"], f["line"]))
    return findings


def main():
    parser = argparse.ArgumentParser(prog="crap.py", description=__doc__)
    parser.add_argument("--report", required=True, help="a clover or cobertura XML coverage report")
    parser.add_argument("--range", dest="diff_range", required=True, help="the git range, <base>..HEAD")
    parser.add_argument("--max", dest="maximum", required=True, type=float, help="the CRAP threshold")
    parser.add_argument("--root", help="the repository root (default: the current directory)")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve() if args.root else Path.cwd()

    try:
        changed = changed_lines(root, args.diff_range)
    except (RuntimeError, OSError) as error:
        print(f"crap.py: {error}", file=sys.stderr)
        return 2

    try:
        methods = read_methods(args.report)
    except (ET.ParseError, ValueError, OSError) as error:
        print(json.dumps({"status": "absent", "findings": [], "reason": f"unreadable report: {error}"}))
        return 0

    if not any(m["complexity"] is not None for m in methods):
        print(json.dumps({"status": "absent", "findings": [], "reason": "the report carries no complexity data"}))
        return 0

    print(json.dumps({"status": "ok", "findings": score(methods, str(root), changed, args.maximum)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

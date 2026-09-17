#!/usr/bin/env python3
"""Run a Go module's tests and summarise coverage.

    go list -f ... ./...              the package set and test-file presence
    go test ./... -coverprofile=<f>   per-package coverage and the test result
    go tool cover -func=<f>           the total

A missing `go` is a hard error. A failing test suite exits non-zero.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile

LIST_FORMAT = (
    '{{.ImportPath}}\t'
    '{{join .GoFiles ","}}\t'
    '{{join .TestGoFiles ","}}\t'
    '{{join .XTestGoFiles ","}}'
)


def list_command():
    return ["go", "list", "-f", LIST_FORMAT, "./..."]


def test_command(profile):
    return ["go", "test", "./...", f"-coverprofile={profile}"]


def cover_command(profile):
    return ["go", "tool", "cover", f"-func={profile}"]


def parse_packages(output):
    packages = []
    for line in output.splitlines():
        fields = line.split("\t")
        if len(fields) < 4:
            continue
        packages.append(tuple(fields[:4]))
    return packages


def untested_packages(packages):
    return [path for path, gofiles, testfiles, xtestfiles in packages
            if gofiles and not testfiles and not xtestfiles]


def parse_coverage(output):
    coverage = {}
    for line in output.splitlines():
        match = re.match(r"^ok\s+(\S+)\s+.*?coverage:\s+([0-9.]+)%", line)
        if match:
            coverage[match.group(1)] = match.group(2)
    return coverage


def parse_total(output):
    for line in output.splitlines():
        match = re.match(r"^total:\s+.*?([0-9.]+)%", line)
        if match:
            return match.group(1)
    return None


def run():
    go = shutil.which("go")
    if go is None:
        print("error: go — not installed; install the Go toolchain to run tests", file=sys.stderr)
        return 1

    listing = subprocess.run([go, *list_command()[1:]], capture_output=True, text=True)
    if listing.returncode != 0:
        print(listing.stdout, end="")
        print(listing.stderr, end="", file=sys.stderr)
        return listing.returncode
    packages = parse_packages(listing.stdout)

    fd, profile = tempfile.mkstemp(suffix=".cover")
    os.close(fd)
    try:
        tests = subprocess.run([go, *test_command(profile)[1:]], capture_output=True, text=True)
        print(tests.stdout, end="")
        if tests.stderr:
            print(tests.stderr, end="", file=sys.stderr)
        coverage = parse_coverage(tests.stdout)

        total = None
        cover = subprocess.run([go, *cover_command(profile)[1:]], capture_output=True, text=True)
        if cover.returncode == 0:
            total = parse_total(cover.stdout)
    finally:
        if os.path.exists(profile):
            os.unlink(profile)

    print()
    print("coverage by package:")
    for path, percent in coverage.items():
        print(f"{path}\t{percent}%")
    if total is not None:
        print(f"total: {total}%")
    missing = untested_packages(packages)
    if missing:
        print("packages with Go files but no test file:")
        for path in missing:
            print(f"  {path}")

    return tests.returncode


def main():
    return run()


if __name__ == "__main__":
    sys.exit(main())

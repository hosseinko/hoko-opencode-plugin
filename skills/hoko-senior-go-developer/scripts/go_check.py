#!/usr/bin/env python3
"""Run a Go module's check pipeline in the order the tooling reference prescribes.

gofmt -l . -> go vet ./... -> golangci-lint run -> govulncheck ./...

A tool that is not installed is skipped, not failed. Any real failure makes the
script exit non-zero, including a non-empty `gofmt -l` listing at exit 0.
"""

import shutil
import subprocess
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class Step:
    argv: tuple
    fail_on_output: bool = False


def check_steps():
    return [
        Step(("gofmt", "-l", "."), fail_on_output=True),
        Step(("go", "vet", "./...")),
        Step(("golangci-lint", "run")),
        Step(("govulncheck", "./...")),
    ]


def run():
    failures = 0
    for step in check_steps():
        command = " ".join(step.argv)
        tool = shutil.which(step.argv[0])
        if tool is None:
            print(f"skipped: {step.argv[0]} — not installed")
            continue
        print(f"$ {command}")
        result = subprocess.run([tool, *step.argv[1:]], capture_output=True, text=True)
        if result.stdout:
            print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
        if result.stderr:
            print(result.stderr, end="" if result.stderr.endswith("\n") else "\n")
        failed = result.returncode != 0 or (step.fail_on_output and bool(result.stdout.strip()))
        if failed:
            print(f"failed: {command} (exit {result.returncode})")
            failures += 1
    if failures:
        print(f"{failures} check{'s' if failures != 1 else ''} failed")
        return 1
    print("all checks passed")
    return 0


def main():
    return run()


if __name__ == "__main__":
    sys.exit(main())

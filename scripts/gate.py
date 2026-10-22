#!/usr/bin/env python3
"""
gate.py — runs one gate command and reports its own exit status.

Ships with the `hoko` plugin.

    gate.py --command <cmd> [--cwd <dir>]

Runs the command with its output captured to a temp log, prints the last 40 lines of
that log plus the command's own exit status, and exits with that status. This replaces
the `log=$(mktemp); … tail -40` block duplicated verbatim in `agents/hoko-code-reviewer.md`
and `agents/hoko-quality-assurance.md`: piping a command straight into `tail` reports
`tail`'s exit status, not the command's, so a failing gate can read back as a pass.
Capturing to a file and reading it back afterwards never has that failure mode.
"""

import argparse
import subprocess
import sys
import tempfile


def run(command, cwd):
    fd, log_path = tempfile.mkstemp(prefix="hoko-gate-")
    with open(fd, "w", encoding="utf-8") as log:
        result = subprocess.run(
            command, shell=True, cwd=cwd, stdout=log, stderr=subprocess.STDOUT,
        )
    with open(log_path, encoding="utf-8", errors="replace") as log:
        lines = log.readlines()
    return result.returncode, lines, log_path


def main():
    parser = argparse.ArgumentParser(prog="gate.py", description=__doc__)
    parser.add_argument("--command", required=True, help="the gate command to run")
    parser.add_argument("--cwd", help="directory to run it in (default: the current one)")
    args = parser.parse_args()

    status, lines, log_path = run(args.command, args.cwd)
    for line in lines[-40:]:
        sys.stdout.write(line)
    print(f"exit: {status}  (log: {log_path})")
    return status


if __name__ == "__main__":
    sys.exit(main())

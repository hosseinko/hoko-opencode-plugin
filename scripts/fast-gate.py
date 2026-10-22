#!/usr/bin/env python3
"""
fast-gate.py — the mechanical health check every plan step, and the conductor's own
preflight, runs instead of a review.

Ships with the `hoko` plugin.

    fast-gate.py [--root <repo>]

Resolves the analyser and test commands with `commands.py` and runs each through
`gate.py`, so a gate's own exit status is what counts, not `tail`'s. The test gate is
the `unit` command, falling back to the `suite` command when the repository names no
`unit` command — this is what makes the gate work on Node and Python projects, where
`commands.py` never resolves `unit`. Prints the command and result for each gate that
ran. A gate with no resolved command is printed as skipped rather than counted as a
failure; when both are skipped, an extra warning line says nothing was checked.

This is a whole-project health check, not a per-step diff scope check: it reads no
plan, takes no step number, and runs no git command of its own. A step that turns the
project red is what fails it, not a changed file the step never named.

On a failing gate, prints the last 40 lines of that command's own output and the path
to its full log, so the runner never has to go digging for what broke.

Exit 0 when every gate that ran passed, 1 when any gate that ran failed, 2 when neither
gate had a command to run (nothing was checked at all).
"""

import argparse
import sys
from pathlib import Path

import commands
import gate as gate_runner


def resolve_test_command(resolved):
    unit = resolved.get("unit")
    if unit is not None:
        return "tests", unit
    return "tests", resolved.get("suite")


def main():
    parser = argparse.ArgumentParser(prog="fast-gate.py", description=__doc__)
    parser.add_argument("--root", help="the repository root (default: the current directory)")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve() if args.root else Path.cwd()

    resolved = commands.build(root)
    gates = [("analyse", resolved.get("analyse")), resolve_test_command(resolved)]

    findings = []
    skipped = 0
    for name, cmd in gates:
        if cmd is None:
            print(f"{name}: no command found — skipped")
            skipped += 1
            continue
        status, lines, log_path = gate_runner.run(cmd, str(root))
        verdict = "pass" if status == 0 else "fail"
        print(f"{name}: {cmd} — {verdict} (exit {status})")
        if status != 0:
            for line in lines[-40:]:
                sys.stdout.write(line)
            print(f"{name}: log at {log_path}")
            findings.append(f"{name}: {cmd} — exit {status}")

    if skipped == len(gates):
        print("unchecked: no gate command found")
        return 2

    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())

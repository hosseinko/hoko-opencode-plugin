#!/usr/bin/env python3
"""
step-commit.py — gates, commits and ticks one step of a plan run, so "gate before
commit, tick after commit" is enforced in code instead of prose.

Ships with the `hoko` plugin.

    step-commit.py --plan <abs plan> --step <N> \\
                    (--message-file <path|-> | --no-op "<reason>") [--root <repo>]

Run by the conductor once per step, in place of writing the commit itself. `--root`
defaults to the git toplevel of the current directory. `--message-file -` reads the
message from stdin, which is how the conductor passes its own heredoc.

Stops at the first failure and prints what it saw at each stage:

1. Refuses to run on `main`, `master`, `staging` or `develop` (exit 3).
2. In message mode, validates the mechanical parts of `hoko-commit`'s format — a
   full-stopped summary line, a blank second line before any body, bullets or
   indented continuations, no line over 72 characters, no `Co-Authored-By` or
   `Generated with` trailer — and names every broken rule (exit 5).
3. Prints `git status --short` and `git diff --stat HEAD`.
4. Refuses a clean tree in message mode, or a dirty tree in `--no-op` mode (exit 4).
5. Runs `fast-gate.py` as a subprocess and passes its output through verbatim, and
   writes its `check.result` event (`fast-gate`: exit 0 `passed`, 1 `failed`, 2
   `skipped`, anything else `error`). A failing gate stops here (exit 1) with nothing
   staged. A gate with nothing to check prints `gate: unchecked` and carries on.
6. In message mode, appends the branch's ticket key as the message's own last line when
   it is not already there, stages every change and commits with hooks enabled. A failed
   commit stops here (exit 6) with no tick.
7. Ticks the step's box in the plan's `## Progress` section and marks the step `done`
   in the plan's `progress.json` with the commit sha, or the no-op reason, writes the
   step's `stage.completed` event, then reports what landed. Exit 0.

Events go to the run `plan-progress.py start` opened (the `run_id` in `progress.json`);
a plan with no run id writes none, and an event that cannot be written never changes the
exit status.
"""

import argparse
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import progress

SCRIPTS_DIR = Path(__file__).resolve().parent

PROTECTED_BRANCHES = {"main", "master", "staging", "develop"}
TICKET_RE = re.compile(r"[A-Z][A-Z0-9]+-\d+")
TRAILER_RE = re.compile(r"Co-Authored-By|Generated with", re.I)


class StepError(Exception):
    """Carries the exit code alongside the message step-commit reports and stops on."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def run_git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)


def git_toplevel(start):
    result = subprocess.run(
        ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise StepError(3, f"not a git repository: {result.stderr.strip()}")
    return Path(result.stdout.strip())


def current_branch(root):
    result = run_git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if result.returncode != 0:
        raise StepError(3, f"cannot read the current branch: {result.stderr.strip()}")
    return result.stdout.strip()


def validate_message(text):
    """The mechanical parts of `hoko-commit`'s format; every broken rule, by name."""
    failures = []
    lines = text.splitlines()

    if not lines or not lines[0].strip():
        failures.append("summary: the message has no summary line")
    elif not lines[0].endswith("."):
        failures.append("summary: the summary line does not end with a full stop")

    body = lines[1:]
    if body:
        if body[0] != "":
            failures.append("blank-line: the second line is not blank")
        for line in body[1:]:
            if line == "" or line.startswith("* ") or line[:1] in (" ", "\t"):
                continue
            if TICKET_RE.fullmatch(line.strip()):
                continue
            failures.append(f"bullet: {line!r} is not a bullet or an indented continuation")

    for number, line in enumerate(lines, start=1):
        if len(line) > 72:
            failures.append(f"line-length: line {number} is {len(line)} characters, over 72")

    if TRAILER_RE.search(text):
        failures.append("trailer: the message carries a Co-Authored-By or Generated with trailer")

    return failures


def read_message(message_file):
    if message_file == "-":
        return sys.stdin.read()
    path = Path(message_file).expanduser()
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise StepError(5, f"cannot read {path}: {exc}")


def append_ticket_key(text, branch):
    """The branch's ticket key as the message's own last line, added only when it is
    not already there; the text is otherwise unchanged but for a trailing newline."""
    match = TICKET_RE.search(branch)
    if match is None:
        return text if text.endswith("\n") else text + "\n"
    key = match.group(0)
    stripped = text.rstrip("\n")
    lines = stripped.split("\n")
    if lines and lines[-1].strip() == key:
        return stripped + "\n"
    return stripped + "\n\n" + key + "\n"


def run_fast_gate(root):
    script = SCRIPTS_DIR / "fast-gate.py"
    result = subprocess.run(
        [sys.executable, str(script), "--root", str(root)], capture_output=True, text=True,
    )
    sys.stdout.write(result.stdout)
    sys.stdout.write(result.stderr)
    return result.returncode


GATE_STATUSES = {0: "passed", 1: "failed", 2: "skipped"}


def emit_event(root, plan, type_, payload):
    """Writes one event for the run the plan's `progress.json` names; silent without
    one."""
    document = progress.load(progress.path_for(plan))
    if document is None:
        return
    try:
        context = progress.step_context(document, plan, payload["step"])
    except (KeyError, TypeError):
        context = {}
    progress.emit(plan, document, type_,
                  {"stage": "Implement", "cycle": progress.document_cycle(document),
                   **payload, **context}, root)


def run_tick(plan, step, commit=None, note=None):
    script = SCRIPTS_DIR / "plan-progress.py"
    command = [sys.executable, str(script), "tick", "--plan", str(plan), "--step", str(step)]
    if commit is not None:
        command += ["--commit", commit]
    if note is not None:
        command += ["--note", note]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise StepError(result.returncode or 1, result.stderr.strip() or "failed to tick the plan")


def run(args):
    root = Path(args.root).expanduser().resolve() if args.root else git_toplevel(Path.cwd())

    branch = current_branch(root)
    if branch in PROTECTED_BRANCHES:
        raise StepError(3, f"refusing to run on protected branch {branch!r}")

    message = None
    if args.message_file is not None:
        message = read_message(args.message_file)
        failures = validate_message(message)
        if failures:
            print("step-commit: the message breaks the commit-message format:")
            for rule in failures:
                print(f"- {rule}")
            return 5

    status = run_git(root, "status", "--short").stdout
    diffstat = run_git(root, "diff", "--stat", "HEAD").stdout
    sys.stdout.write(status)
    sys.stdout.write(diffstat)
    dirty = bool(status.strip())

    if args.message_file is not None and not dirty:
        raise StepError(4, "the tree is clean; nothing to commit")
    if args.no_op is not None and dirty:
        raise StepError(4, f"the tree is dirty; --no-op {args.no_op!r} does not apply")

    started = time.monotonic()
    gate_status = run_fast_gate(root)
    emit_event(root, args.plan, "check.result",
               {"check": "fast-gate", "status": GATE_STATUSES.get(gate_status, "error"),
                "duration_ms": int((time.monotonic() - started) * 1000),
                "exit_code": gate_status, "step": args.step})
    if gate_status == 1:
        return 1
    if gate_status == 2:
        print("gate: unchecked")

    if args.message_file is not None:
        final_message = append_ticket_key(message, branch)

        add_result = run_git(root, "add", "-A")
        if add_result.returncode != 0:
            raise StepError(6, f"git add failed: {add_result.stderr.strip()}")

        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as handle:
            handle.write(final_message)
            message_path = handle.name
        try:
            commit_result = run_git(root, "commit", "-F", message_path)
        finally:
            Path(message_path).unlink(missing_ok=True)

        if commit_result.returncode != 0:
            print(commit_result.stdout + commit_result.stderr)
            return 6

        sha = run_git(root, "rev-parse", "--short", "HEAD").stdout.strip()
        run_tick(args.plan, args.step, commit=sha)
        emit_event(root, args.plan, "stage.completed",
                   {"model": progress.stage_model("Implement"), "outcome": "done",
                    "step": args.step, "commit": sha, "no_op": False})
        subject = run_git(root, "log", "-1", "--pretty=%s").stdout.strip()
        print(f"commit: {sha} {subject}")
    else:
        run_tick(args.plan, args.step, note=args.no_op)
        emit_event(root, args.plan, "stage.completed",
                   {"model": progress.stage_model("Implement"), "outcome": "done",
                    "step": args.step, "commit": None, "no_op": True})
        print(f"no-op: {args.no_op}")

    print(f"tick: step {args.step}")
    return 0


def main():
    parser = argparse.ArgumentParser(prog="step-commit.py", description=__doc__)
    parser.add_argument("--plan", required=True, help="absolute path to the plan file")
    parser.add_argument("--step", required=True, type=int, help="the step number to tick")
    parser.add_argument("--root", help="the repository root (default: the git toplevel of the cwd)")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--message-file", help="path to the commit message, or - for stdin")
    mode.add_argument("--no-op", help="why this step needed no commit")
    args = parser.parse_args()

    try:
        return run(args)
    except StepError as exc:
        print(f"step-commit: {exc.message}")
        return exc.code


if __name__ == "__main__":
    sys.exit(main())

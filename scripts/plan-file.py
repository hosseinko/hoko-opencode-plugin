#!/usr/bin/env python3
"""
plan-file.py — files an approved plan into its journal entry, round by round.

Ships with the `hoko` opencode plugin. One mode:

  file   `plan-file.py file --plan <path> [--session <id>] [--project <name>]` —
         resolves the project (the `--project` override, else the plan's own
         `Project:` line, else `journal.resolve_project`), records a `Project:` line
         under the plan's title, hands the plan and the best available prompt anchor
         to `journal.py write`, records a `Journal:` line naming the `plan-01.md` it
         created, and registers `--session` against that entry as round 1 role `plan`.
         A plan whose `Journal:` line already names an existing file is not re-filed.
         Prints the `plan-01.md` path.

Journaling is opt-in: with no journalPath configured, only the `Project:` line is
written and the plan's own path is printed.
"""

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import journal
import settings

SCRIPTS_DIR = Path(__file__).resolve().parent
JOURNAL_PY = SCRIPTS_DIR / "journal.py"
PROJECT_LINE_RE = re.compile(r"^Project:\s*(.+)$", re.M)


def die(message):
    print(f"plan-file: {message}", file=sys.stderr)
    sys.exit(1)


def ensure_header_line(text, key, value):
    """`<key>: <value>` under the plan's `# ` title, or at the top when it has none —
    right after an existing `Project:` line when adding `Journal:`, so the two stay in
    order however far apart the two calls that add them land. A no-op when the line is
    already there."""
    if re.search(rf"^{key}:\s*.*$", text, re.M):
        return text
    line = f"{key}: {value}\n"
    if key != "Project":
        project_match = re.search(r"^Project:\s*.*$", text, re.M)
        if project_match:
            idx = project_match.end()
            if idx < len(text) and text[idx] == "\n":
                idx += 1
            return text[:idx] + line + text[idx:]
    title_match = re.search(r"^#\s+.*$", text, re.M)
    if title_match:
        idx = title_match.end()
        if idx < len(text) and text[idx] == "\n":
            idx += 1
        return text[:idx] + line + text[idx:]
    return line + text


def own_project(text):
    """The plan's own `Project:` line, already present before filing. None when it has
    none yet."""
    match = PROJECT_LINE_RE.search(text)
    return match.group(1).strip() if match else None


def temp_prompt(content):
    handle = tempfile.NamedTemporaryFile(mode="w", suffix=".prompt", delete=False, encoding="utf-8")
    handle.write(content)
    handle.close()
    path = Path(handle.name)
    return path, lambda: path.unlink(missing_ok=True)


def prompt_source(session_anchor):
    """The session's own captured prompt, else a placeholder — a `(file, cleanup)`
    pair. The session anchor is handed to `journal.py write` as-is, so its own rotation
    retires it."""
    if session_anchor is not None and session_anchor.is_file():
        return session_anchor, None
    return temp_prompt("_Prompt not captured._")


def run_journal(*args):
    result = subprocess.run(
        [sys.executable, str(JOURNAL_PY), *args],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        die(result.stderr.strip() or f"journal.py {args[0]} failed")
    return result.stdout.strip()


def register(session_id, entry):
    if not session_id:
        return
    run_journal("register", "--entry", str(entry), "--session", session_id,
                "--round", "1", "--role", "plan")


def cmd_file(args):
    plan_path = Path(args.plan).expanduser()
    if not plan_path.is_file():
        die(f"no plan file at {plan_path}")
    plan_path = plan_path.resolve()

    session_id = args.session or None
    session_anchor = journal.state_file(session_id) if session_id else None

    text = plan_path.read_text(encoding="utf-8")
    existing = journal.journal_plan(text)
    if existing is not None and existing.is_file():
        if settings.get("journalPath"):
            register(session_id, existing.parent)
        print(existing)
        return

    project = journal.resolve_project(
        args.project or own_project(text), plan_path, session_anchor)
    plan_path.write_text(ensure_header_line(text, "Project", project), encoding="utf-8")

    if not settings.get("journalPath"):
        print(plan_path)
        return

    prompt_file, cleanup = prompt_source(session_anchor)
    try:
        plan_copy = Path(run_journal(
            "write", "--plan", str(plan_path), "--prompt-file", str(prompt_file),
            "--project", project,
        ))
    finally:
        if cleanup:
            cleanup()

    text = ensure_header_line(plan_path.read_text(encoding="utf-8"), "Journal", str(plan_copy))
    plan_path.write_text(text, encoding="utf-8")

    register(session_id, plan_copy.parent)
    print(plan_copy)


def main():
    parser = argparse.ArgumentParser(prog="plan-file.py", description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)

    file_cmd = modes.add_parser("file", help="file an approved plan, or print its existing journal entry")
    file_cmd.add_argument("--plan", required=True, help="absolute path to the plan file")
    file_cmd.add_argument("--session", help="the approving session, registered as round 1 role plan")
    file_cmd.add_argument("--project", help="override the project name")

    args = parser.parse_args()
    if args.mode == "file":
        cmd_file(args)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
analytics.py — where a journal entry's run analytics live.

A journal entry's analytics files are its session registry `sessions.json`, its invoice
`invoice.json` and `invoice.md` and the closing `events-<NN>.jsonl` copies of its runs'
event logs. With `analyticsPath` set they live in `<analyticsPath>/<project>/<entry>/`,
the project and entry names being those of the journal entry's parent and own folder; with
it empty they stay in the journal entry itself. The analytics folder also holds
`entry.json`, the link back: the journal entry's absolute path, project and entry names,
the ids of the runs that completed against it and the ids of its registered sessions.

Imported by `journal.py`, `invoice.py`, `plan-progress.py` and `task.py`, so it imports
only `settings`. A folder that cannot be created or written is a note on stderr naming
it, never an exception: the approval path swallows every one silently.
"""

import contextlib
import json
import os
import sys
from pathlib import Path

import settings

SESSIONS_FILE = "sessions.json"
ENTRY_FILE = "entry.json"


def expand(path):
    return Path(os.path.expandvars(path)).expanduser()


def analytics_root():
    """The analytics root from settings (`analyticsPath`, `hoko.json` /
    `~/.config/opencode/hoko.json` / `HOKO_ANALYTICS_PATH`), or None when it is unset —
    the analytics then stay in the journal entry."""
    path = settings.get("analyticsPath")
    return expand(path) if path else None


def absolute(path):
    return Path(os.path.abspath(Path(path).expanduser()))


def folder_for(entry):
    """The analytics folder of a journal entry folder: `<analyticsPath>/<project>/<entry>`
    whose names are the entry's parent folder's and its own, or the entry itself when
    `analyticsPath` is empty. An analytics folder maps to itself."""
    entry = absolute(entry)
    root = analytics_root()
    if root is None:
        return entry
    return absolute(root) / entry.parent.name / entry.name


def journal_entry_of(path):
    """The journal entry folder a path names: the path itself, or, when it is an analytics
    folder, the entry its `entry.json` links to, else the journal root's folder of the same
    project and name. None when an analytics folder names no journal entry."""
    path = absolute(path)
    root = analytics_root()
    if root is None or path.parent.parent != absolute(root):
        return path
    linked = read_link(path).get("journal_entry")
    if isinstance(linked, str) and linked:
        return Path(linked)
    journal_path = settings.get("journalPath")
    if journal_path:
        return absolute(expand(journal_path)) / path.parent.name / path.name
    return None


@contextlib.contextmanager
def guard(folder):
    """Runs the body, which writes into `folder`; an OSError becomes a note on stderr
    naming the folder, and the body's remaining writes are skipped."""
    try:
        yield
    except OSError as exc:
        print(f"analytics: cannot write {folder}: {exc}", file=sys.stderr)


def write_atomic(path, text):
    scratch = path.with_name(path.name + ".tmp")
    scratch.write_text(text, encoding="utf-8")
    os.replace(scratch, path)


def read_link(folder):
    """The folder's `entry.json` as an object; an empty one when it is missing, unreadable
    or not a JSON object."""
    try:
        data = json.loads((folder / ENTRY_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def session_ids(folder):
    """Every session id of the folder's `sessions.json`, each once, first seen first."""
    try:
        rows = json.loads((folder / SESSIONS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(rows, list):
        return []
    ids = []
    for row in rows:
        if isinstance(row, dict) and row.get("session_id") and str(row["session_id"]) not in ids:
            ids.append(str(row["session_id"]))
    return ids


def link(entry, run_id=None):
    """Rewrites `entry.json` in the journal entry's analytics folder, atomically: the
    entry's absolute path, its project and name, the run ids it already lists plus
    `run_id` once, and the session ids of the folder's `sessions.json`. Writes nothing
    when `analyticsPath` is empty or `entry` is None."""
    if entry is None or analytics_root() is None:
        return
    entry = absolute(entry)
    folder = folder_for(entry)
    with guard(folder):
        folder.mkdir(parents=True, exist_ok=True)
        listed = read_link(folder).get("run_ids")
        run_ids = [item for item in listed if isinstance(item, str)] if isinstance(listed, list) else []
        if run_id and str(run_id) not in run_ids:
            run_ids.append(str(run_id))
        write_atomic(folder / ENTRY_FILE, json.dumps({
            "journal_entry": str(entry), "project": entry.parent.name, "entry": entry.name,
            "run_ids": run_ids, "session_ids": session_ids(folder)}, indent=2) + "\n")

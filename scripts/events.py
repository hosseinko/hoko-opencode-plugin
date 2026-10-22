#!/usr/bin/env python3
"""
events.py — the one writer of a run's events, in the hoko-code event schema.

Ships with the `hoko` plugin. Not a CLI: `progress.py`, `step-commit.py` and
`plan-progress.py` import it.

Every event is one JSON line `{v, event_id, run_id, seq, ts, type, project, payload}`
appended to `<repo root>/<eventsDir>/<run_id>/events.jsonl` (`.ai/runs` by default). The
line is written with a single `os.write` on an `O_APPEND` descriptor, and `seq` is
assigned under an exclusive `flock` on `events.jsonl.lock`, so processes writing for one
run number their events 1, 2, 3 … with no gap and no repeat. The events directory's top
folder gets a `.gitignore` holding `*` before the run directory exists, so `git add -A`
never stages an event.

Writing events never fails the caller. A failed write drops an `events.disabled` marker
in the run directory, prints `events not recorded: <reason>` once on stderr, and every
later `emit` for that run writes nothing. With the `events` setting off nothing is
written at all.
"""

import fcntl
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import invoice
import settings

VERSION = 1
FILE = "events.jsonl"
LOCK = "events.jsonl.lock"
DISABLED = "events.disabled"
CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
RUN_ID = re.compile(r"^[0-9A-Za-z_-]+$")
BACKEND = "opencode"

AGENT_STAGES = {
    "hoko-plan-executor": "Implement",
    "hoko-quality-assurance": "QA",
    "hoko-final-reviewer": "Review",
    "hoko-spec-writer": "Spec",
    "hoko-specifier": "Refine",
    "hoko-planner": "Plan",
}
STAGE_ROLES = {
    "Refine": "planner",
    "Spec": "planner",
    "Plan": "planner",
    "Implement": "implementer",
    "QA": "reviewer",
    "Review": "reviewer",
}
DIFF_STATUSES = {"A": "A", "M": "M", "D": "D", "T": "M"}

_noted = False


def ulid(now_ms=None):
    """A 26-character Crockford base32 ULID: 48 bits of millisecond time, 80 random."""
    if now_ms is None:
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    value = (now_ms << 80) | int.from_bytes(os.urandom(10), "big")
    chars = []
    for _ in range(26):
        chars.append(CROCKFORD[value & 31])
        value >>= 5
    return "".join(reversed(chars))


def timestamp():
    """UTC, millisecond precision, `Z` suffix."""
    moment = datetime.now(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def repo_root(start):
    """The git toplevel of `start`, else the current directory's."""
    for candidate in (Path(start), Path.cwd()):
        try:
            result = subprocess.run(
                ["git", "-C", str(candidate), "rev-parse", "--show-toplevel"],
                capture_output=True, text=True, timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if result.returncode == 0 and result.stdout.strip():
            return Path(result.stdout.strip())
    return Path.cwd()


def configured_dir():
    configured = Path(str(settings.get("eventsDir")))
    if ".." in configured.parts:
        raise ValueError("eventsDir must not contain `..`")
    if not configured.is_absolute() and not configured.parts:
        raise ValueError("eventsDir must name a directory below the repository root")
    return configured


def run_directory(root, run_id):
    if not isinstance(run_id, str) or not RUN_ID.match(run_id):
        raise ValueError(f"{run_id!r} is not a usable run id")
    return Path(root) / configured_dir() / run_id


def ignored_top(root):
    """The folder that gets the `.gitignore`: the first path component of `eventsDir`
    below the repo root, or the events directory itself when it is absolute."""
    configured = configured_dir()
    if configured.is_absolute():
        return configured
    return Path(root) / configured.parts[0]


def ensure_ignored(top):
    top.mkdir(parents=True, exist_ok=True)
    try:
        with open(top / ".gitignore", "x", encoding="utf-8") as handle:
            handle.write("*\n")
    except FileExistsError:
        pass


def count_lines(path):
    """The number of newline-terminated lines in `path`, 0 when it does not exist."""
    total = 0
    try:
        with open(path, "rb") as handle:
            while chunk := handle.read(1 << 16):
                total += chunk.count(b"\n")
    except FileNotFoundError:
        return 0
    return total


def has_events(root, run_id):
    try:
        return (run_directory(root, run_id) / FILE).stat().st_size > 0
    except (OSError, ValueError):
        return False


def append(root, run_id, directory, type_, payload):
    ensure_ignored(ignored_top(root))
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = os.open(directory / LOCK, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = directory / FILE
        event = {
            "v": VERSION,
            "event_id": ulid(),
            "run_id": run_id,
            "seq": count_lines(path) + 1,
            "ts": timestamp(),
            "type": type_,
            "project": Path(root).name,
            "payload": payload,
        }
        line = (json.dumps(event, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
                + "\n").encode("utf-8")
        descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            written = os.write(descriptor, line)
        finally:
            os.close(descriptor)
        if written != len(line):
            raise OSError("short write")
        return event
    finally:
        os.close(lock)


def note(reason):
    global _noted
    if not _noted:
        _noted = True
        print(f"events not recorded: {reason}", file=sys.stderr)


def disable(directory, reason):
    try:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        (directory / DISABLED).write_text(reason + "\n", encoding="utf-8")
    except OSError:
        pass
    note(reason)


def emit(root, run_id, type_, payload):
    """Appends one event to the run's file and returns it, or returns None when events
    are off, the run has no id, or the run's writing is disabled. Never raises: a failed
    write disables the run's events and leaves the caller's own outcome alone."""
    if not run_id or not settings.get("events"):
        return None
    directory = None
    try:
        directory = run_directory(root, run_id)
        if (directory / DISABLED).exists():
            return None
        return append(root, run_id, directory, type_, payload)
    except Exception as exc:
        reason = str(exc) or type(exc).__name__
        if directory is None:
            note(reason)
        else:
            disable(directory, reason)
        return None


def files_changed_payload(root, base):
    """The `files.changed` payload: `git diff --name-status --no-renames <base>` as
    `{files: [{status, path}]}` with a type change read as a modification, or
    `{error}` when there is no base or git cannot say."""
    if not base:
        return {"error": "no base commit recorded"}
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "diff", "-z", "--name-status", "--no-renames", base],
            capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"error": str(exc)}
    if result.returncode != 0:
        return {"error": result.stderr.strip() or "git diff failed"}
    fields = result.stdout.split("\0")
    files = []
    for status, path in zip(fields[0::2], fields[1::2]):
        files.append({"status": DIFF_STATUSES.get(status[:1], "M"), "path": path})
    return {"files": files}


def cycle_at(starts, moment):
    """The last cycle of `starts` (`(start, cycle)` pairs, earliest first) that began at or
    before `moment`, or the first cycle when `moment` is earlier or unknown."""
    found = starts[0][1]
    if moment is None:
        return found
    for begun, cycle in starts:
        if begun <= moment:
            found = cycle
    return found


def cycle_starts(cycles):
    """`(start, cycle)` pairs, earliest first, from `[{"cycle": N, "started": ts}]`; an
    entry without a cycle number or a readable start is left out. Empty when `cycles` is
    not a list or holds nothing usable."""
    pairs = []
    for item in cycles if isinstance(cycles, list) else []:
        begun = invoice.parse_time(item.get("started")) if isinstance(item, dict) else None
        number = item.get("cycle") if begun is not None else None
        if isinstance(number, int) and not isinstance(number, bool):
            pairs.append((begun, number))
    return sorted(pairs)


def usage_payloads(calls, cycles=None):
    """One `usage.reported` payload per call row from `invoice.aggregate`. The stage and
    role come from the agent type, or from the invoice row's own role for a planning
    session; an agent type nobody maps is counted as implementation. `cycles` lists when
    each cycle opened, and a call is given the cycle that was running when it started;
    without it every call is cycle 1."""
    starts = cycle_starts(cycles)
    payloads = []
    for call in calls:
        stage = AGENT_STAGES.get(call["agent_type"])
        if stage is None:
            stage = "Plan" if call.get("role") == "plan" else "Implement"
        cycle = cycle_at(starts, invoice.parse_time(call.get("started"))) if starts else 1
        payloads.append({
            "stage": stage,
            "cycle": cycle,
            "role": STAGE_ROLES[stage],
            "backend": BACKEND,
            "model": call["model"],
            "call_id": call["agent_id"],
            "input_tokens": call["input_tokens"],
            "output_tokens": call["output_tokens"],
            "cache_read_tokens": call["cache_read_tokens"],
            "cache_creation_tokens": call["cache_write_5m_tokens"] + call["cache_write_1h_tokens"],
            "cost_usd": call["cost"],
            "cost_source": "computed",
            "duration_ms": call["duration_ms"],
        })
    return payloads

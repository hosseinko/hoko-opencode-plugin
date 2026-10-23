#!/usr/bin/env python3
"""
migrate-analytics.py — moves a journal's analytics into an analytics root.

    migrate-analytics.py <journal root> <analytics root>

For every journal entry, moves its `sessions.json`, `invoice.json`, `invoice.md` and
`events-<NN>.jsonl` copies into `<analytics root>/<project>/<entry>/`, overwriting what
the target already holds. A round with no event copy gains one synthesized from its
`plan-<NN>.md` and `report-<NN>.md` and their modification times: `run.started` at the
plan's, `run.finished` at the report's, under run id `<entry>-r<NN>`. Every filled folder
gets an `entry.json` naming the journal entry and listing its sessions.

The roots are arguments, not settings: the journal the migration empties and the analytics
root it fills are the two places named on the command line. A round with neither a plan
nor a report gives no timestamp and is skipped with a note on stderr. A second run changes
nothing.
"""

import argparse
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import analytics
import events

MOVED_FILES = ("sessions.json", "invoice.json", "invoice.md")
ROUND_FILE = re.compile(r"^(plan|report)-(\d+)\.md$")
EVENT_COPY = re.compile(r"^events-(\d+)\.jsonl$")


def note(message):
    print(f"migrate-analytics: {message}", file=sys.stderr)


def stamp(moment):
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def modified(path):
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)


def round_number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def analytics_files(entry):
    for path in entry.iterdir():
        if path.is_file() and (path.name in MOVED_FILES or EVENT_COPY.match(path.name)):
            yield path


def round_files(entry):
    """`{round: plan-NN.md}` and `{round: report-NN.md}` for the entry's rounds."""
    plans, reports = {}, {}
    for path in entry.iterdir():
        match = ROUND_FILE.match(path.name)
        if match:
            (plans if match.group(1) == "plan" else reports)[int(match.group(2))] = path
    return plans, reports


def event_rounds(folder):
    numbers = set()
    for path in folder.iterdir():
        match = EVENT_COPY.match(path.name)
        if match:
            numbers.add(int(match.group(1)))
    return numbers


def session_rounds(path):
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    if not isinstance(rows, list):
        return set()
    numbers = set()
    for row in rows:
        if isinstance(row, dict):
            number = round_number(row.get("round"))
            if number is not None:
                numbers.add(number)
    return numbers


def invoice_rounds(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    if not isinstance(data, dict):
        return set()
    numbers = set()
    for section in ("sessions", "tasks"):
        rows = data.get(section)
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict):
                    number = round_number(row.get("round"))
                    if number is not None:
                        numbers.add(number)
    rates = data.get("rates")
    if isinstance(rates, dict):
        for key in rates:
            number = round_number(key)
            if number is not None:
                numbers.add(number)
    return numbers


def event(run_id, seq, type_, moment, project, payload):
    return {
        "v": events.VERSION,
        "event_id": events.ulid(int(moment.timestamp() * 1000)),
        "run_id": run_id,
        "seq": seq,
        "ts": stamp(moment),
        "type": type_,
        "project": project,
        "payload": payload,
    }


def synthesized(entry, number, plan, report):
    run_id = f"{entry.name}-r{number:02d}"
    lines = []
    if plan is not None:
        lines.append(event(run_id, len(lines) + 1, "run.started", modified(plan),
                           entry.parent.name,
                           {"source": "plan", "text": plan.read_text(encoding="utf-8"),
                            "backend": events.BACKEND}))
    if report is not None:
        lines.append(event(run_id, len(lines) + 1, "run.finished", modified(report),
                           entry.parent.name, {"status": "done"}))
    return lines


def write_link(entry, folder, run_ids):
    listed = analytics.read_link(folder).get("run_ids")
    kept = [item for item in listed if isinstance(item, str)] if isinstance(listed, list) else []
    for run_id in run_ids:
        if run_id not in kept:
            kept.append(run_id)
    text = json.dumps({
        "journal_entry": str(entry), "project": entry.parent.name, "entry": entry.name,
        "run_ids": kept, "session_ids": analytics.session_ids(folder),
    }, indent=2) + "\n"
    target = folder / analytics.ENTRY_FILE
    try:
        unchanged = target.read_text(encoding="utf-8") == text
    except OSError:
        unchanged = False
    if not unchanged:
        analytics.write_atomic(target, text)


def migrate_entry(entry, root):
    folder = root / entry.parent.name / entry.name
    folder.mkdir(parents=True, exist_ok=True)
    for source in analytics_files(entry):
        shutil.move(str(source), str(folder / source.name))

    plans, reports = round_files(entry)
    present = event_rounds(folder)
    rounds = set(plans) | set(reports) | present
    rounds |= session_rounds(folder / analytics.SESSIONS_FILE)
    rounds |= invoice_rounds(folder / "invoice.json")

    run_ids = []
    for number in sorted(rounds):
        plan, report = plans.get(number), reports.get(number)
        if plan is None and report is None:
            if number not in present:
                note(f"{entry.name} round {number:02d} has neither a plan nor a report; skipped")
            continue
        if number in present:
            continue
        path = folder / f"events-{number:02d}.jsonl"
        analytics.write_atomic(path, "".join(
            json.dumps(line, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"
            for line in synthesized(entry, number, plan, report)))
        run_ids.append(f"{entry.name}-r{number:02d}")
        present.add(number)

    write_link(entry, folder, run_ids)
    return folder


def main(argv=None):
    parser = argparse.ArgumentParser(prog="migrate-analytics.py", description=__doc__)
    parser.add_argument("journal_root", help="the folder holding <project>/<entry> journal entries")
    parser.add_argument("analytics_root", help="the root to move the analytics under")
    args = parser.parse_args(argv)
    journal_root = Path(args.journal_root).expanduser().resolve()
    analytics_root = Path(args.analytics_root).expanduser().resolve()
    if not journal_root.is_dir():
        note(f"no journal root at {journal_root}")
        return 1
    try:
        for project in sorted(journal_root.iterdir()):
            if not project.is_dir():
                continue
            for entry in sorted(project.iterdir()):
                if entry.is_dir():
                    print(migrate_entry(entry, analytics_root))
    except OSError as exc:
        note(str(exc))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

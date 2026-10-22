#!/usr/bin/env python3
"""
plan-progress.py — write and tick the `## Progress` checklist a plan run resumes from.

Ships with the `hoko` plugin.

    plan-progress.py init --plan <path>
    plan-progress.py start --plan <path> --step <N>
    plan-progress.py tick --plan <path> --step <N> [--commit <sha>] [--note <text>]
    plan-progress.py complete --plan <path> --report-file <path>|-
    plan-progress.py abort --plan <path> [--stage Implement|QA|Review] --reason <text>|-

`init` writes the `## Progress` section directly above `## Steps` when the plan has
none, one unchecked `- [ ] <N>. <title>` box per step, titled from the `### <N>.`
headings. When the section already exists it is reconciled instead: every already
checked box stays checked, a step with no box gets one, and a legacy `Status: done`
line left inside a step's own body is dropped from that step and turned into a checked
box instead — the run's durable record is `## Progress`, not a line buried in a step.
It also records the run's base: a `Base: <sha>` line, `HEAD` at the moment of the
first `init`, is written into the header and kept as-is on every later `init` — QA and
the final review diff `<Base>..HEAD`, not whatever HEAD happens to be by then.

`tick` checks exactly one box and changes nothing else in the file, byte for byte.

Every command also keeps `<plan stem>.progress.json` beside the plan (`progress.py`):
`init` creates it with one `pending` entry per step, or reconciles it — step statuses
come from the checklist, every other field is kept — `start` marks a step
`in_progress`, `tick` marks it `done` with the `--commit` sha or the `--note` of a no-op
step, and `complete` marks the run `done`. A failed JSON write prints a note on stderr
and never fails the command; the checklist stays the record a run resumes from.

The same commands write the run's events (`events.py`, the hoko-code schema): `start`
gives the run its id on first use and writes `run.started` once, then `stage.started`
for the step; `complete` writes `files.changed`, one `usage.reported` per subagent call
since the run started, then `run.finished` `done`, journaling on or off, and copies the
events file into the journal entry's analytics folder as `events-<NN>.jsonl` and lists
the run's id in the folder's `entry.json` (`analytics.py`); `abort` marks the run
`stopped` and writes `stage.failed` for the stage it stopped in, then `run.finished`
`failed`. An event that cannot be written never changes a command's exit status.

`complete` sets `Status: complete` in the header and files the report through
`journal.py`'s own `report` routine, so a run closes with one command instead of a
hook chasing the report afterward. It then regenerates `invoice.md` and `invoice.json`
in the entry's analytics folder through `invoice.py`; a failure there prints a note on
stderr and never fails `complete`, and neither does an analytics folder that cannot be
written, which stays a note naming it. When `journalPath` is unset, it sets the status and
says journaling is off, without touching the journal at all.
"""

import argparse
import os
import re
import shutil
import sys
from pathlib import Path

import analytics
import events
import invoice
import journal
import plan_format
import progress

LEGACY_STATUS = re.compile(r"^[ \t]*-?\s*Status:\s*done\s*$\n?", re.M | re.I)


def die(message):
    print(f"plan-progress: {message}", file=sys.stderr)
    sys.exit(1)


def read_plan(path):
    plan = Path(path).expanduser()
    if not plan.is_file():
        die(f"no plan file at {plan}")
    try:
        return plan, plan.read_text(encoding="utf-8")
    except OSError as exc:
        die(f"cannot read {plan}: {exc}")


def configured_journal_root():
    """The journal root, or None when journaling is off."""
    return journal.journal_root()


def strip_legacy_status(steps_body, spans):
    """Drop a `Status: done` line from each step's own body; report who had one."""
    legacy_done = set()
    cleaned = steps_body
    for number, _title, start, end in sorted(spans, key=lambda s: s[2], reverse=True):
        piece = cleaned[start:end]
        new_piece, count = LEGACY_STATUS.subn("", piece)
        if count:
            legacy_done.add(number)
            cleaned = cleaned[:start] + new_piece + cleaned[end:]
    return cleaned, legacy_done


def build_progress_block(steps_info, checked):
    lines = ["## Progress", ""]
    for number, title in steps_info:
        mark = "x" if checked.get(number) else " "
        lines.append(f"- [{mark}] {number}. {title}")
    return "\n".join(lines) + "\n\n"


def splice(text, replacements):
    """Replace each (start, end, new_text) span, in offset order; copy everything else."""
    ordered = sorted(replacements, key=lambda r: r[0])
    out = []
    cursor = 0
    for start, end, new_text in ordered:
        out.append(text[cursor:start])
        out.append(new_text)
        cursor = end
    out.append(text[cursor:])
    return "".join(out)


def cmd_init(args):
    plan, text = read_plan(args.plan)

    found = plan_format.sections(text)
    steps_span = plan_format.section_span(text, "Steps", found)
    if steps_span is None:
        die("the plan has no `## Steps` section")
    steps_start, steps_end = steps_span
    steps_body = text[steps_start:steps_end]

    spans = progress.step_spans(steps_body)
    if not spans:
        die("the `## Steps` section has no `### <N>.` headings")
    cleaned_steps_body, legacy_done = strip_legacy_status(steps_body, spans)
    steps_info = [(number, title) for number, title, _s, _e in spans]

    prog_span = plan_format.section_span(text, "Progress", found)
    checked = {number: True for number in legacy_done}
    if prog_span is not None:
        prog_start, prog_end = prog_span
        for number, was_checked in progress.existing_checked(text[prog_start:prog_end]).items():
            checked[number] = checked.get(number, False) or was_checked

    block = build_progress_block(steps_info, checked)

    if prog_span is not None:
        prog_start, prog_end = prog_span
        replacements = [(steps_start, steps_end, cleaned_steps_body), (prog_start, prog_end, block)]
    else:
        replacements = [(steps_start, steps_end, block + cleaned_steps_body)]
    new_text = splice(text, replacements)

    if plan_format.read_base(new_text) is None:
        sha = progress.git_head(plan.parent)
        if sha is not None:
            new_text = plan_format.write_base(new_text, sha)

    plan.write_text(new_text, encoding="utf-8")
    record(lambda: progress.init(plan, new_text))
    return 0


def record(write):
    """Runs one `progress.json` write and returns the document, or None after a note on
    stderr: the plan's own checklist is the record a run resumes from, so a lost JSON
    write never fails the command that already changed the plan."""
    try:
        return write()
    except (OSError, ValueError) as exc:
        print(f"plan-progress: progress.json not written: {exc}", file=sys.stderr)
        return None


def cmd_start(args):
    plan, text = read_plan(args.plan)
    try:
        document = progress.start(plan, text, args.step)
    except ValueError as exc:
        die(str(exc))
    except OSError as exc:
        print(f"plan-progress: progress.json not written: {exc}", file=sys.stderr)
        return 0
    root = progress.events_root(plan)
    progress.ensure_run_started(plan, text, document, root)
    progress.emit(plan, document, "stage.started",
                  progress.with_model({"stage": "Implement",
                                       "cycle": progress.document_cycle(document),
                                       **progress.step_context(document, plan, args.step)},
                                      "Implement"), root)
    return 0


def cmd_tick(args):
    plan, text = read_plan(args.plan)

    prog_span = plan_format.section_span(text, "Progress")
    if prog_span is None:
        die("the plan has no `## Progress` section — run `init` first")
    prog_start, prog_end = prog_span

    section_text = text[prog_start:prog_end]
    match = next((m for m in plan_format.progress_box_matches(section_text)
                  if int(m.group(2)) == args.step), None)
    if not match:
        die(f"the `## Progress` section has no box for step {args.step}")

    new_section = section_text[:match.start(1)] + "x" + section_text[match.end(1):]
    new_text = text[:prog_start] + new_section + text[prog_end:]
    plan.write_text(new_text, encoding="utf-8")
    record(lambda: progress.tick(plan, new_text, args.step, args.commit, args.note))
    return 0


def cmd_complete(args):
    plan, text = read_plan(args.plan)
    new_text = plan_format.write_status_complete(text)
    plan.write_text(new_text, encoding="utf-8")
    document = record(lambda: progress.complete(plan, new_text))
    if document is not None:
        write_closing_events(plan, new_text, document)

    if configured_journal_root() is None:
        print("plan-progress: status set to complete; journaling is off (no journalPath configured)")
        return 0

    journal.cmd_report(args)
    write_invoice_for(new_text)
    return 0


def cmd_abort(args):
    plan, text = read_plan(args.plan)
    reason = sys.stdin.read() if args.reason == "-" else args.reason
    reason = reason.strip() or "stopped without a stated reason"
    document = record(lambda: progress.abort(plan, text))
    if document is None:
        return 0
    root = progress.events_root(plan)
    progress.ensure_run_started(plan, text, document, root)
    progress.emit(plan, document, "stage.failed",
                  progress.with_model({"stage": args.stage, "cycle": 1, "reason": reason},
                                      args.stage), root)
    progress.emit(plan, document, "run.finished", {"status": "failed", "reason": reason}, root)
    return 0


def write_closing_events(plan, text, document):
    """`files.changed`, then `usage.reported` per subagent call, then `run.finished`,
    the events file copied into the plan's journal entry's analytics folder and the run's id
    listed in its `entry.json`."""
    root = progress.events_root(plan)
    progress.ensure_run_started(plan, text, document, root)
    base = document.get("base") or plan_format.read_base(text)
    progress.emit(plan, document, "files.changed", events.files_changed_payload(root, base), root)
    for payload in usage_payloads(plan, text, document, root):
        progress.emit(plan, document, "usage.reported", payload, root)
    progress.emit(plan, document, "run.finished", {"status": "done"}, root)
    copy_events(text, root, document.get("run_id"))
    record_run(text, document)


def run_start(document):
    """When the run started: the `started` a task document records, else the earliest
    moment a step started, or None."""
    begun = invoice.parse_time(document.get("started"))
    if begun is not None:
        return begun
    moments = [invoice.parse_time(step.get("started"))
               for entry in document.get("rounds", []) for step in entry.get("steps", [])]
    moments = [moment for moment in moments if moment is not None]
    return min(moments) if moments else None


def usage_payloads(plan, text, document, root):
    """`usage.reported` payloads for the subagent calls made since the run started: from
    the `sessions.json` of the journal entry's analytics folder when there is one, else
    from the sessions the prompt recorded for this project."""
    entry = Path(root.name) / str(document.get("task") or Path(plan).stem)
    rows = None
    frozen = None
    target = journal.journal_plan(text) if configured_journal_root() is not None else None
    folder = analytics.folder_for(target.parent) if target is not None else None
    if folder is not None and (folder / invoice.SESSIONS_FILE).is_file():
        try:
            rows = invoice.read_sessions(folder)
            entry = folder
            frozen = invoice.stored_rates(entry / "invoice.json")
        except ValueError:
            rows = None
    if rows is None:
        rows = journal.recorded_sessions(root)
    if not rows:
        return []
    try:
        data = invoice.aggregate(entry, invoice.load_prices(), frozen, rows=rows,
                                 after=run_start(document), with_calls=True)
    except Exception as exc:
        print(f"plan-progress: usage events not written: {exc}", file=sys.stderr)
        return []
    flow = document.get("flow")
    return events.usage_payloads(data["calls"], flow.get("cycles") if isinstance(flow, dict) else None)


def copy_events(text, root, run_id):
    """Copies the run's events file into the journal round's analytics folder as
    `events-<NN>.jsonl`, and relinks the folder; a failure is a note on stderr."""
    if configured_journal_root() is None or not run_id:
        return
    target = journal.journal_plan(text)
    match = journal.ROUND.match(target.name) if target is not None else None
    if match is None or not target.parent.is_dir():
        return
    try:
        source = events.run_directory(root, run_id) / events.FILE
    except ValueError as exc:
        print(f"plan-progress: events not copied to the journal: {exc}", file=sys.stderr)
        return
    if not source.is_file():
        return
    folder = analytics.folder_for(target.parent)
    with analytics.guard(folder):
        folder.mkdir(parents=True, exist_ok=True)
        destination = folder / f"events-{match.group(1)}.jsonl"
        scratch = destination.with_name(destination.name + ".tmp")
        shutil.copyfile(source, scratch)
        os.replace(scratch, destination)
        analytics.link(target.parent)


def record_run(text, document):
    """Lists the completing run's id in `entry.json` of the journal entry's analytics
    folder, events on or off. The entry is the plan's `Journal:` round, else the run's
    `flow.journal`."""
    run_id = document.get("run_id")
    if configured_journal_root() is None or not run_id:
        return
    target = journal.journal_plan(text)
    entry = target.parent if target is not None else None
    flow = document.get("flow")
    if entry is None and isinstance(flow, dict) and flow.get("journal"):
        entry = Path(flow["journal"])
    if entry is not None and entry.is_dir():
        analytics.link(entry, run_id)


def write_invoice_for(plan_text):
    """Regenerates the invoice of the plan's journal entry; a failure is a note on
    stderr, never a failed `complete`."""
    target = journal.journal_plan(plan_text)
    try:
        written = invoice.write_invoice(target.parent)
        if written is not None:
            print(written)
    except Exception as exc:
        print(f"plan-progress: invoice not written: {exc}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(prog="plan-progress.py", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="write or reconcile the Progress section")
    init_parser.add_argument("--plan", required=True, help="absolute path to the plan file")
    init_parser.set_defaults(func=cmd_init)

    start_parser = subparsers.add_parser("start", help="mark one step in progress in progress.json")
    start_parser.add_argument("--plan", required=True, help="absolute path to the plan file")
    start_parser.add_argument("--step", required=True, type=int, help="the step number being started")
    start_parser.set_defaults(func=cmd_start)

    tick_parser = subparsers.add_parser("tick", help="check one step's box")
    tick_parser.add_argument("--plan", required=True, help="absolute path to the plan file")
    tick_parser.add_argument("--step", required=True, type=int, help="the step number to check")
    tick_parser.add_argument("--commit", help="the sha the step landed as, recorded in progress.json")
    tick_parser.add_argument("--note", help="why the step needed no commit, recorded in progress.json")
    tick_parser.set_defaults(func=cmd_tick)

    complete_parser = subparsers.add_parser("complete", help="set Status: complete and file the report")
    complete_parser.add_argument("--plan", required=True, help="absolute path to the plan file")
    complete_parser.add_argument("--report-file", required=True,
                                 help="file holding the final report, or - for stdin")
    complete_parser.set_defaults(func=cmd_complete)

    abort_parser = subparsers.add_parser("abort", help="mark the run stopped and write its failure events")
    abort_parser.add_argument("--plan", required=True, help="absolute path to the plan file")
    abort_parser.add_argument("--stage", choices=("Implement", "QA", "Review"), default="Implement",
                              help="the stage the run stopped in (default: Implement)")
    abort_parser.add_argument("--reason", required=True, help="why the run stopped, or - for stdin")
    abort_parser.set_defaults(func=cmd_abort)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

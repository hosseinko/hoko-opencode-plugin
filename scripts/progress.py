#!/usr/bin/env python3
"""
progress.py — the one place a plan's progress is read and written: the `## Progress`
checklist helpers and the `progress.json` kept beside the plan.

Ships with the `hoko` plugin. Not a CLI: `plan-progress.py`, `step-commit.py` (through
`plan-progress.py tick`) and `followup.py` import it.

A flat plan `<stem>.md` keeps `<stem>.progress.json` beside it. The checklist in the
plan is the durable record a run resumes from, so every write reconciles the JSON
against it first: step statuses come from the checklist and every other field — run id,
base, commits, notes, timestamps — is kept as it was. A missing or unparsable file is
rebuilt from the plan.
"""

import datetime
import json
import re
import subprocess
from pathlib import Path

import events
import invoice
import plan_format
import settings

VERSION = 1
ROUND_SUFFIX = re.compile(r"^(.*)--r(\d+)$")
TASK_PLAN = re.compile(r"^plan-(\d+)\.md$")
TASK_FILE = "progress.json"

STAGE_MODEL_KEYS = {
    "Implement": "executorModel",
    "QA": "qaModel",
    "Review": "finalReview",
}


def now():
    stamp = datetime.datetime.now(datetime.timezone.utc)
    return stamp.strftime("%Y-%m-%dT%H:%M:%S.") + f"{stamp.microsecond // 1000:03d}Z"


def step_spans(section_text):
    """(number, title, start, end) per `### <N>.` heading, in file order."""
    marks = plan_format.step_matches(section_text)
    spans = []
    for i, mark in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(section_text)
        spans.append((int(mark.group(1)), mark.group(2).strip(), mark.start(), end))
    return spans


def existing_checked(progress_text):
    return {int(m.group(2)): m.group(1).lower() == "x"
            for m in plan_format.progress_box_matches(progress_text)}


def git_head(start):
    """`HEAD`'s sha at `start`, or None outside a git repository or without a commit
    yet."""
    try:
        result = subprocess.run(
            ["git", "-C", str(start), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return None


def plan_round(stem):
    """The round a plan file stem names: its `--r<NN>` suffix, or the NN of a task
    folder's `plan-<NN>`, or 1 without either."""
    match = ROUND_SUFFIX.match(stem)
    if match:
        return int(match.group(2))
    match = TASK_PLAN.match(stem + ".md")
    return int(match.group(1)) if match else 1


def path_for(plan):
    """A plan inside a task folder (`plan-<NN>.md` beside a `progress.json`) shares that
    folder's file; any other plan keeps `<plan stem>.progress.json` beside it."""
    plan = Path(plan)
    if TASK_PLAN.match(plan.name) and (plan.parent / TASK_FILE).is_file():
        return plan.parent / TASK_FILE
    return plan.with_name(plan.stem + ".progress.json")


def document_cycle(document):
    """The cycle a task document is in; a plan run outside a task has one cycle."""
    cycle = document.get("cycle")
    return cycle if isinstance(cycle, int) and cycle > 0 else 1


def load(path):
    """The parsed file, or None when it is missing or not a JSON object."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write(path, document):
    document["updated"] = now()
    invoice.write_atomic(Path(path), json.dumps(document, indent=2) + "\n")


def checklist(plan_text):
    """(number, title, checked) per step: the `## Progress` boxes, or the `### <N>.`
    headings, all unchecked, for a plan with no checklist yet."""
    boxes = plan_format.progress_box_matches(plan_text)
    if boxes:
        return [(int(m.group(2)), m.group(3).strip(), m.group(1).lower() == "x") for m in boxes]
    steps = plan_format.section_span(plan_text, "Steps")
    if steps is None:
        return []
    body = plan_text[steps[0]:steps[1]]
    return [(number, title, False) for number, title, _s, _e in step_spans(body)]


def blank_step(number, title):
    return {"n": number, "title": title, "status": "pending", "commit": None,
            "note": None, "blocker": None, "started": None, "finished": None}


def new_document(plan, plan_text):
    title = re.search(r"^#\s+(.+?)\s*$", plan_text, re.M)
    return {
        "version": VERSION,
        "run_id": None,
        "task": Path(plan).stem,
        "title": title.group(1) if title else Path(plan).stem,
        "status": "pending",
        "stage": "Implement",
        "cycle": 1,
        "loop_limit": settings.get("loopLimit"),
        "base": None,
        "spec": [],
        "stages": {"Implement": "pending", "QA": "pending", "Review": "pending"},
        "rounds": [],
        "updated": None,
    }


def reconcile(plan, plan_text, document, round_number=None, source=None):
    """`document` brought in line with the plan's checklist: the round for this plan
    gets exactly the checklist's steps, each status taken from its box, and no other
    field of an existing step, nor of the document, changes."""
    name = Path(plan).name
    number = plan_round(Path(plan).stem) if round_number is None else round_number
    entry = next((r for r in document["rounds"] if r.get("plan") == name), None)
    if entry is None:
        entry = {"round": number, "plan": name,
                 "source": source or ("plan" if number == 1 else "review"), "steps": []}
        document["rounds"].append(entry)

    known = {step["n"]: step for step in entry["steps"]}
    steps = []
    for step_number, title, checked in checklist(plan_text):
        step = known.get(step_number) or blank_step(step_number, title)
        if checked:
            step["status"] = "done"
        elif step["status"] == "done":
            step["status"] = "pending"
        steps.append(step)
    entry["steps"] = steps

    if document.get("base") is None:
        document["base"] = plan_format.read_base(plan_text)
    return entry


def update(plan, plan_text, mutate=None, round_number=None, source=None):
    """Loads or builds the plan's `progress.json`, reconciles it with the checklist,
    applies `mutate(document, round_entry)` and writes it. Returns the document."""
    path = path_for(plan)
    document = load(path) or new_document(plan, plan_text)
    entry = reconcile(plan, plan_text, document, round_number, source)
    if mutate is not None:
        mutate(document, entry)
    write(path, document)
    return document


def find_step(entry, number):
    for step in entry["steps"]:
        if step["n"] == number:
            return step
    raise ValueError(f"the plan has no step {number}")


def init(plan, plan_text, round_number=None, source=None):
    return update(plan, plan_text, round_number=round_number, source=source)


def start(plan, plan_text, number):
    def mutate(document, entry):
        ensure_run_id(document)
        step = find_step(entry, number)
        step["status"] = "in_progress"
        step["started"] = step["started"] or now()
        step["finished"] = None
        document["status"] = "in_progress"
        document["stages"]["Implement"] = "in_progress"
    return update(plan, plan_text, mutate)


def tick(plan, plan_text, number, commit=None, note=None):
    def mutate(document, entry):
        step = find_step(entry, number)
        step["status"] = "done"
        step["commit"] = commit
        step["note"] = note
        step["blocker"] = None
        step["finished"] = now()
    return update(plan, plan_text, mutate)


def complete(plan, plan_text):
    def mutate(document, entry):
        ensure_run_id(document)
        document["status"] = "done"
        document["stages"]["Implement"] = "done"
    return update(plan, plan_text, mutate)


def abort(plan, plan_text):
    def mutate(document, entry):
        ensure_run_id(document)
        document["status"] = "stopped"
    return update(plan, plan_text, mutate)


def ensure_run_id(document):
    """The run's ULID, generated on first need and kept from then on, so a plan
    forwarded with an id keeps it."""
    if not document.get("run_id"):
        document["run_id"] = events.ulid()
    return document.get("run_id")


def stage_model(stage):
    """The model the stage's own setting names, or None when it is unset. The key is read
    through settings, so a model configured in hoko.json reaches the event and the
    invoice, not only the shell the plugin exported."""
    key = STAGE_MODEL_KEYS.get(stage)
    if key is None:
        return None
    return settings.get(key) or None


def with_model(payload, stage):
    """`payload` plus the stage's model when one is configured: the event schema types
    `model` as a string, so an unset model is omitted rather than written as null."""
    model = stage_model(stage)
    return {**payload, "model": model} if model else payload


def events_root(plan):
    return events.repo_root(Path(plan).resolve().parent)


def emit(plan, document, type_, payload, root=None):
    """Writes one event for the run `document` names; None when it has no run yet."""
    return events.emit(root or events_root(plan), document.get("run_id"), type_, payload)


def plugin_version():
    manifest = settings.PLUGIN_ROOT / "package.json"
    try:
        return json.loads(manifest.read_text(encoding="utf-8")).get("version")
    except (OSError, ValueError):
        return None


def run_started_payload(plan, plan_text, document, root):
    try:
        path = str(Path(plan).resolve().relative_to(Path(root).resolve()))
    except ValueError:
        path = None
    loop_limit = document.get("loop_limit")
    models = {stage: stage_model(stage) for stage in STAGE_MODEL_KEYS}
    payload = {
        "source": "plan",
        "text": plan_text,
        "backend": events.BACKEND,
        "models": {stage: model for stage, model in models.items() if model},
        "presets": [],
        "loop_limit": loop_limit if isinstance(loop_limit, int) else settings.get("loopLimit"),
        "engine": "hoko-plugin",
        "plugin_version": plugin_version(),
        "task": document.get("task"),
    }
    if path is not None:
        payload["path"] = path
    return payload


def ensure_run_started(plan, plan_text, document, root=None):
    """Writes `run.started` unless the run's events file already holds events: the run
    starts once, whichever command reaches it first."""
    root = root or events_root(plan)
    run_id = document.get("run_id")
    if not run_id or events.has_events(root, run_id):
        return
    events.emit(root, run_id, "run.started", run_started_payload(plan, plan_text, document, root))


def step_context(document, plan, number):
    """The `step`, `steps`, `title` and `round` event fields of a step of `plan`."""
    entry = next((r for r in document.get("rounds", []) if r.get("plan") == Path(plan).name), None)
    if entry is None:
        return {"step": number}
    title = next((s["title"] for s in entry["steps"] if s["n"] == number), None)
    return {"step": number, "steps": len(entry["steps"]), "title": title, "round": entry["round"]}

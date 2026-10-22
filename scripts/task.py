#!/usr/bin/env python3
"""
task.py — the state machine behind `/hoko/task`: it holds the stage order, the skip
rules, the cycle count, the loop limit and the spec hand-back, so the conductor
dispatches what it is told and decides nothing about the flow.

Ships with the `hoko` opencode plugin.

    task.py start --title <text> --prompt-file <path>|- [--plan <path>|--spec <path>] [--root <repo>]
    task.py next --task <folder> [--resume-failed]
    task.py record --task <folder> --stage Refine|Spec|Plan|QA|Review [--agent-session <id>]
    task.py record --task <folder> --stage Preflight --exit-code <N> [--duration-ms <ms>]
    task.py record --task <folder> --stage Implement --blocker-file <path>|-
    task.py record --task <folder> --stage Implement --research <findings path>
    task.py answer --task <folder> --answer-file <path>|-
    task.py finish --task <folder> --report-file <path>|-
    task.py stop --task <folder> --reason <text>|-

`--root` defaults to the repository around the current directory, and a relative
`--task` is read against it. All free text — the prompt, the answers, the report, a
reason — reaches the script on a stdin heredoc (`-`).

`start` makes `<plansDir>/<YYYYmmdd-HHMM>-<slug>/` (slug: the title, at most 40
characters, `-2`… on a collision), keeps the prompt in it as `prompt.md`, writes its
`progress.json` and the run's first event. It refuses to start when git tracks `plansDir`,
because `step-commit.py` stages with `git add -A`, and makes sure the folder is ignored.
`--plan <path>` starts from a plan instead of a prompt: Refine, Spec and Plan are skipped
and the plan, with the run id its own `<stem>.progress.json` carries, becomes `plan-01.md`.
`--spec <path>` starts from a spec file instead: it must exist, inside the repository, and
carry a front-matter `id:`, or `start` exits 2 with the reason and makes no folder. Refine
and Spec are skipped, `spec.json` names the file and its live requirement ids, and the
first stage is Plan.
A `start` that fails after making the folder (a plan `plan-progress.py init` refuses, a
journal entry that already holds `plan-01.md`) removes the folder again, and the journal
entry too when this start created it; an entry the plan's `Journal:` line already named is
left alone, and no run event is written.
When Refine found no plan needed (`needs_plan` false) and the task has a spec, recording
the Spec hand-off rewrites the implicit `plan-01.md` with one `Spec:` line per spec file
`paths` names that carries a listed id (its path relative to the repository, its id from
the file's front matter, so a local `spec.md` is named the same way), has its one step
claim every id on one `Satisfies:` line, adopts it again as round 1 (source `implicit`,
a fresh `Base:`) and returns that step without a Plan spawn, so the plan gate is never
asked. A `paths` entry that cannot be read, a file without a front-matter `id:` or an id
whose spec no path carries rejects the hand-off like any schema failure. A `spec` blocker
on that plan still goes through Spec `revise` to a `replan` Plan spawn, and that Spec
hand-off rewrites nothing.
With `journalPath` set the prompt is filed in the journal entry (`journal.py write
--stamp`), and every plan the task writes is copied there as `plan-<NN>.md`.

`next` prints the one action to do, as a single JSON object, and writes no event for a
transition that already happened — asking twice writes nothing twice:

    branch      on a protected branch: create the branch (ticket key in `ticket`), then ask again
    preflight   run `command` (the fast gate) and `record --stage Preflight --exit-code N`
    spawn       launch `agent` named `name` on `model` (the stage's configured reference,
                exactly as written) with `prompt`, then
                `record --stage <stage> --agent-session <id>` with the child session the
                `subagent` tool returned
    resume      continue the child session `session_id` that asked, with `message`
    ask         put `questions` (1–4) to the user, then `answer`
    step        the next unticked step: `slice` for `hoko-plan-executor` (its `model`, when
                present, likewise the stage's configured reference), then `step-commit.py`;
                `context` (when present) goes into the executor's prompt
    finish      every cycle is green: `finish --report-file -`
    stop        the run ended (`status`); report `reason` and end

`--resume-failed` after a `resume` that could not reach its agent returns a fresh `spawn`
that names `answers.json` instead; a fresh spawn carries no `session_id`.

A step the implementer could not finish is recorded with `record --stage Implement
--blocker-file -`, on JSON `{"kind": "spec|plan|external|product", "text": "...", "step":
N}` built from its `Blocker: <kind> — <text>` line. An unknown kind, an empty text or a step
that is not the current one exits non-zero and changes nothing; otherwise the step stays
`in_progress` with `blocker` set. `spec` counts as a Plan hand-back (same `spec_backs`, same
cap and question) and returns a Spec spawn in `revise` mode, then a Plan spawn in `replan`
mode; `plan` returns the `replan` spawn at once, at most twice a cycle, the third asking Re-plan
/ Stop (stage `Plan`). A `replan` Plan writes the next round's `plan-<NN>.md` (source
`replan`, only the steps still to do) in the same cycle, on the base of the plan it replaces.
`external` returns a `hoko-researcher` spawn, then `record --stage Implement --research <path>`
returns the same step with the findings path in its `context`; a second `external` blocker
on that step asks Retry / Stop. `product` asks Retry / Stop (stage `Implement`) and Retry
returns the step with the answer in its `context`. Every Stop ends the task `failed`.

`record` validates the agent's hand-off file in the task folder (`scope.json`,
`spec.json`, `plan.json`, `qa-<NN>.json`, `review-<NN>.json`) before it changes anything: a
hand-off that fails its schema exits non-zero naming the first problem and leaves
`progress.json` as it was. A hand-off whose status is `needs_input` becomes an `ask`
(`answer` stores the reply in `answers.json` and the next `next` is a `resume`); `blocked`
stops the task. A Plan hand-off that is `spec_invalid` is handed back to Spec (`revise`
mode) and then to Plan again, at most twice — the third hand-back is an `ask`.

A cycle that is not green opens the next one: `plan-<NN>.md` (`NN` the next round, which
a re-plan can put ahead of the cycle number), titled `<task title> (round <NN>)`, one step per finding, rendered by `followup.py`. QA `not ready` skips Review for
that cycle (`checks`); Review findings open the next cycle (`findings`). A task runs at
most `1 + loopLimit` cycles, then asks Continue / Accept / Stop (stage `Cycles`):
Continue raises the limit by one — the words after it, if any, become one more step —,
Accept renders the open findings as a follow-up plan that is not run and ends the task
`done`, Stop ends it `failed`. With `loopLimit` 0 there is no question: open items after
cycle 1 are accepted, and `finish` names the follow-up plan as `followup`.

The `planGate` setting is on by default: recording the Plan hand-off asks Approve / Revise / Stop
(stage `Plan`) before any step runs. `"planGate": false` in `~/.config/opencode/hoko.json`, or
`HOKO_PLAN_GATE=false`, turns it off. Revise (`Revise: <what to change>`) spawns the
planner again on the same `plan-01.md`; Stop ends the task `failed`. The question names
each step the plan marks `- Irreversible: <text>`, with its text.

The run's events are written through `events.py`; `finish` closes them like
`plan-progress.py complete` does and files the report in the journal, under the last
round's plan, and writes the invoice only when the plugin has already written the entry's
`usage.json`. `flow.cycles` records when each cycle opened, so a `usage.reported` event
names the cycle that was running when its call started. A task started from a prompt has
no registered session of its own, so `finish` files the sessions recorded for the project
(those written to since the task began) in the `sessions.json` of the entry's analytics
folder (`analytics.py`) before it writes the invoice there, copies the events file there
and lists the run's id in the folder's `entry.json`.
"""

import argparse
import contextlib
import functools
import importlib.util
import io
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import events
import followup
import invoice
import journal
import plan_format
import progress
import settings

SCRIPTS_DIR = Path(__file__).resolve().parent

STAGES = ("Refine", "Spec", "Plan", "Implement", "QA", "Review")
AGENTS = {stage: agent for agent, stage in events.AGENT_STAGES.items() if stage != "Implement"}
PHASE_OF = {"Refine": "refine", "Spec": "spec", "Plan": "plan", "Implement": "implement", "QA": "qa",
            "Review": "review", "Preflight": "preflight"}

SLUG_LIMIT = 40
SPEC_HANDBACK_LIMIT = 3
REPLAN_LIMIT = 2
BLOCKER_KINDS = ("spec", "plan", "external", "product")
SIZES = ("trivial", "small", "medium", "large")
STATUSES = ("ok", "needs_input", "spec_invalid", "blocked")
VERDICTS = ("green", "green with debt", "not ready")
CHECKS = ("fast-gate", "lint", "analyse", "tests", "coverage", "crap", "mutation")
SCOPED_CHECKS = ("crap", "mutation")
GATE_STATUSES = ("passed", "failed", "skipped", "error")
ACTIONABLE = ("blocking", "important")
SEVERITIES = ACTIONABLE + ("nit", "suggestion", "learning", "praise")
DECISION_SOURCES = ("code", "research", "user")
SPEC_ID = re.compile(r"^[\w.\-]+/REQ-\d+$")
FOLDER_NAME = re.compile(r"^(\d{8}-\d{4})-(.+)$")
CHOICES = {
    "cycles": ["Continue", "Accept", "Stop"],
    "handback": ["Revise the spec again", "Plan against the spec as written", "Stop the task"],
    "preflight": ["Continue", "Stop"],
    "plan": ["Approve", "Revise", "Stop"],
    "replan": ["Re-plan", "Stop"],
    "blocker": ["Retry", "Stop"],
}


class TaskError(Exception):
    pass


class HandoffError(TaskError):
    pass


class SpecError(TaskError):
    """The spec file given to `start --spec` cannot start a task."""


@functools.lru_cache(maxsize=None)
def script(name):
    """A sibling CLI script (hyphenated, so not importable by name) as a module; its
    `main` stays guarded, so loading it runs nothing."""
    path = SCRIPTS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def note(message):
    print(f"task: {message}", file=sys.stderr)


def read_text(value, what):
    if value == "-":
        return sys.stdin.read()
    path = Path(value).expanduser()
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise TaskError(f"cannot read the {what} at {path}: {exc}")


def repo_root(start):
    start = Path(start or ".").expanduser()
    result = subprocess.run(["git", "-C", str(start), "rev-parse", "--show-toplevel"],
                            capture_output=True, text=True)
    if result.returncode != 0 or not result.stdout.strip():
        raise TaskError(f"{start} is not inside a git repository")
    return Path(result.stdout.strip()).resolve()


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)


def current_branch(root):
    result = git(root, "rev-parse", "--abbrev-ref", "HEAD")
    return result.stdout.strip() if result.returncode == 0 else None


def on_protected_branch(root):
    return current_branch(root) in script("step-commit").PROTECTED_BRANCHES


def stage_model_ref(stage):
    """The model reference the conductor passes: the stage's configured model, untouched,
    so a `#variant` the setting names stays on it."""
    return progress.stage_model(stage)


def project_slug(root):
    return journal.slugify(root.name) or "unsorted"


class Task:
    """One task folder: its `progress.json` and the events a command queues, written
    after the document is saved so a transition is never announced and then lost."""

    def __init__(self, root, directory, document):
        self.root = root
        self.dir = directory
        self.doc = document
        self.queued = []

    @property
    def flow(self):
        return self.doc["flow"]

    @property
    def cycle(self):
        return self.doc["cycle"]

    def path(self, name):
        return self.dir / name

    def reload(self):
        self.doc = load_document(self.dir)

    def save(self):
        progress.write(self.dir / progress.TASK_FILE, self.doc)

    def queue(self, type_, payload):
        self.queued.append((type_, payload))

    def stage_event(self, type_, stage, **extra):
        payload = {"stage": stage, "cycle": self.cycle}
        if stage in STAGES:
            payload = progress.with_model(payload, stage)
        payload.update(extra)
        self.queue(type_, payload)

    def commit(self):
        self.save()
        self.flush()

    def flush(self):
        for type_, payload in self.queued:
            events.emit(self.root, self.doc.get("run_id"), type_, payload)
        self.queued = []


def load_document(directory):
    document = progress.load(Path(directory) / progress.TASK_FILE)
    if document is None or not isinstance(document.get("flow"), dict):
        raise TaskError(f"{directory} is not a task folder: no readable {progress.TASK_FILE}")
    return document


def open_task(args):
    root = repo_root(args.root)
    directory = Path(args.task).expanduser()
    if not directory.is_absolute():
        directory = root / directory
    directory = directory.resolve()
    return Task(root, directory, load_document(directory))


# ---------------------------------------------------------------- hand-off schemas


def fail(name, message):
    raise HandoffError(f"{name}: {message}")


def is_text(value):
    return isinstance(value, str) and bool(value.strip())


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def check_texts(name, data, field):
    value = data.get(field)
    if not isinstance(value, list) or not all(is_text(item) for item in value):
        fail(name, f"{field} must be a list of non-empty strings")
    return value


def check_questions(name, questions, required):
    if not isinstance(questions, list):
        fail(name, "questions must be a list")
    if required and not 1 <= len(questions) <= 4:
        fail(name, "needs_input needs 1 to 4 questions")
    if len(questions) > 4:
        fail(name, "questions holds at most 4 items")
    seen = set()
    for index, item in enumerate(questions):
        where = f"questions[{index}]"
        if not isinstance(item, dict):
            fail(name, f"{where} must be an object")
        for field in ("id", "question", "why"):
            if not is_text(item.get(field)):
                fail(name, f"{where}.{field} must be a non-empty string")
        if item["id"] in seen:
            fail(name, f"{where}.id {item['id']!r} is used twice")
        seen.add(item["id"])
        options = item.get("options")
        if (not isinstance(options, list) or not 2 <= len(options) <= 4
                or not all(is_text(option) for option in options)):
            fail(name, f"{where}.options must be 2 to 4 non-empty strings")
        if item.get("recommended") not in options:
            fail(name, f"{where}.recommended must be one of its options")
        if "multiple" in item and not isinstance(item["multiple"], bool):
            fail(name, f"{where}.multiple must be true or false")


def check_decisions(name, decisions):
    if not isinstance(decisions, list):
        fail(name, "decisions must be a list")
    for index, item in enumerate(decisions):
        where = f"decisions[{index}]"
        if (not isinstance(item, dict) or not is_text(item.get("id")) or not is_text(item.get("text"))
                or item.get("source") not in DECISION_SOURCES):
            fail(name, f"{where} needs id, text and a source of {'/'.join(DECISION_SOURCES)}")


def check_envelope(name, data, stage, statuses):
    if not isinstance(data, dict):
        fail(name, "must be a JSON object")
    if data.get("stage") != stage:
        fail(name, f"stage must be {stage!r}")
    if data.get("status") not in statuses:
        fail(name, "status must be one of " + ", ".join(statuses))
    if not is_text(data.get("summary")):
        fail(name, "summary must be a non-empty string")
    check_questions(name, data.get("questions", []), data["status"] == "needs_input")
    check_decisions(name, data.get("decisions", []))


def check_scope(name, data):
    if not is_text(data.get("title")):
        fail(name, "title must be a non-empty string")
    if data.get("size") not in SIZES:
        fail(name, "size must be one of " + ", ".join(SIZES))
    impact = data.get("impact")
    if not isinstance(impact, dict):
        fail(name, "impact must be an object")
    for field in ("areas", "files", "contracts"):
        if not isinstance(impact.get(field), list) or not all(isinstance(i, str) for i in impact[field]):
            fail(name, f"impact.{field} must be a list of strings")
    for field in ("needs_spec", "needs_plan"):
        if not isinstance(data.get(field), bool):
            fail(name, f"{field} must be true or false")
    if data.get("ticket") is not None and not is_text(data["ticket"]):
        fail(name, "ticket must be a string or null")
    unknowns = data.get("unknowns")
    if not isinstance(unknowns, list):
        fail(name, "unknowns must be a list")
    for index, item in enumerate(unknowns):
        if not isinstance(item, dict) or not is_text(item.get("question")) or not is_text(item.get("resolution")):
            fail(name, f"unknowns[{index}] needs a question and a resolution")
    if "checks" in data:
        checks = data["checks"]
        if not isinstance(checks, list) or not all(isinstance(check, str) for check in checks):
            fail(name, "checks must be a list of crap and mutation")
        unknown = [check for check in checks if check not in SCOPED_CHECKS]
        if unknown:
            fail(name, f"checks may name only crap and mutation, not {unknown[0]!r}")


def check_spec(name, data):
    check_texts(name, data, "paths")
    if not data["paths"]:
        fail(name, "paths must name at least one spec file")
    ids = check_texts(name, data, "ids")
    for spec_id in ids:
        if not SPEC_ID.match(spec_id):
            fail(name, f"ids must look like SPEC-007/REQ-2, not {spec_id!r}")


def check_plan(name, data, has_spec):
    if data["status"] == "spec_invalid":
        if not has_spec:
            fail(name, "status spec_invalid, but this task has no spec to hand back to")
        if not is_text(data.get("reason")):
            fail(name, "a spec_invalid hand-off needs a reason")
        check_texts(name, data, "invalidates")
    elif data["status"] == "ok" and not is_text(data.get("plan")):
        fail(name, "plan must name the plan file")


def check_finding(name, where, finding, severities):
    if not isinstance(finding, dict):
        fail(name, f"{where} must be an object")
    if finding.get("severity") not in severities:
        fail(name, f"{where}.severity must be one of " + ", ".join(severities))
    if not is_text(finding.get("summary")):
        fail(name, f"{where}.summary must be a non-empty string")
    if finding.get("file") is not None and not isinstance(finding["file"], str):
        fail(name, f"{where}.file must be a string or null")
    if finding.get("line") is not None and not is_int(finding["line"]):
        fail(name, f"{where}.line must be an integer or null")
    for field in ("fix", "scenario"):
        if finding.get(field) is not None and not isinstance(finding[field], str):
            fail(name, f"{where}.{field} must be a string")


def check_qa(name, data):
    if not isinstance(data, dict):
        fail(name, "must be a JSON object")
    if data.get("verdict") not in VERDICTS:
        fail(name, "verdict must be one of " + ", ".join(VERDICTS))
    gates = data.get("gates")
    if not isinstance(gates, list):
        fail(name, "gates must be a list")
    for index, gate in enumerate(gates):
        where = f"gates[{index}]"
        if not isinstance(gate, dict):
            fail(name, f"{where} must be an object")
        if gate.get("check") not in CHECKS:
            fail(name, f"{where}.check must be one of " + ", ".join(CHECKS))
        if gate.get("status") not in GATE_STATUSES:
            fail(name, f"{where}.status must be one of " + ", ".join(GATE_STATUSES))
        if not is_number(gate.get("duration_ms")) or gate["duration_ms"] < 0:
            fail(name, f"{where}.duration_ms must be a non-negative number")
        if gate.get("exit_code") is not None and not is_int(gate["exit_code"]):
            fail(name, f"{where}.exit_code must be an integer or null")
    findings = data.get("findings")
    if not isinstance(findings, list):
        fail(name, "findings must be a list")
    for index, finding in enumerate(findings):
        check_finding(name, f"findings[{index}]", finding, ACTIONABLE)
    check_texts(name, data, "debt")
    if data["verdict"] == "not ready" and not findings:
        fail(name, "a not ready verdict needs at least one finding")


def check_review(name, data):
    if not isinstance(data, list):
        fail(name, "must be a JSON array of findings")
    for index, finding in enumerate(data):
        check_finding(name, f"[{index}]", finding, SEVERITIES)


def read_handoff(task, filename):
    path = task.path(filename)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail(filename, f"not found at {path}")
    except (OSError, ValueError) as exc:
        fail(filename, f"not valid JSON: {exc}")


# ---------------------------------------------------------------- plans and the journal


def journal_target(task, number):
    """The `plan-<NN>.md` this round takes in the task's journal entry, under the same
    number as the task folder's plan, or None when journaling is off or the round's plan
    is already filed there. An entry that already holds that file is an error, unless this
    task filed it itself (a plan the user sent back for revision): filing the copy under
    another number would leave it out of step with the plan."""
    folder = task.flow.get("journal")
    if not folder:
        return None
    if number == 1 and task.flow.get("journal_round_one_filed"):
        return None
    target = Path(folder) / f"plan-{number:02d}.md"
    if target.exists() and number not in task.flow.get("journal_filed", []):
        raise TaskError(f"the journal entry already holds {target.name}; the task's round {number} "
                        "plan cannot be filed there under the same number")
    return target


def adopt_plan(task, plan, number, source):
    """Stamps `Project:` and `Journal:` into the plan, has `plan-progress.py init` give it
    its checklist and `Base:`, records the round in `progress.json` and copies the plan
    into the journal entry. The document is saved first and reloaded after, because
    `plan-progress.py` writes the same file: call this before changing the document."""
    task.save()
    text = plan_format.ensure_header_line(plan.read_text(encoding="utf-8"), "Project", project_slug(task.root))
    target = journal_target(task, number)
    if target is not None:
        text = plan_format.ensure_header_line(text, "Journal", str(target), after=("Project",))
    plan.write_text(text, encoding="utf-8")

    result = subprocess.run([sys.executable, str(SCRIPTS_DIR / "plan-progress.py"), "init", "--plan", str(plan)],
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise TaskError(f"{plan.name} is not a plan this pipeline can run: "
                        f"{(result.stderr or result.stdout).strip()}")
    task.reload()
    text = plan.read_text(encoding="utf-8")
    entry = progress.reconcile(plan, text, task.doc, round_number=number, source=source)
    entry["source"] = source
    if target is not None:
        file_copy(target, text)
        filed = task.flow.setdefault("journal_filed", [])
        if number not in filed:
            filed.append(number)
    return entry


def file_copy(target, text):
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        invoice.write_atomic(target, text)
    except OSError as exc:
        note(f"the journal copy at {target} was not written: {exc}")


def implicit_plan(task, scope, prompt, references=(), claimed=()):
    """A one-step plan for a task the specifier found needs none, so `step-commit.py`
    and `plan-slice.py` work on it unchanged. With a spec, `references` are its `Spec:`
    lines and the one step claims every id in `claimed`."""
    title = " ".join(scope["title"].split())
    change = " ".join(prompt.split())
    if len(change) > 1000:
        change = change[:1000].rsplit(" ", 1)[0] + " …"
    header = "".join(f"Spec: {line}\n" for line in references)
    checks = qa_line(scope["checks"] if "checks" in scope else None)
    if checks is not None:
        header += f"QA: {checks}\n"
    satisfies = f"- Satisfies: {', '.join(claimed)}\n" if claimed else ""
    tests = ("a test for each claimed requirement that fails without the change; "
             if claimed else "") + "the project's own checks stay green."
    body = (f"# {title}\n{header}\n## Goal\n\n{title}\n\n## Progress\n\n- [ ] 1. {title}\n\n"
            f"## Steps\n\n### 1. {title}\n\n- Change: {change}\n{satisfies}"
            f"- Tests: {tests}\n")
    path = task.path("plan-01.md")
    path.write_text(body, encoding="utf-8")
    return path


def spec_reference_lines(task, name, data):
    """The `<path> (<spec id>: REQ-N, …)` of each spec file `data["paths"]` names that
    carries a listed id: the path relative to the repository (a relative entry is read
    against the root, then the task folder) and the id from the file's front matter.
    A path that cannot be read, a file without an id, or a listed id no path carries
    rejects the hand-off."""
    carried = {}
    for value in data["paths"]:
        path = Path(value).expanduser()
        candidates = [path] if path.is_absolute() else [task.root / path, task.dir / path]
        text = None
        for candidate in candidates:
            try:
                resolved = candidate.resolve()
                relative = resolved.relative_to(task.root)
                text = resolved.read_text(encoding="utf-8")
            except (OSError, ValueError):
                continue
            break
        if text is None:
            fail(name, f"cannot read the spec file {value} inside the repository {task.root}")
        spec_id = plan_format.spec_id(text)
        if not spec_id:
            fail(name, f"the spec file {relative} has no `id:` in its front matter")
        carried.setdefault(spec_id, relative.as_posix())
    lines = []
    for spec_id, relative in carried.items():
        reqs = [i.rsplit("/", 1)[1] for i in data["ids"] if i.rsplit("/", 1)[0] == spec_id]
        if reqs:
            lines.append(f"{relative} ({spec_id}: {', '.join(reqs)})")
    missing = [i for i in data["ids"] if i.rsplit("/", 1)[0] not in carried]
    if missing:
        fail(name, f"{', '.join(missing)} names a spec that none of paths carries")
    return lines


def next_round(task):
    """The round the next plan of this task takes: one past the last, since a re-plan adds
    a round without opening a cycle."""
    return max((entry["round"] for entry in task.doc["rounds"]), default=0) + 1


def start_round(task, number):
    """Records when round `number` began, once, so the invoice can bill each response to the
    round that was running."""
    starts = task.flow.setdefault("round_starts", [])
    if all(entry["round"] != number for entry in starts):
        starts.append({"round": number, "started": progress.now()})


def fix_plan(task, items, instruction):
    """Writes the next round's `plan-<NN>.md`, one step per item — plus one for the
    user's own words — and returns its path and round number."""
    number = next_round(task)
    journal_target(task, number)
    start_round(task, number)
    findings = [{**item, "file": item.get("file") or ""} for item in items]
    if instruction:
        findings.append({"severity": "important", "file": "", "line": None,
                         "summary": instruction, "fix": instruction,
                         "scenario": "The user asked for this when the loop limit was reached."})
    title = followup.round_title(task.doc["title"], number)
    try:
        body = followup.render(followup.ordered(findings), title, task.doc["title"])
    except followup.FollowupError as exc:
        raise TaskError(str(exc))
    path = task.path(f"plan-{number:02d}.md")
    path.write_text(body, encoding="utf-8")
    return path, number


def plan_base(task, plan):
    return plan_format.read_base(plan.read_text(encoding="utf-8")) or task.doc.get("base")


# ---------------------------------------------------------------- start


def check_plans_dir(root, relative):
    configured = Path(relative)
    if configured.is_absolute() or ".." in configured.parts or not configured.parts:
        raise TaskError(f"plansDir {relative!r} must name a directory below the repository root")
    tracked = git(root, "ls-files", "--", relative)
    if tracked.stdout.strip():
        raise TaskError(f"plansDir {relative!r} is tracked by git, and step-commit.py stages with "
                        "`git add -A`: untrack it or point plansDir elsewhere")

    script("plan-file").ensure_gitignore(root, relative)
    probe = f"{relative.rstrip('/')}/.probe"
    if git(root, "check-ignore", "-q", "--", probe).returncode != 0:
        with open(root / ".gitignore", "a", encoding="utf-8") as handle:
            handle.write(f"/{relative.strip('/')}/\n")
    if git(root, "check-ignore", "-q", "--", probe).returncode != 0:
        raise TaskError(f"plansDir {relative!r} is not ignored by git and could not be: "
                        "plans would be committed by `git add -A`")


def make_folder(plans_dir, stamp, slug):
    plans_dir.mkdir(parents=True, exist_ok=True)
    folder = plans_dir / f"{stamp}-{slug}"
    counter = 2
    while folder.exists():
        folder = plans_dir / f"{stamp}-{slug}-{counter}"
        counter += 1
    folder.mkdir()
    return folder


def discard_start(folder, entry):
    """Removes what a refused start left behind: the task folder and, when this start
    created it, the journal entry. A failed removal is noted and never masks the error."""
    for path in (folder, entry):
        if path is None:
            continue
        try:
            shutil.rmtree(path)
        except OSError as exc:
            note(f"could not remove {path} after the refused start: {exc}")


def file_prompt(root, folder, prompt):
    """Files the prompt in the journal; the entry's folder, or None when journaling is
    off or the write failed."""
    if journal.journal_root() is None:
        return None
    stamp, slug = FOLDER_NAME.match(folder.name).groups()
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "journal.py"), "write", "--stamp", stamp, "--slug", slug,
         "--project", root.name, "--prompt-file", "-"],
        input=prompt, capture_output=True, text=True)
    if result.returncode != 0 or not result.stdout.strip():
        note(f"the prompt was not filed in the journal: {(result.stderr or result.stdout).strip()}")
        return None
    return Path(result.stdout.strip().splitlines()[-1]).parent


def new_document(folder, title, loop_limit, base, run_id, source):
    started = progress.now()
    return {
        "version": progress.VERSION,
        "run_id": run_id,
        "task": folder.name,
        "title": title,
        "status": "in_progress",
        "stage": "Refine",
        "cycle": 1,
        "loop_limit": loop_limit,
        "base": base,
        "spec": [],
        "stages": {stage: "pending" for stage in STAGES},
        "rounds": [],
        "source": source,
        "started": started,
        "updated": None,
        "flow": {"phase": "refine", "attempt": 0, "spec_backs": 0, "spec_mode": "write",
                 "announced": None, "spawned": None, "question": None, "resume": None,
                 "open": [], "open_reason": None, "closed": False, "skip_review": False,
                 "scope": None, "journal": None, "cycles": [{"cycle": 1, "started": started}],
                 "round_starts": [{"round": 1, "started": started}],
                 "replans": 0, "replan": None, "blocked": None, "context": None, "researched": [],
                 "sessions": {}},
    }


def run_started_payload(task, source, text, plan_path):
    payload = {
        "source": source,
        "text": text,
        "backend": events.BACKEND,
        "models": {stage: model for stage in STAGES if (model := progress.stage_model(stage))},
        "presets": [],
        "loop_limit": task.doc["loop_limit"],
        "engine": "hoko-plugin",
        "plugin_version": progress.plugin_version(),
        "task": task.doc["task"],
    }
    if plan_path is not None:
        try:
            payload["path"] = str(Path(plan_path).resolve().relative_to(task.root))
        except ValueError:
            pass
    return payload


def skip_stage(task, stage):
    task.doc["stages"][stage] = "skipped"
    task.stage_event("stage.completed", stage, outcome="skipped")


def read_spec(root, value):
    """The spec file a task starts from: its path relative to the repository, its
    front-matter id and the `<id>/REQ-N` of every live requirement."""
    path = Path(value).expanduser()
    path = (path if path.is_absolute() else root / path).resolve()
    try:
        relative = path.relative_to(root)
        text = path.read_text(encoding="utf-8")
    except ValueError:
        raise SpecError(f"the spec file {path} is outside the repository {root}")
    except OSError as exc:
        raise SpecError(f"cannot read the spec file at {path}: {exc}")
    spec_id = plan_format.spec_id(text)
    if not spec_id:
        raise SpecError(f"the spec file {relative} has no `id:` in its front matter")
    live = sorted(plan_format.spec_requirement_ids(text), key=lambda req: int(req.split("-")[1]))
    return relative.as_posix(), [f"{spec_id}/{req}" for req in live]


def write_spec_handoff(folder, path, ids):
    handoff = {"stage": "Spec", "status": "ok", "summary": f"the task starts from {path}",
               "questions": [], "decisions": [], "paths": [path], "ids": ids}
    invoice.write_atomic(folder / "spec.json", json.dumps(handoff, indent=2) + "\n")


def cmd_start(args):
    root = repo_root(args.root)
    title = " ".join(args.title.split())
    if not title:
        raise TaskError("a task needs a title")
    if args.plan and args.spec:
        raise TaskError("start from a plan or from a spec, not both")
    spec_path, spec_ids = read_spec(root, args.spec) if args.spec else (None, None)
    prompt = read_text(args.prompt_file, "prompt file")
    if not prompt.strip():
        raise TaskError("the prompt is empty")

    plan_source = None
    plan_text = None
    if args.plan:
        plan_source = Path(args.plan).expanduser().resolve()
        plan_text = read_text(str(plan_source), "plan file")

    relative = settings.get("plansDir")
    check_plans_dir(root, relative)
    slug = journal.slugify(title, limit=SLUG_LIMIT) or "task"
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M")
    folder = make_folder(root / relative, stamp, slug)
    created_entry = None
    try:
        (folder / "prompt.md").write_text(prompt.strip() + "\n", encoding="utf-8")

        forwarded = progress.load(progress.path_for(plan_source)) if plan_source else None
        run_id = (forwarded or {}).get("run_id") or events.ulid()
        base = plan_format.read_base(plan_text) if plan_text else None
        source = "plan" if plan_source else "spec" if spec_path else "prompt"
        document = new_document(folder, title, settings.get("loopLimit"), base or progress.git_head(root),
                                run_id, source)
        task = Task(root, folder, document)

        existing = journal.journal_plan(plan_text) if plan_text else None
        filed = existing is not None and existing.parent.is_dir()
        entry_dir = existing.parent if filed else file_prompt(root, folder, prompt)
        if not filed:
            created_entry = entry_dir
        if entry_dir is not None:
            document["flow"]["journal"] = str(entry_dir)
            document["flow"]["journal_round_one_filed"] = filed

        if spec_path is not None:
            task.queue("run.started", run_started_payload(task, "spec", prompt.strip(), root / spec_path))
            write_spec_handoff(folder, spec_path, spec_ids)
            document["spec"] = [spec_path]
            document["flow"]["spec_ids"] = spec_ids
            for stage in ("Refine", "Spec"):
                skip_stage(task, stage)
            task.doc["stage"] = "Plan"
            task.flow["phase"] = "branch" if on_protected_branch(root) else "preflight"
        elif plan_source is None:
            task.queue("run.started", run_started_payload(task, "prompt", prompt.strip(), None))
        else:
            task.queue("run.started", run_started_payload(task, "plan", plan_text, plan_source))
            plan = folder / "plan-01.md"
            plan.write_text(plan_text, encoding="utf-8")
            adopt_plan(task, plan, 1, "plan")
            for stage in ("Refine", "Spec", "Plan"):
                skip_stage(task, stage)
            task.doc["stage"] = "Implement"
            task.flow["phase"] = "branch" if on_protected_branch(root) else "preflight"
        task.commit()
    except Exception:
        discard_start(folder, created_entry)
        raise
    print(json.dumps({"task": folder.name, "dir": str(folder), "run_id": run_id,
                      "journal": task.flow.get("journal")}))
    return 0


# ---------------------------------------------------------------- next


def spawn(task, stage, lines, **extra):
    flow = task.flow
    backs = flow["spec_backs"]
    key = f"{stage}:{task.cycle}:{backs}:{flow['attempt']}"
    name = f"{stage.lower()}-c{task.cycle}"
    if backs:
        name += f"-b{backs}"
    if flow["attempt"]:
        name += f"-a{flow['attempt']}"
    if flow.get("announced") != key:
        flow["announced"] = key
        flow["spawned"] = name
        task.doc["stage"] = stage
        task.doc["stages"][stage] = "in_progress"
        task.stage_event("stage.started", stage)
        task.commit()
    answers = task.path("answers.json")
    if answers.is_file():
        lines = lines + [f"Answers the user already gave are in {answers}."]
    action = {"action": "spawn", "stage": stage, "name": name, "agent": AGENTS[stage],
              "prompt": "\n".join(lines)}
    model = stage_model_ref(stage)
    if model:
        action["model"] = model
    return {**action, **extra}


def prompt_lines(task, handoff, *lines):
    return [f"Task: {task.doc['title']}", f"Task folder: {task.dir}",
            f"The user's prompt: {task.path('prompt.md')}", *lines,
            f"Write your hand-off to {handoff} and return only its path and a one-line summary."]


def plan_of_round(task):
    entry = task.doc["rounds"][-1]
    return task.path(entry["plan"]), entry


def phase_refine(task):
    handoff = task.path("scope.json")
    return spawn(task, "Refine", prompt_lines(
        task, handoff, "Refine the prompt into scope.json: size, impact, needs_spec, needs_plan, ticket "
        "and the unknowns you resolved from the code. Ask the product questions, and always ask "
        "which QA checks the run gets."),
        handoff=str(handoff))


def phase_branch(task):
    if not on_protected_branch(task.root):
        task.flow["phase"] = "preflight"
        task.commit()
        return decide(task)
    scope = task.flow.get("scope") or {}
    return {"action": "branch", "current": current_branch(task.root), "ticket": scope.get("ticket"),
            "title": task.doc["title"], "slug": journal.slugify(task.doc["title"], limit=SLUG_LIMIT)}


def phase_preflight(task):
    gate = SCRIPTS_DIR / "fast-gate.py"
    return {"action": "preflight", "command": f'python3 "{gate}"'}


def scope_lines(task):
    """The scope hand-off, for a task that has one: a task started from a spec skips Refine."""
    scope = task.path("scope.json")
    return [f"The scope: {scope}"] if scope.is_file() else []


def selected_checks(task):
    """The checks the Refine answer selected, or None when the task asked no such question:
    a pre-change scope and a task started from a spec or a plan carry no `checks` list."""
    scope = task.flow.get("scope") or {}
    return scope["checks"] if "checks" in scope else None


def qa_line(checks):
    """The plan's `QA:` value for a checks selection, or None when there was no selection."""
    return None if checks is None else ", ".join(checks) or "none"


def plan_check_lines(task):
    """What the planner writes on the plan's `QA:` line: the Refine answer when there is one,
    else nothing and the plan in force or the settings decide."""
    checks = selected_checks(task)
    if checks is None:
        return []
    if not checks:
        return ["Refine selected no QA check (Skip): write the plan's `QA:` line as `QA: none`."]
    return [f"Refine selected the QA checks {', '.join(checks)}: write that list on the plan's `QA:` line."]


def qa_check_lines(task):
    checks = selected_checks(task)
    if checks is None:
        return []
    if not checks:
        return ["Refine selected no QA check (Skip): run neither the CRAP index nor mutation testing, "
                "and report both as off."]
    return [f"Refine selected the QA checks {', '.join(checks)}: run exactly those and report the rest as off."]


def phase_spec(task):
    handoff = task.path("spec.json")
    mode = task.flow["spec_mode"]
    lines = prompt_lines(task, handoff, f"Mode: {mode}. Write spec.json with the spec paths and the "
                         "requirement ids (SPEC-NNN/REQ-N).", *scope_lines(task))
    if mode == "revise":
        back = task.flow.get("spec_reason") or {}
        if back.get("from") == "Implement":
            lines.append(f"The implementer found a requirement that cannot hold as written: {back.get('reason')}")
        else:
            lines.append(f"The planner handed the spec back: {back.get('reason')} "
                         f"(invalidates {', '.join(back.get('invalidates') or [])}).")
    if not settings.get("specs"):
        lines.append(f"The specs setting is off: write the spec to {task.path('spec.md')}.")
    return spawn(task, "Spec", lines, handoff=str(handoff), mode=mode,
                 spec_path=None if settings.get("specs") else str(task.path("spec.md")))


def replan_lines(task, handoff, replan):
    plan = task.path(f"plan-{replan['round']:02d}.md")
    return prompt_lines(
        task, handoff, f"Mode: replan. Round {replan['round']} of cycle {task.cycle}: write {plan} and "
        f"plan.json (status ok, plan {plan.name}).",
        f"The plan in force is {task.path(replan['plan'])}; the steps ticked there are done and committed. "
        "Write only the steps still to do, numbered from 1, in the same format.",
        f"The implementer was blocked on step {replan['step']} ({replan['kind']}): {replan['reason']}",
        *scope_lines(task))


def phase_plan(task):
    handoff = task.path("plan.json")
    replan = task.flow.get("replan")
    if replan:
        lines = replan_lines(task, handoff, replan)
    else:
        lines = prompt_lines(task, handoff, f"Write {task.path('plan-01.md')} and plan.json "
                             "(status ok, or spec_invalid with the ids it invalidates).", *scope_lines(task))
    if task.doc["spec"]:
        lines.append(f"The spec: {task.path('spec.json')}")
    revision = None if replan else task.flow.get("plan_revision")
    if revision:
        lines.append(f"The user sent the plan back: rewrite {task.path('plan-01.md')} in place, and "
                     f"write plan.json again, with these changes: {revision}")
    if task.flow.get("plan_against_spec_as_written"):
        lines.append("The user chose to plan against the spec as written: do not hand it back again.")
    lines.extend(plan_check_lines(task))
    return spawn(task, "Plan", lines, handoff=str(handoff), **({"mode": "replan"} if replan else {}))


def phase_implement(task):
    doc = task.doc
    plan, entry = plan_of_round(task)
    try:
        text = plan.read_text(encoding="utf-8")
    except OSError as exc:
        raise TaskError(f"cannot read {plan}: {exc}")
    before = json.dumps(doc, sort_keys=True)
    progress.reconcile(plan, text, doc, round_number=entry["round"])
    pending = [step for step in entry["steps"] if step["status"] != "done"]
    if not pending:
        doc["stages"]["Implement"] = "done"
        task.flow["phase"] = "qa"
        task.commit()
        return decide(task)
    doc["stage"] = "Implement"
    doc["stages"]["Implement"] = "in_progress"
    if json.dumps(doc, sort_keys=True) != before:
        task.commit()
    step = pending[0]
    result = subprocess.run([sys.executable, str(SCRIPTS_DIR / "plan-slice.py"), "--plan", str(plan),
                             "--step", str(step["n"]), "--out-dir", str(task.path(".slices"))],
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise TaskError(f"cannot slice step {step['n']} of {plan.name}: {result.stderr.strip()}")
    action = {"action": "step", "plan": str(plan), "step": step["n"], "steps": len(entry["steps"]),
              "title": step["title"], "round": entry["round"], "cycle": task.cycle,
              "slice": result.stdout.strip()}
    model = stage_model_ref("Implement")
    if model:
        action["model"] = model
    context = task.flow.get("context")
    if context and (context["round"], context["step"]) == (entry["round"], step["n"]):
        action["context"] = context["text"]
    return action


def phase_research(task):
    blocked = task.flow["blocked"]
    return {"action": "spawn", "stage": "Implement", "name": f"research-c{task.cycle}-s{blocked['step']}",
            "agent": "hoko-researcher",
            "prompt": "\n".join([
                f"Task: {task.doc['title']}",
                f"The implementer of step {blocked['step']} is blocked by something outside the repository.",
                f"The question: {blocked['text']}",
                "File the findings, and return only the path of the findings file and a one-line summary."])}


def phase_qa(task):
    plan, entry = plan_of_round(task)
    handoff = task.path(f"qa-{task.cycle:02d}.json")
    lines = prompt_lines(
        task, handoff, f"The plan: {plan}", f"The range: {plan_base(task, plan)}..HEAD",
        "Run only the project's auto-fixers and commit their output; every other problem goes back "
        "as a finding.")
    lines.extend(qa_check_lines(task))
    return spawn(task, "QA", lines, handoff=str(handoff), plan=str(plan),
                 range=f"{plan_base(task, plan)}..HEAD")


def phase_review(task):
    plan, entry = plan_of_round(task)
    handoff = task.path(f"review-{task.cycle:02d}.json")
    lines = prompt_lines(task, handoff, f"The plan: {plan}", f"The range: {plan_base(task, plan)}..HEAD",
                         f"Write the findings as a JSON array to exactly {handoff}.")
    if task.doc["spec"]:
        lines.append(f"The spec ids to check Satisfies: lines against: {task.path('spec.json')}")
    return spawn(task, "Review", lines, handoff=str(handoff), plan=str(plan),
                 range=f"{plan_base(task, plan)}..HEAD")


PHASES = {"refine": phase_refine, "branch": phase_branch, "preflight": phase_preflight,
          "spec": phase_spec, "plan": phase_plan, "implement": phase_implement, "research": phase_research,
          "qa": phase_qa, "review": phase_review}


def ask_action(task):
    question = task.flow["question"]
    if not question.get("logged"):
        question["logged"] = True
        task.save()
        for item in question["questions"]:
            events.emit(task.root, task.doc.get("run_id"), "user.input_requested",
                        {"stage": question["stage"], "cycle": task.cycle, "question": item["question"],
                         "initial": item["recommended"]})
    return {"action": "ask", "stage": question["stage"], "questions": question["questions"]}


def decide(task):
    doc, flow = task.doc, task.flow
    if flow.get("closed"):
        return {"action": "stop", "status": doc["status"], "reason": flow.get("reason")}
    if doc["status"] == "done" or flow["phase"] == "finish":
        action = {"action": "finish", "cycle": task.cycle}
        if flow.get("accepted"):
            action["followup"] = str(task.path(flow["accepted"]))
        return action
    if flow.get("question"):
        return ask_action(task)
    if flow.get("resume"):
        resume = flow["resume"]
        action = {"action": "resume", "stage": resume["stage"], "name": resume["name"],
                  "message": f"The user answered your questions: read {task.path('answers.json')}, "
                             f"then finish your hand-off."}
        if resume.get("session_id"):
            action["session_id"] = resume["session_id"]
        return action
    return PHASES[flow["phase"]](task)


def cmd_next(args):
    task = open_task(args)
    if args.resume_failed and task.flow.get("resume"):
        task.flow["attempt"] += 1
        task.flow["resume"] = None
        task.save()
    print(json.dumps(decide(task)))
    return 0


# ---------------------------------------------------------------- record


def choose(answer, options):
    """The option an answer begins with, and the words after it."""
    for option in options:
        word = option.split()[0]
        match = re.match(r"\s*" + re.escape(word) + r"(?!\w)[\s:,.\-]*(.*)", answer, re.I | re.S)
        if match:
            return option, match.group(1).strip()
    raise TaskError(f"the answer {answer.strip()!r} must begin with one of: "
                    + ", ".join(option.split()[0] for option in options))


def ask(task, stage, kind, questions):
    task.flow["question"] = {"kind": kind, "stage": stage, "questions": questions, "logged": False,
                             "name": task.flow.get("spawned"),
                             "session": (task.flow.get("sessions") or {}).get(stage)}


def stop_run(task, stage, reason):
    """Ends the task `failed`: `stage.failed`, then `run.finished`."""
    task.flow["closed"] = True
    task.flow["reason"] = reason
    task.doc["status"] = "stopped"
    task.stage_event("stage.failed", stage, reason=reason)
    task.queue("run.finished", {"status": "failed", "reason": reason})


def intake(task, stage, filename, check):
    """Reads and validates a stage's hand-off. Returns it when it carries the stage's
    result; a `needs_input` becomes a question and a `blocked` stops the task, and both
    return None."""
    data = read_handoff(task, filename)
    if not isinstance(data, dict):
        fail(filename, "must be a JSON object")
    statuses = STATUSES if stage == "Plan" else ("ok", "needs_input", "blocked")
    check_envelope(filename, data, stage, statuses)
    if data["status"] == "ok" or data["status"] == "spec_invalid":
        check(filename, data)
    task.flow["resume"] = None
    if data["status"] == "needs_input":
        ask(task, stage, "agent", data["questions"])
        task.commit()
        return None
    if data["status"] == "blocked":
        stop_run(task, stage, data["summary"])
        task.commit()
        return None
    return data


def done_stage(task, stage, **extra):
    task.doc["stages"][stage] = "done"
    task.stage_event("stage.completed", stage, outcome="done", **extra)


def after_preflight(task):
    stages = task.doc["stages"]
    if stages["Spec"] == "pending":
        task.flow["phase"] = "spec"
    elif stages["Plan"] == "pending":
        task.flow["phase"] = "plan"
    else:
        task.flow["phase"] = "implement"


def record_preflight(task, args):
    if args.exit_code is None:
        raise TaskError("record --stage Preflight needs --exit-code")
    status = script("step-commit").GATE_STATUSES.get(args.exit_code, "error")
    task.stage_event("check.result", "Implement", check="fast-gate", status=status,
                     duration_ms=args.duration_ms or 0, exit_code=args.exit_code, phase="preflight")
    if args.exit_code in (0, 2):
        after_preflight(task)
    else:
        ask(task, "Implement", "preflight", [{
            "id": "preflight", "recommended": "Continue",
            "question": f"The fast gate was already {status} (exit {args.exit_code}) before this run "
                        "touched anything. Continue anyway?",
            "options": ["Continue", "Stop"],
            "why": "A failure unrelated to this task is often fine to run alongside, and only you can say."}])
    task.commit()


def record_refine(task, args):
    data = intake(task, "Refine", "scope.json", check_scope)
    if data is None:
        return
    prompt = task.path("prompt.md").read_text(encoding="utf-8")
    if not data["needs_plan"]:
        adopt_plan(task, implicit_plan(task, data, prompt), 1, "implicit")
    task.flow["scope"] = {key: data[key] for key in ("title", "size", "needs_spec", "needs_plan", "ticket")}
    if "checks" in data:
        task.flow["scope"]["checks"] = data["checks"]
    done_stage(task, "Refine", size=data["size"], needs_spec=data["needs_spec"], needs_plan=data["needs_plan"])
    if not data["needs_spec"]:
        skip_stage(task, "Spec")
    if not data["needs_plan"]:
        skip_stage(task, "Plan")
    if data["size"] == "trivial":
        task.flow["skip_review"] = True
        skip_stage(task, "Review")
    task.flow["phase"] = "branch" if on_protected_branch(task.root) else "preflight"
    task.commit()


def plans_itself(task):
    """True while the task's one-step plan stands in for the planner: Refine found no plan
    needed and no re-plan is waiting to write the next round."""
    scope = task.flow.get("scope") or {}
    return scope.get("needs_plan") is False and not task.flow.get("replan")


def record_spec(task, args):
    references = []

    def check(name, data):
        check_spec(name, data)
        if plans_itself(task):
            references.extend(spec_reference_lines(task, name, data))

    data = intake(task, "Spec", "spec.json", check)
    if data is None:
        return
    if plans_itself(task):
        prompt = task.path("prompt.md").read_text(encoding="utf-8")
        adopt_plan(task, implicit_plan(task, task.flow["scope"], prompt, references, data["ids"]),
                   1, "implicit")
    mode = task.flow["spec_mode"]
    task.doc["spec"] = data["paths"]
    task.flow["spec_ids"] = data["ids"]
    task.flow["spec_mode"] = "write"
    task.flow["spec_reason"] = None
    done_stage(task, "Spec", mode=mode, ids=len(data["ids"]))
    task.flow["phase"] = "implement" if plans_itself(task) else "plan"
    task.commit()


def handback_question(task, reason):
    return [{"id": "handback", "recommended": "Revise the spec again",
             "question": f"The spec has been handed back {task.flow['spec_backs']} times: {reason} "
                         "How should the task go on?",
             "options": ["Revise the spec again", "Plan against the spec as written", "Stop the task"],
             "why": "Each hand-back means the spec and the plan still disagree; that is a product call."}]


def plan_gate_question(plan, entry):
    question = (f"The plan has {len(entry['steps'])} step(s), in {plan}. Approve it and start "
                "implementing, revise it (say what to change after the word), or stop?")
    marked = plan_format.irreversible_steps(plan.read_text(encoding="utf-8"))
    if marked:
        question += " Steps a revert cannot undo: " + ", ".join(
            f"step {number} ({text})" for number, text in marked) + "."
    return [{"id": "plan", "recommended": "Approve", "question": question,
             "options": ["Approve", "Revise", "Stop"],
             "why": "The planGate setting stops the pipeline for your approval before any step runs. It is on by "
                    "default; \"planGate\": false in ~/.config/opencode/hoko.json, or HOKO_PLAN_GATE=false, turns it off."}]


def record_plan(task, args):
    data = intake(task, "Plan", "plan.json", lambda name, d: check_plan(name, d, bool(task.doc["spec"])))
    if data is None:
        return
    flow = task.flow
    if data["status"] == "spec_invalid":
        flow["spec_backs"] += 1
        task.path("plan.json").replace(task.path(f"plan.handback-{flow['spec_backs']}.json"))
        flow["spec_reason"] = {"reason": data["reason"], "invalidates": data["invalidates"]}
        task.doc["stages"]["Plan"] = "pending"
        task.doc["stages"]["Spec"] = "pending"
        task.stage_event("stage.completed", "Plan", outcome="done", handoff_to="Spec", reason=data["reason"])
        if flow["spec_backs"] >= SPEC_HANDBACK_LIMIT:
            ask(task, "Plan", "handback", handback_question(task, data["reason"]))
        else:
            flow["spec_mode"] = "revise"
            flow["phase"] = "spec"
        task.commit()
        return

    replan = flow.get("replan")
    number = replan["round"] if replan else 1
    plan = task.path(f"plan-{number:02d}.md")
    if Path(data["plan"]).name != plan.name or not plan.is_file():
        fail("plan.json", f"plan must name {plan.name}, written into the task folder")
    if replan:
        inherit_base(task, plan, task.path(replan["plan"]))
    entry = adopt_plan(task, plan, number, "replan" if replan else "plan")
    done_stage(task, "Plan", plan=plan.name, steps=len(entry["steps"]))
    task.flow["plan_revision"] = None
    if replan:
        task.flow.update({"replan": None, "blocked": None, "phase": "implement"})
    elif settings.get("planGate"):
        ask(task, "Plan", "plan", plan_gate_question(plan, entry))
    else:
        task.flow["phase"] = "implement"
    task.commit()


def inherit_base(task, plan, previous):
    """A re-plan carries on the cycle it replaces, so its plan keeps that plan's base
    and the cycle's QA and review still cover every commit of it."""
    text = plan.read_text(encoding="utf-8")
    if plan_format.read_base(text) is None:
        base = plan_base(task, previous)
        if base:
            plan.write_text(plan_format.write_base(text, base), encoding="utf-8")


def finding_events(task, stage, findings):
    for number, finding in enumerate(findings, start=1):
        task.queue("finding.reported", {
            "stage": stage, "cycle": task.cycle, "id": f"{task.cycle}.{number}",
            "file": finding.get("file") or None, "line": finding.get("line"),
            "problem": finding["summary"], "question": None, "severity": finding["severity"]})


def cycles_question(task, items):
    limit = 1 + task.doc["loop_limit"]
    return [{"id": "cycles", "recommended": "Accept",
             "question": f"{len(items)} open item(s) remain after cycle {task.cycle} of {limit}. "
                         "Continue with another cycle (add what to do after the word), accept the open "
                         "items as a follow-up plan, or stop?",
             "options": ["Continue", "Accept", "Stop"],
             "why": "Accepting open findings is a product call, not the pipeline's."}]


def route_open_items(task, items, reason):
    """What the end of a cycle with `items` still open leads to: the next cycle, whose plan
    is written now (the document is reloaded, so nothing may have changed yet), or the
    loop-limit question, or, with a loop limit of 0, the follow-up plan without one. None
    when nothing is open."""
    if not items:
        return None
    if task.cycle >= 1 + task.doc["loop_limit"]:
        if task.doc["loop_limit"] == 0:
            return {"accept": True}
        return {"ask": cycles_question(task, items), "items": items, "reason": reason}
    path, number = fix_plan(task, items, None)
    adopt_plan(task, path, number, "qa" if reason == "checks" else "review")
    return {"cycle": task.cycle + 1, "reasons": [reason]}


def apply_route(task, route, items):
    """Applies `route_open_items` once the stage's own changes are in the document."""
    flow = task.flow
    if route is None:
        flow["phase"] = "finish"
    elif route.get("accept"):
        accept_open_items(task, items)
    elif "ask" in route:
        flow["open"] = items
        flow["open_reason"] = route["reason"]
        flow["phase"] = "cycles"
        ask(task, "Cycles", "cycles", route["ask"])
    else:
        enter_cycle(task, route["cycle"], route["reasons"])


def enter_cycle(task, number, reasons):
    doc = task.doc
    doc["cycle"] = number
    doc["stage"] = "Implement"
    doc["stages"]["Implement"] = "pending"
    doc["stages"]["QA"] = "pending"
    doc["stages"]["Review"] = "skipped" if task.flow["skip_review"] else "pending"
    task.flow.update({"phase": "implement", "attempt": 0, "open": [], "open_reason": None, "replans": 0})
    task.flow.setdefault("cycles", []).append({"cycle": number, "started": progress.now()})
    task.queue("cycle.started", {"cycle": number, "reasons": reasons})


def record_qa(task, args):
    name = f"qa-{task.cycle:02d}.json"
    data = read_handoff(task, name)
    check_qa(name, data)
    findings = data["findings"]
    route = route_open_items(task, findings, "checks") if data["verdict"] == "not ready" else None
    task.flow["resume"] = None

    for gate in data["gates"]:
        payload = {"stage": "QA", "cycle": task.cycle, "check": gate["check"], "status": gate["status"],
                   "duration_ms": gate["duration_ms"]}
        if gate.get("exit_code") is not None:
            payload["exit_code"] = gate["exit_code"]
        task.queue("check.result", payload)
    finding_events(task, "QA", findings)
    done_stage(task, "QA", verdict=data["verdict"], findings=len(findings), debt=data["debt"])
    if data["verdict"] != "not ready":
        task.flow["phase"] = "finish" if task.flow["skip_review"] else "review"
    else:
        apply_route(task, route, findings)
    task.commit()


def record_review(task, args):
    name = f"review-{task.cycle:02d}.json"
    data = read_handoff(task, name)
    check_review(name, data)
    items = [finding for finding in data if finding["severity"] in ACTIONABLE]
    route = route_open_items(task, items, "findings")
    task.flow["resume"] = None

    finding_events(task, "Review", data)
    done_stage(task, "Review", findings=len(data), open=len(items))
    apply_route(task, route, items)
    task.commit()


def current_step(task):
    """The round the implementer is working on and its first unticked step, read from the
    plan's checklist; the document is only changed in memory."""
    plan, entry = plan_of_round(task)
    try:
        text = plan.read_text(encoding="utf-8")
    except OSError as exc:
        raise TaskError(f"cannot read {plan}: {exc}")
    progress.reconcile(plan, text, task.doc, round_number=entry["round"])
    pending = [step for step in entry["steps"] if step["status"] != "done"]
    if not pending:
        raise TaskError(f"every step of {plan.name} is done: no step can be blocked")
    return plan, entry, pending[0]


def read_blocker(task, value, step):
    name = "blocker"
    text = read_text(value, "blocker file")
    try:
        data = json.loads(text)
    except ValueError as exc:
        fail(name, f"not valid JSON: {exc}")
    if not isinstance(data, dict):
        fail(name, "must be a JSON object")
    if data.get("kind") not in BLOCKER_KINDS:
        fail(name, "kind must be one of " + ", ".join(BLOCKER_KINDS))
    if not is_text(data.get("text")):
        fail(name, "text must be a non-empty string")
    if not is_int(data.get("step")) or data["step"] != step["n"]:
        fail(name, f"step must be the current step, {step['n']}")
    if data["kind"] == "spec" and not task.doc["spec"]:
        fail(name, "kind spec, but this task has no spec to hand back to: record it as a plan blocker")
    return {"kind": data["kind"], "text": " ".join(data["text"].split()), "step": step["n"]}


def begin_replan(task, plan, entry, blocker):
    """The next Plan spawn writes the next round's plan, in the same cycle."""
    flow = task.flow
    flow["replan"] = {"round": next_round(task), "plan": plan.name, "step": blocker["step"],
                      "kind": blocker["kind"], "reason": blocker["text"]}
    start_round(task, flow["replan"]["round"])
    flow["attempt"] += 1
    task.doc["stages"]["Plan"] = "pending"
    if task.path("plan.json").is_file():
        task.path("plan.json").replace(task.path(f"plan.round-{entry['round']:02d}.json"))


def blocker_question(kind, text, step, why):
    return [{"id": "blocker", "recommended": "Retry",
             "question": f"Step {step} is blocked ({kind}): {text} Retry the step (say what to change "
                         "after the word) or stop?",
             "options": ["Retry", "Stop"], "why": why}]


def blocked_on_spec(task, plan, entry, blocker):
    flow = task.flow
    flow["spec_backs"] += 1
    flow["spec_reason"] = {"reason": blocker["text"], "invalidates": [], "from": "Implement"}
    begin_replan(task, plan, entry, blocker)
    task.doc["stages"]["Spec"] = "pending"
    if flow["spec_backs"] >= SPEC_HANDBACK_LIMIT:
        flow["phase"] = "plan"
        ask(task, "Plan", "handback", handback_question(task, blocker["text"]))
    else:
        flow["spec_mode"] = "revise"
        flow["phase"] = "spec"


def blocked_on_plan(task, plan, entry, blocker):
    flow = task.flow
    flow["replans"] = flow.get("replans", 0) + 1
    begin_replan(task, plan, entry, blocker)
    flow["phase"] = "plan"
    if flow["replans"] > REPLAN_LIMIT:
        ask(task, "Plan", "replan", [{
            "id": "replan", "recommended": "Re-plan",
            "question": f"The implementer has sent the plan back {flow['replans']} times in cycle "
                        f"{task.cycle}: {blocker['text']} Re-plan once more, or stop?",
            "options": ["Re-plan", "Stop"],
            "why": "Each send-back means the plan and the code still disagree; whether to go on is your call."}])


def blocked_on_external(task, plan, entry, blocker):
    flow = task.flow
    key = f"{entry['round']}:{blocker['step']}"
    researched = flow.setdefault("researched", [])
    if key in researched:
        ask(task, "Implement", "blocker", blocker_question(
            "external", blocker["text"], blocker["step"],
            "Research already ran once for this step and it is blocked again."))
        return
    researched.append(key)
    flow["phase"] = "research"


def blocked_on_product(task, plan, entry, blocker):
    ask(task, "Implement", "blocker", blocker_question(
        "product", blocker["text"], blocker["step"], "Only you can settle a product decision."))


BLOCKED_ON = {"spec": blocked_on_spec, "plan": blocked_on_plan, "external": blocked_on_external,
              "product": blocked_on_product}


def record_research(task, value):
    path = Path(value).expanduser()
    path = path if path.is_absolute() else task.root / path
    if not path.is_file():
        fail("research", f"no findings file at {path}")
    blocked = task.flow["blocked"]
    task.flow["context"] = {"round": blocked["round"], "step": blocked["step"],
                            "text": f"The step was blocked: {blocked['text']} Research findings: {path} "
                                    "— read them before you implement."}
    task.flow["phase"] = "implement"
    task.commit()


def record_implement(task, args):
    if bool(args.blocker_file) == bool(args.research):
        raise TaskError("record --stage Implement needs exactly one of --blocker-file and --research")
    if args.research:
        return record_research(task, args.research)

    plan, entry, step = current_step(task)
    blocker = read_blocker(task, args.blocker_file, step)
    step["status"] = "in_progress"
    step["blocker"] = {"kind": blocker["kind"], "text": blocker["text"]}
    task.doc["stage"] = "Implement"
    task.flow["blocked"] = {"round": entry["round"], **blocker}
    task.flow["context"] = None
    BLOCKED_ON[blocker["kind"]](task, plan, entry, blocker)
    task.commit()


RECORDERS = {"Refine": record_refine, "Spec": record_spec, "Plan": record_plan, "Implement": record_implement,
             "QA": record_qa, "Review": record_review, "Preflight": record_preflight}


def cmd_record(args):
    task = open_task(args)
    recorder = RECORDERS[args.stage]
    if task.flow.get("closed"):
        raise TaskError("the task has ended")
    if task.flow.get("question"):
        raise TaskError("a question is waiting: `answer` it first")
    expected = "research" if args.stage == "Implement" and args.research else PHASE_OF[args.stage]
    if task.flow["phase"] != expected:
        raise TaskError(f"the task is in phase {task.flow['phase']!r}, not {expected!r}")
    if args.agent_session:
        task.flow.setdefault("sessions", {})[args.stage] = args.agent_session
    recorder(task, args)
    print(json.dumps({"recorded": args.stage, "phase": task.flow["phase"], "status": task.doc["status"]}))
    return 0


# ---------------------------------------------------------------- answer


def parse_answers(text, questions):
    try:
        given = json.loads(text)
    except ValueError as exc:
        raise TaskError(f"the answer is not valid JSON: {exc}")
    if not isinstance(given, dict) or not all(isinstance(v, str) for v in given.values()):
        raise TaskError("the answer must be a JSON object of question id to answer text")
    wanted = {item["id"] for item in questions}
    if set(given) != wanted:
        raise TaskError("the answer must hold exactly the question ids: " + ", ".join(sorted(wanted)))
    return given


def store_answers(task, given):
    path = task.path("answers.json")
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        stored = {}
    if not isinstance(stored, dict):
        stored = {}
    stored.update(given)
    invoice.write_atomic(path, json.dumps(stored, indent=2) + "\n")


def accept_open_items(task, items):
    """Renders the open items as a follow-up plan that is not run and ends the task `done`."""
    flow = task.flow
    path, number = fix_plan(task, items, None)
    text = plan_format.ensure_header_line(path.read_text(encoding="utf-8"), "Project", project_slug(task.root))
    target = journal_target(task, number)
    if target is not None:
        text = plan_format.ensure_header_line(text, "Journal", str(target), after=("Project",))
        file_copy(target, text)
    path.write_text(text, encoding="utf-8")
    task.doc["status"] = "done"
    flow["phase"] = "finish"
    flow["accepted"] = path.name
    flow["open"] = []
    task.stage_event("stage.completed", "Cycles", outcome="done", accepted=len(items))


def answer_cycles(task, choice, items):
    option, extra = choice
    flow = task.flow
    if option == "Continue":
        path, number = fix_plan(task, items, extra or None)
        reason = flow["open_reason"]
        adopt_plan(task, path, number, "qa" if reason == "checks" else "review")
        task.doc["loop_limit"] += 1
        enter_cycle(task, task.cycle + 1, [reason] + (["instruction"] if extra else []))
    elif option == "Accept":
        accept_open_items(task, items)
    else:
        stop_run(task, "Cycles", f"stopped at the loop limit with {len(items)} open item(s)")


def answer_handback(task, choice):
    option, _ = choice
    flow = task.flow
    if option.startswith("Revise"):
        flow["spec_mode"] = "revise"
        flow["phase"] = "spec"
    elif option.startswith("Plan"):
        flow["plan_against_spec_as_written"] = True
        flow["phase"] = "plan"
    else:
        stop_run(task, "Plan", "stopped after repeated spec hand-backs")


def answer_plan(task, choice):
    option, extra = choice
    flow = task.flow
    if option == "Approve":
        flow["phase"] = "implement"
    elif option == "Revise":
        flow["plan_revision"] = extra
        flow["attempt"] += 1
        task.doc["stages"]["Plan"] = "pending"
        flow["phase"] = "plan"
    else:
        stop_run(task, "Plan", "stopped at the plan gate")


def answer_replan(task, choice):
    if choice[0] == "Re-plan":
        task.flow["phase"] = "plan"
    else:
        stop_run(task, "Plan", "stopped: the implementer kept sending the plan back")


def answer_blocker(task, choice):
    option, extra = choice
    blocked = task.flow["blocked"]
    if option == "Retry":
        task.flow["context"] = {
            "round": blocked["round"], "step": blocked["step"],
            "text": f"The step was blocked: {blocked['text']} The user's answer: {extra or 'retry as it is.'}"}
        task.flow["phase"] = "implement"
    else:
        stop_run(task, "Implement", f"stopped at a blocker on step {blocked['step']}: {blocked['text']}")


def answer_preflight(task, choice):
    if choice[0] == "Continue":
        after_preflight(task)
    else:
        stop_run(task, "Implement", "stopped: the fast gate was red before the run")


ANSWERS = {"cycles": answer_cycles, "handback": answer_handback, "preflight": answer_preflight,
           "plan": answer_plan, "replan": answer_replan, "blocker": answer_blocker}


def cmd_answer(args):
    task = open_task(args)
    question = task.flow.get("question")
    if not question:
        raise TaskError("no question is waiting")
    given = parse_answers(read_text(args.answer_file, "answer file"), question["questions"])
    kind = question["kind"]
    choice = choose(given[kind], CHOICES[kind]) if kind in CHOICES else None
    if kind == "plan" and choice[0] == "Revise" and not choice[1]:
        raise TaskError("a Revise answer needs the changes after it: `Revise: <what to change>`")

    store_answers(task, given)
    for item in question["questions"]:
        task.queue("user.input_answered", {"stage": question["stage"], "cycle": task.cycle,
                                           "answer": given[item["id"]]})
    task.flow["question"] = None
    if kind == "agent":
        task.flow["resume"] = {"stage": question["stage"], "name": question["name"],
                               "session_id": question.get("session")}
    elif kind == "cycles":
        answer_cycles(task, choice, task.flow["open"])
    else:
        ANSWERS[kind](task, choice)
    task.commit()
    print(json.dumps({"answered": question["stage"], "phase": task.flow["phase"], "status": task.doc["status"]}))
    return 0


# ---------------------------------------------------------------- finish and stop


def register_run_sessions(task):
    """Files every session recorded for the project since the task began in the journal
    entry's analytics folder, one row per round with that round's start as its `since`, so
    the invoice bills each response to the round that was running. Rows already in
    `sessions.json` are kept. A round with no recorded start (a `progress.json` from before
    they were kept) gets no row, and its usage stays with the round before it."""
    folder = task.flow.get("journal")
    if not folder or journal.journal_root() is None:
        return
    entry = Path(folder)
    if not entry.is_dir():
        return
    starts = {item["round"]: item["started"] for item in task.flow.get("round_starts", [])}
    rounds = [(entry_round["round"], starts[entry_round["round"]])
              for entry_round in task.doc["rounds"] if entry_round["round"] in starts]
    started = invoice.parse_time(task.doc.get("started"))
    try:
        for row in journal.recorded_sessions(task.root, after=started):
            for number, since in rounds:
                journal.register_session(entry, str(row["session_id"]), str(row.get("transcript_path") or ""),
                                         number, "execute", since=since)
    except OSError as exc:
        note(f"the run's sessions were not registered in the journal: {exc}")


def usage_recorded(task):
    """Whether the plugin has written the entry's `usage.json`: the invoice prices that
    file, and a task run with nothing recorded has no invoice to regenerate."""
    folder = task.flow.get("journal")
    return bool(folder) and (Path(folder) / invoice.USAGE_FILE).is_file()


def close_in_journal(task, report_path, plan):
    """Files the report in the plan's journal round and regenerates the invoice when the
    entry has a `usage.json`, as `plan-progress.py complete` does; a failure is a note,
    never a failed `finish`."""
    if journal.journal_root() is None:
        return
    quiet = io.StringIO()
    try:
        with contextlib.redirect_stdout(quiet):
            journal.cmd_report(argparse.Namespace(plan=str(plan), report_file=str(report_path)))
            if usage_recorded(task):
                script("plan-progress").write_invoice_for(plan.read_text(encoding="utf-8"))
    except SystemExit:
        note("the report was not filed in the journal: " + quiet.getvalue().strip())


def cmd_finish(args):
    task = open_task(args)
    if task.flow.get("closed"):
        raise TaskError("the task has already ended")
    if task.flow["phase"] != "finish" and task.doc["status"] != "done":
        raise TaskError(f"the task is in phase {task.flow['phase']!r}, not ready to finish")
    report = read_text(args.report_file, "report file")
    if not report.strip():
        raise TaskError("the report is empty")

    plan = task.path(task.doc["rounds"][-1]["plan"]) if task.doc["rounds"] else task.path("plan-01.md")
    task.doc["status"] = "done"
    task.doc["stages"]["Implement"] = "done"
    task.flow["closed"] = True
    task.save()
    report_path = task.path("report.md")
    report_path.write_text(report.strip() + "\n", encoding="utf-8")

    register_run_sessions(task)
    script("plan-progress").write_closing_events(plan, plan.read_text(encoding="utf-8"), task.doc)
    close_in_journal(task, report_path, plan)
    print(json.dumps({"finished": task.doc["task"], "report": str(report_path)}))
    return 0


def cmd_stop(args):
    task = open_task(args)
    if task.flow.get("closed"):
        raise TaskError("the task has already ended")
    reason = sys.stdin.read() if args.reason == "-" else args.reason
    reason = " ".join(reason.split()) or "stopped without a stated reason"
    stop_run(task, task.doc["stage"], reason)
    task.commit()
    print(json.dumps({"stopped": task.doc["task"], "reason": reason}))
    return 0


def main():
    parser = argparse.ArgumentParser(prog="task.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    def command(name, func, help_text, task=True):
        sub = commands.add_parser(name, help=help_text)
        sub.add_argument("--root", help="the repository (default: the one around the current directory)")
        if task:
            sub.add_argument("--task", required=True, help="the task folder, absolute or relative to --root")
        sub.set_defaults(func=func)
        return sub

    start = command("start", cmd_start, "create a task folder and its progress.json", task=False)
    start.add_argument("--title", required=True, help="the task's title, at most six words")
    start.add_argument("--prompt-file", required=True, help="file holding the prompt, or - for stdin")
    start.add_argument("--plan", help="start from this plan instead of a prompt")
    start.add_argument("--spec", help="start from this spec file: Refine and Spec are skipped")

    following = command("next", cmd_next, "print the next action as one JSON object")
    following.add_argument("--resume-failed", action="store_true",
                           help="the last `resume` could not reach its agent: spawn a fresh one")

    record = command("record", cmd_record, "record a stage's hand-off")
    record.add_argument("--stage", required=True, choices=sorted(RECORDERS))
    record.add_argument("--agent-session", help="the child session the subagent tool returned for this stage")
    record.add_argument("--exit-code", type=int, help="Preflight: the fast gate's exit status")
    record.add_argument("--duration-ms", type=int, help="Preflight: how long the fast gate ran")
    record.add_argument("--blocker-file", help="Implement: JSON {kind, text, step} of a blocked step, or -")
    record.add_argument("--research", help="Implement: the findings file the researcher filed")

    answer = command("answer", cmd_answer, "give the answers to the waiting question")
    answer.add_argument("--answer-file", required=True,
                        help="JSON object of question id to answer, or - for stdin")

    finish = command("finish", cmd_finish, "close a green task and file its report")
    finish.add_argument("--report-file", required=True, help="file holding the final report, or - for stdin")

    stop = command("stop", cmd_stop, "end the task as failed")
    stop.add_argument("--reason", required=True, help="why the task stopped, or - for stdin")

    args = parser.parse_args()
    try:
        return args.func(args)
    except SpecError as exc:
        print(f"task: {exc}", file=sys.stderr)
        return 2
    except TaskError as exc:
        print(f"task: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
review-findings.py — turn the end-of-run strict review's findings into a plan.

Ships with the `hoko` plugin.

    review-findings.py --from <findings.json> --root <repo> [--plan <current plan>]

The strict review reports as JSON, not prose, because a follow-up plan is read by a
fresh session that never saw the review run and has nothing else to go on. Each
element is a finding — `severity`, `file`, `line`, `summary`, `fix`, `scenario` — and
this script renders one step per finding, most severe first, into a plan file this
repository's own conventions can run: a `## Goal`, one `R<N>` requirement per finding
stated in EARS form (never naming the file — that belongs on the step, not the
requirement, or `plan-lint.py` calls it implementation), a full `## Progress` section,
and a `## Steps` section a plan run can execute exactly like any other plan.

Only `blocking` and `important` findings are actionable. Every other severity (`nit`,
`suggestion`, `learning`, `praise`) is skipped, with a count of how many on stderr, since
nobody has checked they hold up as a plan step. A finding's `scenario` — the concrete
input or state and the wrong result it leads to — renders into its step as its own line;
a finding with no `scenario` still renders, with that line reading `not given`.

Writes the plan into the configured plans directory (`settings.py plansDir`, under
`--root`) and prints its absolute path. No actionable finding left after filtering means
nothing to follow up on, so nothing is written; malformed JSON means the review's own
output cannot be trusted, so nothing is written either — both are reported on stderr and
exit non-zero.

Without `--plan` the file is `<YmdHis>-review-followup-<slug>.md`, titled
`Review follow-up: <findings file stem>`.

`--plan <current plan>` names the follow-up after its parent instead — `<round-1
stem>--r<NN>.md`, titled `<parent title> (round <NN>)` — so the name and the title stay
the same length from one round to the next (`followup.py`). NN is the first round after the
parent's own that is free both as `<name>.md` in the plans directory and, when the parent
has a journal entry, as `plan-NN.md` there, so the name, the title and the journal copy
always agree.

Beside the follow-up it writes `<name>.progress.json` (`progress.py`), one `pending`
entry per step, so a run that starts from it has its progress file from the first step.

It also chains the follow-up into the current plan's own journal round: when that plan's
`Journal:` line names an existing `plan-NN.md`, the follow-up plan carries the parent's
own `## Decisions` and `## Test conventions` sections, and gets a `Project:` line (copied
from the current plan) and a `Journal:` line naming `plan-<NN>.md` for the same round
number as the follow-up's name and title. It is also written there, next to the parent's
round, verbatim. When the current plan has no `Journal:` line, only the name and the title
change.
"""

import argparse
import datetime
import json
import re
import sys
from pathlib import Path

import followup
import journal
import plan_format
import settings

ACTIONABLE_SEVERITIES = {"blocking", "important"}


def die(message):
    print(f"review-findings: {message}", file=sys.stderr)
    sys.exit(1)


def slugify(text):
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "findings"


def load_findings(path):
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        die(f"cannot read {path}: {exc}")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        die(f"{path} is not valid JSON: {exc}")
    if not isinstance(data, list):
        die(f"{path} must hold a JSON array of findings")
    return data


def actionable_only(findings, path):
    actionable = [f for f in findings
                  if str(f.get("severity", "")).lower() in ACTIONABLE_SEVERITIES]
    skipped = len(findings) - len(actionable)
    if skipped:
        print(f"review-findings: skipped {skipped} non-actionable finding(s)", file=sys.stderr)
    if not actionable:
        die(f"{path} names no findings — nothing to follow up on")
    return actionable


def copied_section(text, name):
    """The parent plan's `## <name>` section, heading included, or None when it has
    no such section."""
    span = plan_format.section_span(text, name)
    if span is None:
        return None
    start, end = span
    return text[start:end].rstrip("\n") + "\n"


def insert_section_before(body, section_text, before_heading):
    """`body` with `section_text` spliced in right before its `## <before_heading>`
    heading, a blank line either side. Appended at the end instead when that heading
    is missing — `render()` always writes Requirements and Progress, so this should
    not happen."""
    match = re.search(rf"^##\s+{re.escape(before_heading)}\s*$", body, re.M)
    if match is None:
        return body.rstrip("\n") + "\n\n" + section_text + "\n"
    idx = match.start()
    return body[:idx] + section_text + "\n" + body[idx:]


def read_parent(plan_arg):
    plan_path = Path(plan_arg).expanduser()
    if not plan_path.is_file():
        die(f"no plan file at {plan_path}")
    return plan_path, plan_path.read_text(encoding="utf-8")


def journal_entry_of(plan_text):
    """The journal entry folder and the round of the `plan-NN.md` the plan's `Journal:`
    line points to, or (None, 0) when the plan has no journal entry on disk."""
    target = journal.journal_plan(plan_text)
    match = journal.ROUND.match(target.name) if target is not None else None
    if match is None or not target.is_file():
        return None, 0
    return target.parent, int(match.group(1))


def chain_into_journal(body, plan_path, plan_text, follow_up_path):
    """D11: copies the parent's `## Decisions` and `## Test conventions` sections into
    `body`, stamps it with the parent's `Project:` and a `Journal:` line for
    `follow_up_path`, and writes it there, next to the parent's journal round. Returns
    the stamped body."""
    project = (plan_format.header_line(plan_text, "Project")
               or journal.resolve_project(None, plan_path, None))

    decisions = copied_section(plan_text, "Decisions")
    if decisions:
        body = insert_section_before(body, decisions, "Requirements")

    test_conventions = copied_section(plan_text, "Test conventions")
    if test_conventions:
        body = insert_section_before(body, test_conventions, "Progress")

    body = plan_format.ensure_header_line(body, "Project", project)
    body = plan_format.ensure_header_line(body, "Journal", str(follow_up_path), after=("Project",))
    follow_up_path.write_text(body, encoding="utf-8")
    return body


def main():
    parser = argparse.ArgumentParser(prog="review-findings.py", description=__doc__)
    parser.add_argument("--from", dest="findings_path", required=True,
                         help="the review's findings, as a JSON array")
    parser.add_argument("--root", required=True, help="the repository the plan is written into")
    parser.add_argument("--plan", help="the current plan, to name the follow-up after it and chain "
                                        "it into its journal round")
    args = parser.parse_args()

    findings_path = Path(args.findings_path).expanduser()
    findings = followup.ordered(actionable_only(load_findings(findings_path), findings_path))

    root = Path(args.root).expanduser().resolve()
    plans_dir = root / settings.get("plansDir")
    plans_dir.mkdir(parents=True, exist_ok=True)

    run_name = findings_path.stem
    journal_path = None
    number = 1
    if args.plan:
        plan_path, plan_text = read_parent(args.plan)
        entry, journal_round = journal_entry_of(plan_text)
        stem = followup.round_one_stem(plan_path.stem)
        first = max(followup.parent_round(plan_path.stem), journal_round) + 1
        number = followup.pick_round(plans_dir, stem, first, entry)
        if entry is not None:
            journal_path = entry / f"plan-{number:02d}.md"
        subject = followup.base_title(plan_text, plan_path.stem)
        title = followup.round_title(subject, number)
        destination = plans_dir / f"{stem}--r{number:02d}.md"
    else:
        timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        destination = plans_dir / f"{timestamp}-review-followup-{slugify(run_name)}.md"
        subject = run_name
        title = f"Review follow-up: {run_name}"

    try:
        body = followup.render(findings, title, subject)
    except followup.FollowupError as exc:
        die(str(exc))
    if journal_path:
        body = chain_into_journal(body, plan_path, plan_text, journal_path)
    followup.write_plan(destination, body, number)
    print(destination)
    return 0


if __name__ == "__main__":
    sys.exit(main())

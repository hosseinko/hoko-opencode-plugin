#!/usr/bin/env python3
"""
followup.py — render a review's findings into a follow-up plan, and name and title it.

Imported by `review-findings.py`; it never exits or prints, so any caller can render a
follow-up. A problem raises `FollowupError`.

A follow-up of a parent plan is named `<round-1 stem>--r<NN>.md` and titled
`<parent title> (round <NN>)`, so the name and the title stay the same length however
many rounds a task goes through. The double hyphen cannot occur in a slug, so the round
suffix is never mistaken for part of a name.
"""

import re

import journal
import progress

ACTIONABLE_SEVERITIES = {"blocking", "important"}

SEVERITY_RANK = {
    "blocking": 0,
    "important": 1,
}

LEADING_PREFIX = "Review follow-up: "
TRAILING_ROUND = re.compile(r"\s*\(round \d+\)\s*$")
TITLE_LINE = re.compile(r"^#\s+(.+?)\s*$", re.M)


class FollowupError(Exception):
    pass


def one_line(text, fallback):
    collapsed = " ".join(str(text).split())
    return collapsed or fallback


def ordered(findings):
    return sorted(
        findings,
        key=lambda f: SEVERITY_RANK.get(str(f.get("severity", "")).lower(), len(SEVERITY_RANK)),
    )


def round_one_stem(stem):
    """`stem` without its `--r<NN>` round suffix."""
    match = progress.ROUND_SUFFIX.match(stem)
    return match.group(1) if match else stem


def parent_round(stem):
    """The round a plan file stem names: its `--r<NN>` suffix, or 1 without one."""
    return progress.plan_round(stem)


def base_title(parent_text, stem):
    """The parent plan's title with every leading `Review follow-up: ` and trailing
    ` (round N)` removed. The parent's own title is read from its `# ` heading, then
    from `journal.plan_title`, then from its round-1 stem."""
    match = TITLE_LINE.search(parent_text)
    title = match.group(1).strip() if match else journal.plan_title(parent_text)
    title = title or round_one_stem(stem)
    previous = None
    while previous != title:
        previous = title
        while title.startswith(LEADING_PREFIX):
            title = title[len(LEADING_PREFIX):]
        title = TRAILING_ROUND.sub("", title)
    return title.strip() or round_one_stem(stem)


def round_title(base, number):
    return f"{base} (round {number})"


def pick_round(plans_dir, stem, first, journal_entry=None):
    """The first round number from `first` on that is free everywhere the follow-up is
    filed: no `<round-1 stem>--r<NN>.md` in `plans_dir` and, when `journal_entry` is given,
    no `plan-<NN>.md` in it. One number then names the file, titles the plan and files its
    journal copy."""
    number = first
    while (plans_dir / f"{stem}--r{number:02d}.md").exists() or (
            journal_entry is not None and (journal_entry / f"plan-{number:02d}.md").exists()):
        number += 1
    return number


def write_plan(destination, body, number):
    """Writes the follow-up plan and, beside it, its `progress.json` for round
    `number`, one `pending` entry per step."""
    destination.write_text(body, encoding="utf-8")
    progress.init(destination, body, round_number=number, source="review")


def render(findings, title, subject):
    if not findings:
        raise FollowupError("no findings to render")
    if not title.strip():
        raise FollowupError("a follow-up plan needs a title")

    lines = [f"# {title}", "", "## Goal", "",
              f"Fix what the strict review found over {subject} before anything else "
              "from that run is built on top.", "", "## Requirements", ""]

    for i, finding in enumerate(findings, start=1):
        severity = one_line(finding.get("severity", ""), "unrated")
        lines.append(
            f"- **R{i}** When the step for finding {i} runs, the fix shall be applied "
            f"so the {severity} issue is resolved."
        )
    lines += ["", "## Progress", ""]

    titles = [one_line(f.get("summary", ""), f"Address finding {i}")
              for i, f in enumerate(findings, start=1)]
    for i, step_title in enumerate(titles, start=1):
        lines.append(f"- [ ] {i}. {step_title}")
    lines += ["", "## Steps", ""]

    for i, (finding, step_title) in enumerate(zip(findings, titles), start=1):
        file_path = one_line(finding.get("file", ""), "unknown file")
        line_no = finding.get("line", "unknown")
        location = f"`{file_path}`" if line_no is None else f"`{file_path}`:{line_no}"
        severity = one_line(finding.get("severity", ""), "unrated")
        summary = one_line(finding.get("summary", ""), "no summary given")
        scenario = one_line(finding.get("scenario", ""), "not given")
        fix = one_line(finding.get("fix", ""), "no fix given")
        lines += [
            f"### {i}. {step_title}",
            "",
            f"- Finding: {severity} at {location} — {summary}",
            f"- Scenario: {scenario}",
            f"- Fix: {fix}",
            f"- Satisfies: R{i}",
            "",
        ]

    return "\n".join(lines).rstrip() + "\n"

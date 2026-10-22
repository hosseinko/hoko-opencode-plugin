#!/usr/bin/env python3
"""
plan-lint.py — the checks on a plan that a machine can make.

Ships with the `hoko` plugin.

A plan is read by three subagents that cannot see the conversation it came from, so a
requirement no step claims, or an undeclared requirement a step claims, is not caught
until something has already been built against it. None of that needs judgement, so
none of it should cost a model's attention. A plan may point at a spec instead of
restating it: `Spec: <path> (<spec id>: REQ-N, …)` in the header names the file and the
requirements this plan delivers, and a step claims `<spec id>/REQ-N` on its `Satisfies:`
line. The spec's own id comes from its front matter, and every listed requirement must
exist in the file and be claimed by exactly one step. Every finding is either blocking —
it denies approval and makes the CLI exit 1 — or advisory: a style nit or a note the
CLI prints but never denies on.

    plan-lint.py --plan <path> [--root <repo>] [--structural] [--rewrite]

Findings go to stdout: a blocking one as `line <N>: <what>`, an advisory one as
`note: line <N>: <what>`. Exit 0 when nothing blocks, 1 when something does, 2 when the file
cannot be read, or carries no `## ` section at all. `--structural` prints only the
blocking findings and skips the `## Progress` check — the preflight execute-plan runs
before touching a step. `--rewrite` first turns a numbered-list `## Steps`
(`1. **Title.** …`) into `### N. Title` headings in the plan file itself, then judges the
rewritten plan: a blocking finding still exits 1, and a plan that already carries step
headings is left byte for byte. What plan-lint does not check is whether the plan is any
good — that is the reviewer's job, and this is the part that never needed one.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

import plan_format

SATISFIES = re.compile(r"^\s*-\s*Satisfies:\s*(.*?)\s*$", re.M)
CITATION = re.compile(r"`?([\w.\-/]+/[\w.\-]+\.\w{1,5}):(\d+)`?")
RID = re.compile(r"\bR\d+\b")
SPEC_CLAIM = re.compile(r"([\w.\-]+)/(REQ-\d+)\b")
SPEC_READ_LIMIT = 1_000_000

# Word-boundary matched, so "the handler shall" survives and "shall handle" does not.
BANNED = ("will", "should", "efficient", "robust", "gracefully", "as appropriate",
          "handle", "handles", "TBD")
BANNED_RE = re.compile(r"\b(" + "|".join(BANNED) + r")\b", re.I)

# Implementation, not behaviour. A bare component name is what the protocol asks for,
# so only what could not be anything but code counts here.
IMPLEMENTATION = re.compile(r"::|\(\)|\b[\w/]+\.(?:php|py|ts|tsx|js|go|rs|sql)\b")

# A step titled to verify rather than change comes back from plan-executor as a no-op —
# see step-commit.py's --no-op mode — so its empty diff is not a defect worth blocking on.
VERIFY_TITLE = re.compile(r"^(Verify|Validate|Test|Run)\b", re.I)

BLOCKING = "block"
ADVISORY = "note"


def line_of(text, index):
    return text.count("\n", 0, index) + 1


class Findings(list):
    def add(self, line, message, severity=BLOCKING):
        self.append((line, message, severity))


def repo_root(start_dir, explicit):
    """The git top level of `start_dir`, or `explicit` when given, or `start_dir`
    itself when it is not inside a git repository."""
    if explicit:
        return Path(explicit).expanduser().resolve()
    try:
        result = subprocess.run(
            ["git", "-C", str(start_dir), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return Path(result.stdout.strip())
    except Exception:
        pass
    return Path(start_dir)


def step_bodies(text):
    """(number, title, line, body) per step, the body bounded by the next step or the end of `## Steps`."""
    steps_span = plan_format.section_span(text, "Steps")
    marks = plan_format.step_matches(text)
    out = []
    for i, mark in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else (steps_span[1] if steps_span else len(text))
        out.append((int(mark.group(1)), mark.group(2), line_of(text, mark.start()),
                    text[mark.end():end]))
    return out


def check_sections(text, findings):
    if plan_format.section_span(text, "Steps") is None:
        findings.add(1, "no `## Steps` section — the plan is not in the plan format")
    # `## Context` is an accepted heading for the same thing a `## Goal` says; either
    # satisfies the reader, so only having neither is a finding.
    if (plan_format.section_span(text, "Goal") is None
            and plan_format.section_span(text, "Context") is None):
        findings.add(1, "no `## Goal` section — say what the plan is for", ADVISORY)


def check_steps(steps, findings):
    if not steps:
        findings.add(1, "no `### <N>. <title>` step headings — a plan needs at least one step "
                        "(`Step` prefix and `:`/`)`/dash separators accepted)")
        return
    seen = {}
    for number, title, line, body in steps:
        if number in seen:
            findings.add(line, f"step {number} appears twice (also on line {seen[number]})")
        seen[number] = line
    expected = list(range(1, len(steps) + 1))
    if sorted(seen) != expected:
        findings.add(steps[0][2], f"steps are numbered {sorted(seen)}, expected {expected}")

    for number, title, line, body in steps:
        # `Satisfies:` is what ties a step to the behaviour it owes. A step without it
        # does not fail here, it fails mid-run with the work already done.
        if not SATISFIES.search(body):
            findings.add(line, f"step {number} has no `Satisfies:` line — say `none — internal` if it delivers no requirement", ADVISORY)
        match = VERIFY_TITLE.match(title)
        if match:
            findings.add(line, f"step {number} is titled to {match.group(1).lower()}, not change — an empty diff there is not a defect", ADVISORY)


def check_progress(text, steps, findings):
    if plan_format.section_span(text, "Progress") is None:
        findings.add(1, "no `## Progress` section — it is how a run knows where it got to")
        return
    boxes = [(int(m.group(2)), m.group(3), line_of(text, m.start()))
             for m in plan_format.progress_box_matches(text)]
    by_number = {number: (title, line) for number, title, line in boxes}
    if len(by_number) != len(boxes):
        findings.add(boxes[0][2], "a step number appears twice in `## Progress`")
    for number, title, line in steps:
        if number not in by_number:
            findings.add(line, f"step {number} has no box in `## Progress`")
        elif by_number[number][0] != title:
            findings.add(by_number[number][1],
                         f"box {number} reads {by_number[number][0]!r}, the step heading reads {title!r}")
    for number, (_, line) in by_number.items():
        if number not in {n for n, _, _ in steps}:
            findings.add(line, f"`## Progress` has a box {number} with no step to match")


def check_requirements(text, findings):
    declared = {}
    for m in plan_format.requirement_matches(text):
        rid, body, line = m.group(1), m.group(2), line_of(text, m.start())
        if rid in declared:
            findings.add(line, f"{rid} is declared twice (also on line {declared[rid]})")
        declared[rid] = line
        if " shall " not in body:
            findings.add(line, f"{rid} has no ` shall ` — it is not stated as a requirement")
        for word in sorted({w.group(1).lower() for w in BANNED_RE.finditer(body)}):
            findings.add(line, f"{rid} says {word!r} — nothing that cannot fail a test", ADVISORY)
        found = IMPLEMENTATION.search(body)
        if found:
            findings.add(line, f"{rid} names implementation ({found.group(0)!r}) — that belongs in *Decisions*", ADVISORY)
    return declared


def read_spec(reference, root, plan_dir):
    """The text of the spec a `Spec:` line names, tried as an absolute path, then
    against the repository root, then against the plan's own folder (a task's local
    `spec.md`). None when no candidate is a readable file."""
    path = Path(reference.path).expanduser()
    candidates = [path] if path.is_absolute() else [root / path]
    if not path.is_absolute() and plan_dir is not None:
        candidates.append(plan_dir / path)
    for candidate in candidates:
        try:
            with candidate.open(encoding="utf-8", errors="replace") as handle:
                return handle.read(SPEC_READ_LIMIT)
        except OSError:
            continue
    return None


def check_specs(text, root, plan_dir, findings):
    """Resolve every `Spec:` header line against the spec file it names. Returns
    `{spec id: (listed REQ ids, live REQ ids the spec declares or None when it could not be
    read, line of the first line naming it, REQ ids the spec marks retired)}` — what `check_satisfies` claims against."""
    specs = {}
    for reference in plan_format.spec_references(text):
        if not reference.well_formed:
            findings.add(reference.line, "`Spec:` line is not `<path> (<spec id>: REQ-N, REQ-M)`")
            continue
        spec_text = read_spec(reference, root, plan_dir)
        declared = None
        retired = set()
        if spec_text is None:
            findings.add(reference.line, f"`Spec:` names {reference.path}, and there is no such file")
        else:
            declared = plan_format.spec_requirement_ids(spec_text)
            retired = plan_format.retired_requirement_ids(spec_text)
            actual_id = plan_format.spec_id(spec_text)
            if actual_id is None:
                findings.add(reference.line, f"{reference.path} has no `id:` in its front matter")
            elif actual_id != reference.spec_id:
                findings.add(reference.line,
                             f"`Spec:` calls {reference.path} {reference.spec_id}, its front matter says {actual_id}")
            for req in reference.reqs:
                if req in retired:
                    findings.add(reference.line,
                                 f"`Spec:` lists {req}, which {reference.spec_id} has retired")
                elif req not in declared:
                    findings.add(reference.line,
                                 f"`Spec:` lists {req}, which {reference.spec_id} does not contain")
        listed, known, line, known_retired = specs.get(
            reference.spec_id, (set(), None, reference.line, set()))
        specs[reference.spec_id] = (listed | set(reference.reqs),
                                    declared if known is None else known, line,
                                    known_retired | retired)
    return specs


def check_satisfies(text, declared, findings, specs=None):
    specs = specs or {}
    claimed = {}

    def claim(key, line):
        if key in claimed:
            findings.add(line, f"{key} is claimed twice (also on line {claimed[key]})")
        else:
            claimed[key] = line

    for m in SATISFIES.finditer(text):
        body, line = m.group(1), line_of(text, m.start())
        ids = RID.findall(body)
        refs = SPEC_CLAIM.findall(body)
        if not ids and not refs:
            if "none" not in body.lower():
                findings.add(line, "`Satisfies:` lists no requirement and does not say `none — internal`", ADVISORY)
            continue
        for rid in ids:
            if rid not in declared:
                findings.add(line, f"`Satisfies:` claims {rid}, which no requirement declares")
            else:
                claim(rid, line)
        for spec_id, req in refs:
            key = f"{spec_id}/{req}"
            if spec_id not in specs:
                findings.add(line, f"`Satisfies:` claims {key}, and no `Spec:` line names {spec_id}")
                continue
            listed, contents, _, retired = specs[spec_id]
            if req in retired:
                findings.add(line, f"`Satisfies:` claims {key}, which {spec_id} has retired")
            elif contents is not None and req not in contents:
                findings.add(line, f"`Satisfies:` claims {key}, which {spec_id} does not contain")
            elif req not in listed:
                findings.add(line, f"`Satisfies:` claims {key}, which the `Spec:` line does not list")
            else:
                claim(key, line)
    for rid, line in declared.items():
        if rid not in claimed:
            findings.add(line, f"{rid} is claimed by no step — either a step owes it or it is not a requirement")
    for spec_id, (listed, contents, line, retired) in specs.items():
        for req in sorted(listed, key=lambda r: int(r.split("-")[1])):
            if req in retired or (contents is not None and req not in contents):
                continue
            if f"{spec_id}/{req}" not in claimed:
                findings.add(line, f"{spec_id}/{req} is claimed by no step — either a step owes it or the `Spec:` line should not list it")


def check_citations(text, root, findings):
    for m in CITATION.finditer(text):
        path, number, line = m.group(1), int(m.group(2)), line_of(text, m.start())
        target = root / path
        if not target.is_file():
            findings.add(line, f"cites {path}:{number}, and there is no such file", ADVISORY)
            continue
        try:
            length = sum(1 for _ in target.open(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if number > length:
            findings.add(line, f"cites {path}:{number}, and that file has {length} lines", ADVISORY)


def lint(text, root, include_progress=True, plan_dir=None):
    """Every check plan-lint makes, in one place. Returns `(findings, malformed)` —
    `malformed` is true only when the text carries no `## ` heading at all, which is
    not a formatting nit but proof this is not a plan; nothing else is checked then.
    `include_progress` is off for `--structural`: `## Progress` is generated on
    approval, not hand-written, so it is not part of the preflight. `plan_dir`
    is where a `Spec:` path is tried after the repository root."""
    if not plan_format.sections(text):
        return Findings([(1, "no `## ` sections — the plan is not in the plan format", BLOCKING)]), True

    findings = Findings()
    steps = step_bodies(text)
    check_sections(text, findings)
    check_steps(steps, findings)
    if include_progress:
        check_progress(text, [(n, title, line) for n, title, line, _ in steps], findings)
    declared = check_requirements(text, findings)
    specs = check_specs(text, root, plan_dir, findings)
    check_satisfies(text, declared, findings, specs)
    check_citations(text, root, findings)
    return findings, False


def rewrite_list_steps(path, text):
    """`(text, changed)`: `text` with a numbered-list `## Steps` turned into step headings
    and written back to `path`. The original text and `False` when nothing changed or
    the file cannot be written."""
    rewritten = plan_format.normalise_list_steps(text)
    if rewritten == text:
        return text, False
    try:
        path.write_text(rewritten, encoding="utf-8")
    except OSError:
        return text, False
    return rewritten, True


def main():
    parser = argparse.ArgumentParser(prog="plan-lint.py", description=__doc__)
    parser.add_argument("--plan", help="absolute path to the plan file")
    parser.add_argument("--root", help="the repository the plan's paths are relative to")
    parser.add_argument("--structural", action="store_true",
                        help="report only the findings that block approval, and skip `## Progress`")
    parser.add_argument("--rewrite", action="store_true",
                        help="rewrite a numbered-list `## Steps` into `### <N>.` headings in place first")
    args = parser.parse_args()

    if not args.plan:
        parser.error("--plan is required")

    plan = Path(args.plan).expanduser()
    try:
        text = plan.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"plan-lint: cannot read {plan}: {exc}", file=sys.stderr)
        return 2

    if args.rewrite:
        text, _ = rewrite_list_steps(plan, text)

    root = repo_root(plan.resolve().parent, args.root)
    findings, malformed = lint(text, root, include_progress=not args.structural,
                               plan_dir=plan.resolve().parent)
    if malformed:
        print(f"plan-lint: {plan} has no `## ` sections — it is not in the plan format", file=sys.stderr)
        return 2

    blocked = False
    for line, message, severity in sorted(findings, key=lambda f: (f[0], f[1])):
        if severity == BLOCKING:
            blocked = True
            print(f"line {line}: {message}")
        elif not args.structural:
            print(f"note: line {line}: {message}")
    return 1 if blocked else 0


if __name__ == "__main__":
    sys.exit(main())

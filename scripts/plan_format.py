#!/usr/bin/env python3
"""
plan_format.py — the one grammar every plan parser reads by.

Ships with the `hoko` plugin. Not a CLI: a stdlib module `plan-lint.py`,
`plan-progress.py`, `plan-slice.py`, `plan-find.py`, `journal.py` and
`review-findings.py` import instead of each carrying its own copy of the same regex.

A plan's `## ` headings split it into top-level sections; nothing below a `### N.` or
`- [ ] N.` line belongs to the document until the section it is read under says so —
a `### 1.` under `## Verification`, or a `- [ ] 1.` quoted inside a fenced example, is
prose, not a step or a box. `sections()` finds the headings; `step_matches()`,
`progress_box_matches()` and `requirement_matches()` each look only inside their own
section — `## Steps`, `## Progress`, `## Requirements` — and `is_complete()` looks only
in the header block above the first section. All four skip a match sitting inside a
fenced code block (``` or ~~~), so a plan that quotes another plan as an example is
never mistaken for one. `spec_references()` reads the `Spec: <path> (<id>: REQ-N, …)`
header lines of a plan that points at a spec instead of restating its requirements;
`irreversible_steps()` reads the `- Irreversible: <text>` line of each step.
`spec_id()`, `spec_requirement_ids()` (live ids) and `retired_requirement_ids()` read
the spec file those lines name.
`header_line()` and `ensure_header_line()` read and write the `Project:`, `Journal:`,
`Base:` and `Status:` lines of the header block, so a look-alike line inside a fenced
example is never mistaken for the plan's own.
"""

import re

FENCE_LINE = re.compile(r"^[ \t]*(`{3,}|~{3,})", re.M)
SECTION = re.compile(r"^##\s+(.+?)\s*$", re.M)
STEP = re.compile(r"^###\s*(?:step\s+)?(\d+)\s*[.:)\-–—]\s*(.*?)\s*$", re.I | re.M)
LIST_STEP = re.compile(r"^(\d+)\.[ \t]+\*\*(.+?)\*\*[ \t]*(.*)$", re.M)
PROGRESS_BOX = re.compile(r"^\s*-\s*\[([ xX])\]\s*(\d+)\s*\.\s*(.*?)\s*$", re.M)
REQUIREMENT = re.compile(r"^\s*-\s*\*\*(R\d+)\b[^*]*\*\*\s*(.*?)\s*$", re.M)
STATUS_COMPLETE = re.compile(r"^(?:\*\*Status:\*\*|Status:)\s*complete\b", re.M | re.I)
STATUS_LINE = re.compile(r"^(?:\*\*Status:\*\*|Status:)\s*.*$", re.M | re.I)
BASE_LINE = re.compile(r"^Base:\s*(\S+)\s*$", re.M)
TITLE_LINE = re.compile(r"^#[ \t]+.*$", re.M)
IRREVERSIBLE_LINE = re.compile(r"^[ \t]*-[ \t]+Irreversible:[ \t]*(.*?)[ \t]*$", re.M)
SPEC_LINE = re.compile(r"^Spec:[ \t]*(.*?)[ \t]*$", re.M)
SPEC_REFERENCE = re.compile(
    r"^(\S+)[ \t]*\([ \t]*([\w.\-]+)[ \t]*:[ \t]*(REQ-\d+(?:[ \t]*,[ \t]*REQ-\d+)*)[ \t]*\)$")
SPEC_REQUIREMENT = re.compile(r"^\s*-\s*\*\*(REQ-\d+)\b[^*]*\*\*", re.M)
SPEC_RETIRED = re.compile(r"^\s*-\s*\*\*(REQ-\d+)\*\*[ \t]*_Retired\._[ \t]*$", re.M)
FRONT_MATTER = re.compile(r"\A---[ \t]*\n(.*?)\n---[ \t]*(?:\n|\Z)", re.S)
FRONT_MATTER_ID = re.compile(r"^id:[ \t]*(\S+)[ \t]*$", re.M)


def project_name(text):
    """The project name on the plan's `Project:` line — its first whitespace-delimited
    token, so an annotation after it (`(branch …)`) never reaches a folder name or a
    match. Read from the header block only. None when the plan has no such line or the
    line is empty."""
    value = header_line(text, "Project")
    return value.split()[0] if value else None


class SpecReference:
    """One `Spec: <path> (<spec id>: REQ-N, REQ-M)` header line. `spec_id` is None and
    `reqs` empty when the line does not follow that shape."""

    def __init__(self, line, path, spec_id, reqs):
        self.line = line
        self.path = path
        self.spec_id = spec_id
        self.reqs = reqs

    @property
    def well_formed(self):
        return self.spec_id is not None


def spec_references(text):
    """The `Spec:` lines of the plan's header block, outside fenced code, in file order.
    A plan with none gives `[]`."""
    found = sections(text)
    header_end = len(header_block(text, found))
    out = []
    for m in _scoped_matches(SPEC_LINE, text, 0, header_end):
        body = m.group(1)
        line = line_of(text, m.start())
        parsed = SPEC_REFERENCE.match(body)
        if not parsed:
            out.append(SpecReference(line, body.split()[0] if body.split() else "", None, []))
            continue
        reqs = [r.strip() for r in parsed.group(3).split(",")]
        out.append(SpecReference(line, parsed.group(1), parsed.group(2), reqs))
    return out


def spec_id(spec_text):
    """The `id:` in a spec file's front matter, or None."""
    front = FRONT_MATTER.match(spec_text)
    if not front:
        return None
    match = FRONT_MATTER_ID.search(front.group(1))
    return match.group(1) if match else None


def retired_requirement_ids(spec_text):
    """The `REQ-N` ids a spec keeps only as `- **REQ-N** _Retired._` list items, outside
    fenced code."""
    return {m.group(1) for m in _scoped_matches(SPEC_RETIRED, spec_text)}


def spec_requirement_ids(spec_text):
    """The live `REQ-N` ids a spec declares as `- **REQ-N** …` list items, outside fenced
    code. A retired id is not live: see `retired_requirement_ids()`."""
    declared = {m.group(1) for m in _scoped_matches(SPEC_REQUIREMENT, spec_text)}
    return declared - retired_requirement_ids(spec_text)


def line_of(text, index):
    return text.count("\n", 0, index) + 1


def _line_end(text, index):
    newline = text.find("\n", index)
    return len(text) if newline == -1 else newline + 1


def fenced_spans(text):
    """[(start, end)] character ranges covered by fenced code blocks, the opening and
    closing delimiter lines included. A fence opens on a line of 3+ backticks or
    tildes and closes on the next line of the same character, at least as long — a
    nested fence of the other character, or a shorter one, does not close it. An
    unterminated fence runs to the end of the text."""
    spans = []
    open_marker = None
    open_len = 0
    open_start = None
    for m in FENCE_LINE.finditer(text):
        token = m.group(1)
        marker, length = token[0], len(token)
        if open_marker is None:
            open_marker, open_len, open_start = marker, length, m.start()
        elif marker == open_marker and length >= open_len:
            spans.append((open_start, _line_end(text, m.start())))
            open_marker = None
    if open_marker is not None:
        spans.append((open_start, len(text)))
    return spans


def _in_spans(index, spans):
    return any(start <= index < end for start, end in spans)


def _scoped_matches(pattern, text, start=0, end=None, fences=None):
    fences = fenced_spans(text) if fences is None else fences
    end = len(text) if end is None else end
    return [m for m in pattern.finditer(text, start, end) if not _in_spans(m.start(), fences)]


def sections(text):
    """Top-level `## ` sections outside fenced code, in file order, as
    `(name, start, end)` — `end` is the next such section's start, or the end of the
    text."""
    marks = _scoped_matches(SECTION, text)
    out = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        out.append((m.group(1).strip(), m.start(), end))
    return out


def section_span(text, name, found=None):
    """The `(start, end)` span of the top-level section named `name` (case-insensitive,
    a trailing `:` ignored), or None when the plan has no such section."""
    found = sections(text) if found is None else found
    key = name.lower()
    for section_name, start, end in found:
        if section_name.lower().rstrip(":") == key:
            return start, end
    return None


def header_block(text, found=None):
    """Everything above the first top-level section — `Project:`, `Journal:`,
    `Status:`, `Base:`, the plan's own bookkeeping — or the whole text when it has no
    section at all."""
    found = sections(text) if found is None else found
    end = found[0][1] if found else len(text)
    return text[:end]


def step_matches(text, found=None):
    """`### N.` step headings inside `## Steps`, outside fenced code, in file order.
    `[]` when the plan has no `## Steps` section."""
    span = section_span(text, "Steps", found)
    if span is None:
        return []
    start, end = span
    return _scoped_matches(STEP, text, start, end)


def irreversible_steps(text, found=None):
    """`(step number, text)` for each step carrying a `- Irreversible: <text>` list line in
    its body, in file order, ignoring a line inside fenced code or one with no text. A
    step with several such lines is read from the first. `[]` when no step is marked."""
    found = sections(text) if found is None else found
    heads = step_matches(text, found)
    if not heads:
        return []
    fences = fenced_spans(text)
    steps_end = section_span(text, "Steps", found)[1]
    out = []
    for i, head in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else steps_end
        marks = [m for m in _scoped_matches(IRREVERSIBLE_LINE, text, head.end(), end, fences)
                 if m.group(1)]
        if marks:
            out.append((int(head.group(1)), marks[0].group(1)))
    return out


def normalise_list_steps(text, found=None):
    """`text` with a numbered-list `## Steps` rewritten into `### N. Title` headings:
    each column-0 `N. **Title.** rest` item inside `## Steps`, outside fenced code,
    becomes `### N. Title` (the bold text, trailing `.` dropped) with `rest` moved to
    the next line. Indented items, other sections and fenced code are left alone, and
    text that already has `### N.` step headings comes back unchanged."""
    found = sections(text) if found is None else found
    if step_matches(text, found):
        return text
    span = section_span(text, "Steps", found)
    if span is None:
        return text
    out = text
    for m in reversed(_scoped_matches(LIST_STEP, text, span[0], span[1])):
        title = m.group(2).strip().rstrip(".").rstrip()
        heading = f"### {m.group(1)}. {title}"
        rest = m.group(3).strip()
        if rest:
            heading += "\n" + rest
        out = out[:m.start()] + heading + out[m.end():]
    return out


def progress_box_matches(text, found=None):
    """`- [ ] N. <title>` boxes inside `## Progress`, outside fenced code, in file
    order. `[]` when the plan has no `## Progress` section."""
    span = section_span(text, "Progress", found)
    if span is None:
        return []
    start, end = span
    return _scoped_matches(PROGRESS_BOX, text, start, end)


def requirement_matches(text, found=None):
    """`- **RN** <body>` requirement lines inside `## Requirements`, outside fenced
    code, in file order. `[]` when the plan has no `## Requirements` section."""
    span = section_span(text, "Requirements", found)
    if span is None:
        return []
    start, end = span
    return _scoped_matches(REQUIREMENT, text, start, end)


def is_complete(text, found=None):
    """True when the header block carries `Status: complete` or `**Status:**
    complete`, trailing text (` — note`, and so on) allowed."""
    return bool(_scoped_matches(STATUS_COMPLETE, text, 0, len(header_block(text, found))))


def read_base(text):
    """The `Base: <sha>` line from the plan's header block, or None."""
    found = _scoped_matches(BASE_LINE, text, 0, len(header_block(text)))
    return found[0].group(1) if found else None


def _header_key_match(text, key):
    """The first `<key>: …` line of the header block outside fenced code, as a match
    whose group 1 is the trimmed value, or None."""
    pattern = re.compile(rf"^{re.escape(key)}:[ \t]*(.*?)[ \t]*$", re.M)
    found = _scoped_matches(pattern, text, 0, len(header_block(text)))
    return found[0] if found else None


def header_line(text, key):
    """The value of the plan's `<key>: <value>` header line, read from the header block
    only — a line of that shape inside fenced code, or below the first `## ` heading, is
    prose. None when the header has no such line or its value is empty."""
    match = _header_key_match(text, key)
    return (match.group(1) or None) if match else None


def _insert_header_line(text, line, anchors):
    header_end = len(header_block(text))
    fences = fenced_spans(text)
    ends = [m.end() for key in anchors
            for m in [_header_key_match(text, key)] if m]
    if not ends:
        titles = _scoped_matches(TITLE_LINE, text, 0, header_end, fences)
        ends = [titles[0].end()] if titles else []
    if not ends:
        return line + text
    idx = max(ends)
    if idx < len(text) and text[idx] == "\n":
        idx += 1
    elif idx == len(text):
        line = "\n" + line
    return text[:idx] + line + text[idx:]


def ensure_header_line(text, key, value, after=()):
    """`text` with a `<key>: <value>` line in its header block. A no-op when the header
    already has a `<key>:` line, whatever its value. Otherwise the line goes right after
    the last existing header line among the `after` keys, else directly under the `# `
    title, else at the very top — never below the first `## ` heading, and never beside
    a look-alike line inside fenced code."""
    if _header_key_match(text, key):
        return text
    return _insert_header_line(text, f"{key}: {value}\n", after)


def write_status_complete(text):
    """`text` with a `Status: complete` line in its header block: an existing
    `Status:`/`**Status:**` line (any value) is replaced in place, else the line is
    inserted right after `Base:`, else `Journal:`, else `Project:`, else the `# `
    title, else at the very top."""
    match = next(iter(_scoped_matches(STATUS_LINE, text, 0, len(header_block(text)))), None)
    if match:
        return text[:match.start()] + "Status: complete" + text[match.end():]
    return _insert_header_line(text, "Status: complete\n", ("Base", "Journal", "Project"))


def write_base(text, sha):
    """`text` with a `Base: <sha>` line in its header block: updated in place when one
    is already there, else inserted right after `Journal:`, else after `Project:`,
    else after the `# ` title, else at the very top."""
    match = _header_key_match(text, "Base")
    if match:
        return text[:match.start()] + f"Base: {sha}" + text[match.end():]
    return _insert_header_line(text, f"Base: {sha}\n", ("Journal", "Project"))

#!/usr/bin/env python3
"""
journal.py — files the initial prompt, the plan and the outcome of a plan-and-execute
cycle into a per-project journal.

Ships with the `hoko` opencode plugin. Two modes:

  write   Assembles the entry. Copies the prompt and the plan byte-for-byte;
          nothing here summarises or rewrites them.

  report  Appends the run's final report to that same entry, once the plan is done.

The journal root comes from HOKO_JOURNAL_PATH, else "journalPath" in
~/.config/opencode/hoko.json. There is no default: with neither set, journaling is off
and this script says so instead of writing anywhere.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

CONFIGS = (Path.home() / ".config" / "opencode" / "hoko.json",)
STATE_DIR = Path(os.environ.get("HOKO_STATE_DIR") or Path(tempfile.gettempdir()) / "hoko-journal")
PROJECT_MARKERS = (".git", ".ai", ".opencode", ".claude")


def die(message):
    print(f"journal: {message}", file=sys.stderr)
    sys.exit(1)


def journal_root():
    configured = os.environ.get("HOKO_JOURNAL_PATH")
    if not configured:
        for config_path in CONFIGS:
            try:
                config = json.loads(config_path.read_text(encoding="utf-8"))
            except OSError:
                continue
            except json.JSONDecodeError as exc:
                die(f"{config_path} is not valid JSON: {exc}")
            configured = config.get("journalPath")
            if configured:
                break
    if not configured:
        die("HOKO_JOURNAL_PATH is not set — journaling is off. "
            "Set it in hoko.env to keep a journal.")
    return Path(os.path.expandvars(configured)).expanduser()


def git_toplevel(start):
    try:
        result = subprocess.run(
            ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return Path(result.stdout.strip())
    except Exception:
        pass
    return None


def home_path():
    """The home directory with symlinks resolved, so it compares equal to the
    resolved paths this script builds. Falls back to the raw path."""
    home = Path.home()
    try:
        return home.resolve()
    except OSError:
        return home


def project_root(start):
    """The project a path belongs to: its git root, else the nearest ancestor
    holding one of PROJECT_MARKERS. The home directory is never a project."""
    home = home_path()
    top = git_toplevel(start)
    if top is not None and top != home:
        return top
    for candidate in (start, *start.parents):
        if candidate == home or candidate.parent == candidate:
            break
        if any((candidate / marker).exists() for marker in PROJECT_MARKERS):
            return candidate
    return None


def resolve_project(explicit, plan, anchor):
    """Preference order: an explicit override; the project the plugin recorded
    alongside the captured prompt; this process's cwd; the plan's own location."""
    if explicit:
        return slugify(explicit)

    if anchor is not None:
        try:
            recorded = Path(anchor.with_suffix(".project").read_text(encoding="utf-8").strip())
        except OSError:
            recorded = None
        if recorded is not None and recorded.name and recorded != home_path():
            return slugify(recorded.name)

    root = project_root(Path.cwd())
    if root is None and plan is not None:
        root = project_root(plan.parent)
    if root is None and plan is not None:
        # A loose plan file: step over a <marker>/plans/ layout if there is one.
        root = plan.parent
        while root.name in plan_dir_segments() and root != root.parent:
            root = root.parent
    if root is None or root == home_path() or root.name in ("", ".", "/"):
        return "unsorted"
    return slugify(root.name)


def plan_dir_segments():
    """Directory names that are part of a plans path rather than a project name."""
    configured = os.environ.get("HOKO_PLANS_DIR") or ".ai/plans"
    return {*configured.strip("/").split("/"), "plans", ".ai", ".opencode", ".claude"}


def slugify(value, limit=60):
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    if len(value) <= limit:
        return value
    cut = value[:limit]
    return (cut.rsplit("-", 1)[0] if "-" in cut[1:] else cut).strip("-")


def tidy(line, limit=90):
    """One line of plan prose into a title."""
    line = re.sub(r"\s+", " ", line).strip()
    line = re.sub(r"[`*_]", "", line).strip(" .:;,-")
    if len(line) > limit:
        cut = line[:limit]
        line = (cut.rsplit(" ", 1)[0] if " " in cut else cut).rstrip(" .:;,-")
    return line


def plan_title(plan_text):
    """A human title from the plan itself. Plan filenames carry a timestamp and an
    auto-generated slug, so the filename is a last resort, not a title."""
    heading = re.search(r"^#\s+(.+)$", plan_text, re.M)
    if heading:
        title = tidy(heading.group(1))
        if title:
            return title

    goal = re.search(r"^##+\s+Goal\s*$(.*?)(?=^##+\s|\Z)", plan_text, re.M | re.S)
    if goal:
        for line in goal.group(1).splitlines():
            title = tidy(line.lstrip("-*+ "))
            if title:
                return title

    for line in plan_text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith(("#", "-", "*", "+", ">", "|", "`")):
            title = tidy(stripped)
            if title:
                return title
    return ""


def plan_slug(plan):
    stem = re.sub(r"^\d{8,14}[-_]", "", plan.stem)
    return slugify(stem) or "plan"


def fence(text):
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


def latest_entry(folder):
    entries = sorted(folder.glob("*.md"))  # names start with a timestamp
    return entries[-1] if entries else None


def read_text_arg(value, what):
    if value == "-":
        return sys.stdin.read()
    path = Path(value).expanduser()
    if not path.is_file():
        die(f"no {what} at {path}")
    return path.read_text(encoding="utf-8")


def add_frontmatter(text, key, value):
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---\n", 3)
    if end == -1 or re.search(rf"^{key}:", text[4:end], re.M):
        return text
    return f"{text[:end]}\n{key}: {value}{text[end:]}"


def cmd_write(args):
    plan = Path(args.plan).expanduser()
    if not plan.is_file():
        die(f"no plan file at {plan}")
    plan = plan.resolve()
    plan_text = plan.read_text(encoding="utf-8")

    anchor = None
    if args.prompt_file != "-":
        anchor = Path(args.prompt_file).expanduser()
        if not anchor.is_file():
            die(f"no prompt file at {anchor}")
        anchor = anchor.resolve()
    prompt = read_text_arg(args.prompt_file, "prompt file")
    if not prompt.strip():
        die("the prompt is empty")

    project = resolve_project(args.project, plan, anchor)
    title = plan_title(plan_text)
    slug = slugify(args.slug) if args.slug else (slugify(title) or plan_slug(plan))
    if not title:
        title = slug.replace("-", " ")
    now = datetime.now().astimezone()
    stamp = now.strftime("%Y%m%d%H%M%S")

    destination_dir = journal_root() / project
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / f"{stamp}-{slug}.md"
    counter = 2
    while destination.exists():
        destination = destination_dir / f"{stamp}-{slug}-{counter}.md"
        counter += 1

    guard = fence(prompt)
    destination.write_text(
        "---\n"
        f"project: {project}\n"
        f"date: {now.isoformat(timespec='seconds')}\n"
        f"plan: {plan}\n"
        "---\n\n"
        f"# {title[:1].upper()}{title[1:]}\n\n"
        "## Initial prompt\n\n"
        f"{guard}text\n{prompt.strip()}\n{guard}\n\n"
        "## Plan\n\n"
        f"{plan_text.strip()}\n",
        encoding="utf-8",
    )

    if anchor is not None and anchor.parent == STATE_DIR.resolve():
        for used in (anchor, anchor.with_suffix(".project")):
            try:
                used.rename(used.with_name(used.name + ".used"))
            except OSError:
                pass

    print(destination)


def cmd_report(args):
    report = read_text_arg(args.report_file, "report file")
    if not report.strip():
        die("the report is empty")

    if args.entry:
        entry = Path(args.entry).expanduser()
        if not entry.is_file():
            die(f"no journal entry at {entry}")
    else:
        project = resolve_project(args.project, None, None)
        folder = journal_root() / project
        entry = latest_entry(folder)
        if entry is None:
            die(f"no journal entry to append to in {folder} — file the plan first")

    text = entry.read_text(encoding="utf-8")
    filed = len(re.findall(r"^## Final report", text, re.M))
    heading = "## Final report" if not filed else f"## Final report ({filed + 1})"
    now = datetime.now().astimezone()
    text = add_frontmatter(text, "completed", now.isoformat(timespec="seconds"))
    entry.write_text(f"{text.rstrip()}\n\n{heading}\n\n{report.strip()}\n", encoding="utf-8")
    print(entry)


def main():
    parser = argparse.ArgumentParser(prog="journal.py", description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)

    write = modes.add_parser("write", help="write a journal entry")
    write.add_argument("--plan", required=True, help="absolute path to the plan file")
    write.add_argument("--prompt-file", required=True,
                       help="file holding the initial prompt verbatim, or - for stdin")
    write.add_argument("--project",
                       help="override the project name (default: the project recorded with the prompt, else the cwd's project)")
    write.add_argument("--slug",
                       help="override the entry slug (default: from the plan's title or Goal)")

    report = modes.add_parser("report", help="append a final report to an existing entry")
    report.add_argument("--report-file", required=True,
                        help="file holding the final report, or - for stdin")
    report.add_argument("--entry", help="the journal entry to append to (default: the project's newest)")
    report.add_argument("--project", help="override the project name (default: the cwd's project)")

    args = parser.parse_args()
    if args.mode == "report":
        cmd_report(args)
    else:
        cmd_write(args)


if __name__ == "__main__":
    main()

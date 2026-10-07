#!/usr/bin/env python3
"""
journal.py — files a plan cycle's initial prompt and plan, round by round, into a
per-project journal folder.

Ships with the `hoko` opencode plugin. Three modes:

  write     Creates `<journalPath>/<project>/<stamp>-<slug>/`, with the initial prompt
            copied verbatim into `prompt.md` and the plan copied verbatim into
            `plan-01.md`. Prints the `plan-01.md` path.

  report    Reads the `Journal:` line of the given plan and writes `report-NN.md`
            next to the `plan-NN.md` it names, overwriting an earlier report of the
            same round.

  register  Records a session against a journal entry in `sessions.json`, once per
            (session, round, role), so the invoice can find its usage later.

The journal root comes from HOKO_JOURNAL_PATH, else "journalPath" in
~/.config/opencode/hoko.json. There is no default: with neither set, journaling is off
and this script says so instead of writing anywhere.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

CONFIGS = (Path.home() / ".config" / "opencode" / "hoko.json",)
STATE_DIR = Path(os.environ.get("HOKO_STATE_DIR") or Path(tempfile.gettempdir()) / "hoko-journal")
PROJECT_MARKERS = (".git", ".ai", ".opencode", ".claude")
SESSIONS_FILE = "sessions.json"
JOURNAL_LINE = re.compile(r"^Journal:\s*(.+)$", re.M)
ROUND = re.compile(r"^plan-(\d+)\.md$")


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


def state_file(session_id):
    """This session's prompt anchor. The digest and the `.prompt` suffix must stay
    byte-identical to the plugin's own `state()` path."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]
    return STATE_DIR / f"{digest}.prompt"


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


def journal_plan(plan_text):
    """The `plan-NN.md` a plan's `Journal:` line names, or None without one."""
    match = JOURNAL_LINE.search(plan_text)
    return Path(match.group(1).strip()) if match else None


def read_text_arg(value, what):
    if value == "-":
        return sys.stdin.read()
    path = Path(value).expanduser()
    if not path.is_file():
        die(f"no {what} at {path}")
    return path.read_text(encoding="utf-8")


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

    root = journal_root()
    project = resolve_project(args.project, plan, anchor)
    slug = slugify(args.slug) if args.slug else (slugify(plan_title(plan_text)) or plan_slug(plan))
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M")

    project_dir = root / project
    folder = project_dir / f"{stamp}-{slug}"
    counter = 2
    while folder.exists():
        folder = project_dir / f"{stamp}-{slug}-{counter}"
        counter += 1
    folder.mkdir(parents=True)

    guard = fence(prompt)
    (folder / "prompt.md").write_text(f"{guard}text\n{prompt.strip()}\n{guard}\n", encoding="utf-8")
    plan_copy = folder / "plan-01.md"
    plan_copy.write_text(f"{plan_text.strip()}\n", encoding="utf-8")

    if anchor is not None and anchor.parent == STATE_DIR.resolve():
        for used in (anchor, anchor.with_suffix(".project")):
            try:
                used.rename(used.with_name(used.name + ".used"))
            except OSError:
                pass

    print(plan_copy)


def cmd_report(args):
    report = read_text_arg(args.report_file, "report file")
    if not report.strip():
        die("the report is empty")

    plan = Path(args.plan).expanduser()
    if not plan.is_file():
        die(f"no plan file at {plan}")
    plan = plan.resolve()

    target = journal_plan(plan.read_text(encoding="utf-8"))
    if target is None:
        die(f"{plan} has no Journal: line")

    match = ROUND.match(target.name)
    if not match:
        die(f"{target} named by {plan}'s Journal: line is not a plan-NN.md file")
    if not target.parent.is_dir():
        die(f"{target.parent} does not exist — file the plan first")

    report_path = target.with_name(f"report-{match.group(1)}.md")
    report_path.write_text(f"{report.strip()}\n", encoding="utf-8")
    print(report_path)


def cmd_register(args):
    entry = Path(args.entry).expanduser()
    if not entry.is_dir():
        die(f"no journal entry directory at {entry}")
    path = entry / SESSIONS_FILE

    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        rows = []
    if not isinstance(rows, list):
        rows = []

    for row in rows:
        if (isinstance(row, dict) and row.get("session_id") == args.session
                and row.get("round") == args.round and row.get("role") == args.role):
            return

    since = args.since or datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    rows.append({"session_id": args.session, "round": args.round, "role": args.role, "since": since})
    scratch = path.with_name(path.name + ".tmp")
    scratch.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    os.replace(scratch, path)
    print(path)


def main():
    parser = argparse.ArgumentParser(prog="journal.py", description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)

    write = modes.add_parser("write", help="file a plan cycle's prompt and plan into a journal folder")
    write.add_argument("--plan", required=True, help="absolute path to the plan file")
    write.add_argument("--prompt-file", required=True,
                       help="file holding the initial prompt verbatim, or - for stdin")
    write.add_argument("--project",
                       help="override the project name (default: the project recorded with the prompt, else the cwd's project)")
    write.add_argument("--slug",
                       help="override the folder slug (default: from the plan's title or Goal)")

    report = modes.add_parser("report", help="file a round's final report next to its plan-NN.md")
    report.add_argument("--plan", required=True, help="absolute path to the plan file, named by its Journal: line")
    report.add_argument("--report-file", required=True,
                        help="file holding the final report, or - for stdin")

    register_parser = modes.add_parser("register", help="record a session against a journal entry")
    register_parser.add_argument("--entry", required=True, help="the journal entry folder")
    register_parser.add_argument("--session", required=True, help="the session id")
    register_parser.add_argument("--round", required=True, type=int, help="the plan round")
    register_parser.add_argument("--role", required=True, help="plan or execute")
    register_parser.add_argument("--since", help="registration time (default: now, UTC)")

    args = parser.parse_args()
    if args.mode == "write":
        cmd_write(args)
    elif args.mode == "report":
        cmd_report(args)
    else:
        cmd_register(args)


if __name__ == "__main__":
    main()

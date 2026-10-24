#!/usr/bin/env python3
"""
journal.py — files a plan cycle's initial prompt and plan, round by round, into a
per-project journal folder.

Ships with the `hoko` opencode plugin. Four modes:

  write   Creates `<journalPath>/<project>/<stamp>-<slug>/`, with the initial prompt
          copied verbatim into `prompt.md` and the plan copied verbatim into
          `plan-01.md`. Prints the `plan-01.md` path.
          With `--stamp <YYYYmmdd-HHMM> --slug <slug>` instead of `--plan` it files the
          prompt only, into the folder a task already named, and prints the
          `plan-01.md` path the entry will carry once a plan is copied there.

  report  Reads the `Journal:` line of the given plan and writes `report-NN.md`
          next to the `plan-NN.md` it names, overwriting an earlier report of the
          same round. A plan run reaches it through `plan-progress.py complete`,
          which closes the run with the report and the invoice in one command.

  register  Records a session against a journal entry, once per (session, round,
          role), so the invoice can find its usage later. The row goes into the
          `sessions.json` of the entry's analytics folder (`analytics.py`), and the
          folder's `entry.json` is rewritten after it.

  record  Records a session in the project registry of the repository at `--root`:
          every session the plugin saw created, one row each, so a task's finish can
          carry them into its journal entry. Prints the registry file it wrote.

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

import analytics
import plan_format
import settings

STATE_DIR = Path(os.environ.get("HOKO_STATE_DIR") or Path(tempfile.gettempdir()) / "hoko-journal")
PROJECT_MARKERS = (".git", ".ai", ".opencode", ".claude")
SESSIONS_FILE = analytics.SESSIONS_FILE
RECORDED_SESSIONS_LIMIT = 100
ROUND = re.compile(r"^plan-(\d+)\.md$")
STAMP = re.compile(r"^\d{8}-\d{4}$")


def die(message):
    print(f"journal: {message}", file=sys.stderr)
    sys.exit(1)


def state_file(session_id):
    """This session's prompt anchor. The digest and the `.prompt` suffix must stay
    byte-identical to the plugin's own `state()` path."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]
    return STATE_DIR / f"{digest}.prompt"


def project_anchor(root):
    """The project-wide prompt anchor: survives a `/clear`, unlike the session-scoped
    one, because it is keyed on the project instead of the session. Overwritten at the
    start of each new cycle, never consumed by a write."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:16]
    return STATE_DIR / f"project-{digest}.prompt"


def journal_root():
    """The journal root from settings (`journalPath` in either hoko.json, either hoko.env,
    or `HOKO_JOURNAL_PATH`), or None when it is unset — journaling is off, and that is a
    normal, silent state, not an error."""
    path = settings.get("journalPath")
    if not path:
        return None
    return Path(os.path.expandvars(path)).expanduser()


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
    """Preference order: an explicit override (which the filer sets from the plan's own
    `Project:` line); this process's cwd, which is the project the run happens in; the
    project the plugin recorded alongside the captured prompt; the plan's own
    location."""
    if explicit:
        return slugify(explicit)

    root = project_root(Path.cwd())

    if root is None and anchor is not None:
        try:
            recorded = Path(anchor.with_suffix(".project").read_text(encoding="utf-8").strip())
        except OSError:
            recorded = None
        if recorded is not None and recorded.name and recorded != home_path():
            root = recorded

    if root is None and plan is not None:
        root = project_root(plan.parent)
    if root is None and plan is not None:
        # A loose plan file: step over a plans-directory layout if there is one.
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
    """The `plan-NN.md` a plan's header `Journal:` line names, or None without one."""
    value = plan_format.header_line(plan_text, "Journal")
    return Path(value) if value else None


def register_session(entry_dir, session_id, transcript_path="", round=1, role="plan", since=None):
    """Records a session against `entry_dir` in the `sessions.json` of its analytics
    folder (`analytics.py`). Each (session, round, role) is kept once, stamped with
    `since` (an ISO-8601 UTC string; the registration time when omitted) so the invoice
    can split a shared session; the file is replaced atomically and the folder's
    `entry.json` rewritten after it. Returns the `sessions.json` path."""
    folder = analytics.folder_for(entry_dir)
    with analytics.guard(folder):
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / SESSIONS_FILE
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            rows = []
        if not isinstance(rows, list):
            rows = []

        for row in rows:
            if (isinstance(row, dict) and row.get("session_id") == session_id
                    and row.get("round") == round and row.get("role") == role):
                return path

        rows.append({"session_id": session_id, "transcript_path": transcript_path,
                     "round": round, "role": role,
                     "since": since or datetime.now(timezone.utc).isoformat(timespec="milliseconds")})
        analytics.write_atomic(path, json.dumps(rows, indent=2) + "\n")
        analytics.link(entry_dir)
        return path
    return folder / SESSIONS_FILE


def recorded_sessions_file(root):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(str(Path(root).resolve()).encode("utf-8")).hexdigest()[:16]
    return STATE_DIR / f"sessions-{digest}.json"


def row_since(row):
    """The row's own `since` as a UTC-aware datetime, a value with no offset being read as
    UTC; None when it is missing or unparseable."""
    try:
        since = datetime.fromisoformat(str(row.get("since") or ""))
    except ValueError:
        return None
    return since if since.tzinfo else since.replace(tzinfo=timezone.utc)


def written_since(row, after):
    """Whether the session was in use at or after `after`. opencode exposes no
    transcript, so a transcript that is absent or unreadable falls back to the row's own
    `since`; a row with neither was not in use."""
    transcript = str(row.get("transcript_path") or "")
    if transcript:
        try:
            modified = Path(transcript).stat().st_mtime
        except OSError:
            pass
        else:
            return datetime.fromtimestamp(modified, timezone.utc) >= after
    since = row_since(row)
    return since is not None and since >= after


def recorded_sessions(root, after=None):
    """The sessions a run in the project at `root` recorded, as `sessions.json` rows;
    empty when none was recorded. With `after` (a UTC-aware datetime) only the sessions
    whose transcript was written to since then, which are the ones a run that began then
    can have used."""
    try:
        rows = json.loads(recorded_sessions_file(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(rows, list):
        return []
    rows = [row for row in rows if isinstance(row, dict) and row.get("session_id")]
    if after is not None:
        rows = [row for row in rows if written_since(row, after)]
    return rows


def record_session(root, session_id, transcript_path=""):
    """Keeps one row per session in the project's state file, newest last, at most
    `RECORDED_SESSIONS_LIMIT` of them; the file is replaced atomically."""
    rows = recorded_sessions(root)
    if any(row["session_id"] == session_id for row in rows):
        return
    rows.append({"session_id": session_id, "transcript_path": transcript_path,
                 "round": 1, "role": "execute",
                 "since": datetime.now(timezone.utc).isoformat(timespec="milliseconds")})
    path = recorded_sessions_file(root)
    scratch = path.with_name(path.name + ".tmp")
    scratch.write_text(json.dumps(rows[-RECORDED_SESSIONS_LIMIT:], indent=2) + "\n", encoding="utf-8")
    os.replace(scratch, path)


def read_text_arg(value, what):
    if value == "-":
        return sys.stdin.read()
    path = Path(value).expanduser()
    if not path.is_file():
        die(f"no {what} at {path}")
    return path.read_text(encoding="utf-8")


def cmd_write(args):
    if args.stamp and args.plan:
        die("--stamp files the prompt only; drop --plan")
    if not args.stamp and not args.plan:
        die("write needs --plan, or --stamp with --slug for a prompt-only entry")
    if args.stamp and not STAMP.match(args.stamp):
        die(f"--stamp must look like 20261021-1530, not {args.stamp!r}")
    if args.stamp and not (args.slug and slugify(args.slug)):
        die("--stamp needs a --slug naming the folder")

    plan = None
    plan_text = ""
    if args.plan:
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
    if root is None:
        die("HOKO_JOURNAL_PATH is not set — journaling is off. "
            "Set it in hoko.json to keep a journal.")

    project = resolve_project(args.project or plan_format.project_name(plan_text), plan, anchor)
    slug = slugify(args.slug) if args.slug else (slugify(plan_title(plan_text)) or plan_slug(plan))
    stamp = args.stamp or datetime.now().astimezone().strftime("%Y%m%d-%H%M")

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
    if plan is not None:
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
    path = register_session(entry, args.session, args.transcript or "",
                            args.round, args.role, args.since)
    print(path)


def cmd_record(args):
    record_session(args.root, args.session, args.transcript or "")
    print(recorded_sessions_file(args.root))


def main():
    parser = argparse.ArgumentParser(prog="journal.py", description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)

    write = modes.add_parser("write", help="file a plan cycle's prompt and plan into a journal folder")
    write.add_argument("--plan", help="absolute path to the plan file (omit with --stamp)")
    write.add_argument("--stamp",
                       help="file the prompt only, into the folder <stamp>-<slug>: the task's own YYYYmmdd-HHMM")
    write.add_argument("--prompt-file", required=True,
                       help="file holding the initial prompt verbatim, or - for stdin")
    write.add_argument("--project",
                       help="override the project name (default: the cwd's project, else the one recorded with the prompt)")
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
    register_parser.add_argument("--transcript", help="the session's transcript path, when one exists")

    record_parser = modes.add_parser("record", help="record a session in a project's own registry")
    record_parser.add_argument("--root", required=True, help="the project's repository root")
    record_parser.add_argument("--session", required=True, help="the session id")
    record_parser.add_argument("--transcript", help="the session's transcript path, when one exists")

    args = parser.parse_args()
    if args.mode == "write":
        cmd_write(args)
    elif args.mode == "report":
        cmd_report(args)
    elif args.mode == "record":
        cmd_record(args)
    else:
        cmd_register(args)


if __name__ == "__main__":
    main()

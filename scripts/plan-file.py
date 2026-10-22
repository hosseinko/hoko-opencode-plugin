#!/usr/bin/env python3
"""
plan-file.py — files an approved plan: stamps it, copies it into the repository, and
journals it, all without any model turn in between.

Ships with the `hoko` opencode plugin. One mode:

  file   `plan-file.py file --plan <path> [--session <id>] [--project <name>]
         [--since <iso>]` — resolves the project (the `--project` override, the plan's
         own `Project:` line, else `journal.resolve_project`), records a `Project:`
         line under the plan's title, hands the plan and the best available prompt
         anchor to `journal.py write`, records a `Journal:` line naming the
         `plan-01.md` it created, and registers `--session` against that entry as round
         1 role `plan`, stamped with `--since` when given. A plan whose `Journal:`
         line already names an existing file is not re-filed.
         Prints the `plan-01.md` path, or the plan's own path when journaling is off.

Filing also copies the plan into the repository's plans directory — under a new
`<stamp>-<slug>.md` name when the plan came from outside it, keeping the planner's own
timestamped name when it is already there, because renaming that one would invalidate
the session state the plugin recorded before calling this script. The plans
directory's top segment is gitignored when the repository does not already track it,
and the copy gets its `## Progress` checklist through `plan-progress.py init`.

Journaling is opt-in: with no journalPath configured, only the `Project:` line is
written and the plan's own path is printed.
"""

import argparse
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import journal
import plan_format
import settings

SCRIPTS_DIR = Path(__file__).resolve().parent
JOURNAL_PY = SCRIPTS_DIR / "journal.py"
PLAN_PROGRESS_PY = SCRIPTS_DIR / "plan-progress.py"


class PlanFileError(Exception):
    pass


def die(message):
    print(f"plan-file: {message}", file=sys.stderr)
    sys.exit(1)


def own_project(text):
    """The plan's own `Project:` line, already present before filing. None when it has
    none yet."""
    return plan_format.project_name(text)


def resolve_repo(session_anchor, plan_path=None):
    """The project's filesystem root, walked in the same order
    `journal.resolve_project` uses: this process's own cwd first, else the project the
    plugin recorded from cwd when it captured the prompt, else — for a loose plan file
    with neither — a project rooted near the plan file itself. None when nothing in
    that chain resolves to one."""
    root = journal.project_root(Path.cwd())
    if root is None and session_anchor is not None:
        try:
            recorded = Path(session_anchor.with_suffix(".project").read_text(encoding="utf-8").strip())
        except OSError:
            recorded = None
        if recorded is not None and recorded.name and recorded != journal.home_path():
            root = recorded
    if root is None and plan_path is not None:
        root = journal.project_root(plan_path.parent)
    if root is None and plan_path is not None:
        root = plan_path.parent
        while root.name in journal.plan_dir_segments() and root != root.parent:
            root = root.parent
    if root is None or root == journal.home_path() or root.name in ("", ".", "/"):
        return None
    return root


def temp_prompt(content):
    handle = tempfile.NamedTemporaryFile(mode="w", suffix=".prompt", delete=False, encoding="utf-8")
    handle.write(content)
    handle.close()
    path = Path(handle.name)
    return path, lambda: path.unlink(missing_ok=True)


def prompt_source(session_anchor, repo_root):
    """The best available prompt anchor: the session's, else the project's, else a
    placeholder — a `(file, cleanup)` pair. The session anchor is handed to
    `journal.py write` as-is, so its own rotation retires it; the project anchor is
    copied to a scratch file instead, since it survives cycles and must not be retired
    by a write."""
    if session_anchor is not None and session_anchor.is_file():
        return session_anchor, None
    if repo_root is not None:
        candidate = journal.project_anchor(repo_root)
        if candidate.is_file():
            return temp_prompt(candidate.read_text(encoding="utf-8"))
    return temp_prompt("_Prompt not captured._")


def ensure_gitignore(repo_root, plans_dir_rel):
    top = plans_dir_rel.split("/", 1)[0]
    tracked = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "--error-unmatch", top],
        capture_output=True, text=True,
    )
    if tracked.returncode == 0:
        return  # the repo already tracks it
    gitignore = repo_root / ".gitignore"
    line = f"/{top}/"
    try:
        existing = gitignore.read_text(encoding="utf-8").splitlines()
    except OSError:
        existing = []
    if line not in existing:
        with gitignore.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def repository_copy(repo_root, plan_path, text, project):
    """The plan's copy in the repository's plans directory. A plan filed from outside
    that directory gets the planner's `<stamp>-<slug>.md` name; one already inside it
    keeps its name, because the plugin has already recorded that path for the run."""
    plans_dir_rel = settings.get("plansDir")
    plans_dir = (repo_root / plans_dir_rel).resolve()
    plans_dir.mkdir(parents=True, exist_ok=True)

    name = plan_path.name
    if plan_path.parent.resolve() != plans_dir:
        slug = journal.slugify(journal.plan_title(text)) or journal.plan_slug(plan_path)
        stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M")
        name = f"{stamp}-{slug}.md"
    repo_copy = plans_dir / name
    if not repo_copy.exists():
        repo_copy.write_text(text, encoding="utf-8")
    ensure_gitignore(repo_root, plans_dir_rel)
    return repo_copy


def journaled_copy(repo_root, existing):
    """The repository copy a previous filing made for the `plan-NN.md` at `existing`,
    recognised by its own `Journal:` line, so filing the same plan again adds no second
    copy. None when the repository has none."""
    plans_dir = (repo_root / settings.get("plansDir")).resolve()
    if not plans_dir.is_dir():
        return None
    for candidate in sorted(plans_dir.glob("*.md")):
        try:
            text = candidate.read_text(encoding="utf-8")
        except OSError:
            continue
        value = plan_format.header_line(text, "Journal")
        if value is not None and Path(value) == existing:
            return candidate
    return None


def init_progress(repo_path):
    """Writes the `## Progress` checklist into the filed repository copy, so a plan
    never reaches execute-plan without one. Best-effort: a plan without `## Steps` just
    keeps whatever it already had — this is not the place to raise about it."""
    try:
        subprocess.run(
            [sys.executable, str(PLAN_PROGRESS_PY), "init", "--plan", str(repo_path)],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        pass


def run_journal(*args):
    result = subprocess.run(
        [sys.executable, str(JOURNAL_PY), *args],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise PlanFileError(result.stderr.strip() or f"journal.py {args[0]} failed")
    return result.stdout.strip()


def register(session_id, entry, since=None):
    if not session_id or not settings.get("journalPath"):
        return
    args = ["register", "--entry", str(entry), "--session", session_id,
            "--round", "1", "--role", "plan"]
    if since:
        args += ["--since", since]
    try:
        run_journal(*args)
    except PlanFileError:
        # The registry is bookkeeping; a note on stderr is the whole cost of losing it.
        print(f"plan-file: the planning session was not registered against {entry}", file=sys.stderr)


def file_plan(plan_path, session_id=None, project_override=None, since=None):
    """Files `plan_path`, or — when it already names a filed journal round — just
    returns that copy. Returns `(plan_copy, folder_or_None, repo_root_or_None)`, where
    `folder` is None exactly when journaling is off."""
    plan_path = plan_path.resolve()
    text = plan_path.read_text(encoding="utf-8")
    session_anchor = journal.state_file(session_id) if session_id else None
    repo_root = resolve_repo(session_anchor, plan_path)

    existing = journal.journal_plan(text)
    if existing is not None and existing.is_file():
        register(session_id, existing.parent, since)
        if repo_root is not None:
            repo_copy = journaled_copy(repo_root, existing)
            if repo_copy is None:
                repo_copy = repository_copy(repo_root, plan_path, text,
                                            own_project(text) or plan_path.parent.name)
            init_progress(repo_copy)
        return existing, existing.parent, repo_root

    project = journal.resolve_project(project_override or own_project(text), plan_path, session_anchor)
    plan_path.write_text(plan_format.ensure_header_line(text, "Project", project), encoding="utf-8")

    folder = None
    if settings.get("journalPath"):
        prompt_file, cleanup = prompt_source(session_anchor, repo_root)
        try:
            plan_copy = Path(run_journal(
                "write", "--plan", str(plan_path), "--prompt-file", str(prompt_file),
                "--project", project,
            ))
        finally:
            if cleanup:
                cleanup()
        plan_path.write_text(
            plan_format.ensure_header_line(plan_path.read_text(encoding="utf-8"), "Journal",
                                           str(plan_copy), after=("Project",)),
            encoding="utf-8")
        folder = plan_copy.parent
        register(session_id, folder, since)
    else:
        plan_copy = plan_path

    if repo_root is not None:
        repo_copy = repository_copy(repo_root, plan_path, plan_path.read_text(encoding="utf-8"), project)
        init_progress(repo_copy)
    return plan_copy, folder, repo_root


def cmd_file(args):
    plan_path = Path(args.plan).expanduser()
    if not plan_path.is_file():
        die(f"no plan file at {plan_path}")
    try:
        plan_copy, _folder, _repo_root = file_plan(
            plan_path.resolve(), args.session or None, args.project or None, args.since or None)
    except PlanFileError as exc:
        die(str(exc))
    print(plan_copy)


def main():
    parser = argparse.ArgumentParser(prog="plan-file.py", description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)

    file_cmd = modes.add_parser("file", help="file an approved plan, or print its existing journal entry")
    file_cmd.add_argument("--plan", required=True, help="absolute path to the plan file")
    file_cmd.add_argument("--session", help="the approving session, registered as round 1 role plan")
    file_cmd.add_argument("--project", help="override the project name")
    file_cmd.add_argument("--since",
                          help="the cycle's prompt-capture time recorded on the plan row (default: now, UTC)")

    args = parser.parse_args()
    if args.mode == "file":
        cmd_file(args)


if __name__ == "__main__":
    main()

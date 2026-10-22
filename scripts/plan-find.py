#!/usr/bin/env python3
"""
plan-find.py — locate the plan a bare `/hoko/execute-plan` should resume.

Ships with the `hoko` plugin.

Ports the algorithm written as prose in `commands/hoko/execute-plan.md` under *Find
the plan*, so the conductor no longer re-derives it, and the two lists it reads
are never merged by timestamp:

    plan-find.py [--root <repo>]

This repository's own plans directory (`settings.py plansDir`, and `.ai/plans` and
`.opencode/plans` as well, since a project may still keep plans in one while configuring
another) is searched first. The newest file in it that is not marked `Status: complete`
wins outright — printed as its absolute path, exit 0.

Only when that list holds nothing does `~/.opencode/plan` come into play. That directory
is shared by every project on the machine, so a plan is never picked from it
automatically: each candidate is scored 1 when its `Project:` line matches this
repository's project slug, 0 otherwise, printed with its score, and the script exits
non-zero so the model asks which one is meant — a candidate scoring zero is never the
one it means.
"""

import argparse
import subprocess
import sys
from pathlib import Path

import journal
import plan_format
import settings


def repo_root(explicit):
    if explicit:
        return Path(explicit).expanduser().resolve()
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        return Path(result.stdout.strip())
    return Path.cwd()


def candidate_plans(*directories):
    """Every `*.md` under the given directories, newest first, each path once."""
    seen = set()
    found = []
    for directory in directories:
        if not directory.is_dir():
            continue
        for path in directory.glob("*.md"):
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                found.append(resolved)
    found.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return found


def score(path, project_slug):
    """1 when the candidate's `Project:` line matches this repository's project
    slug, 0 otherwise — including when the candidate has no `Project:` line at all."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return 0
    return 1 if plan_format.project_name(text) == project_slug else 0


def main():
    parser = argparse.ArgumentParser(prog="plan-find.py", description=__doc__)
    parser.add_argument("--root", help="the repository root (default: `git rev-parse --show-toplevel`)")
    args = parser.parse_args()

    root = repo_root(args.root)
    plans_dir = settings.get("plansDir")

    # `~/.opencode/plan` is shared by every project on the machine — never a
    # repository's own plans directory, even when `root` happens to be home itself.
    shared_home_plans = (Path.home() / ".opencode" / "plan").resolve()
    repo_dirs = [d for d in (root / plans_dir, root / ".ai" / "plans", root / ".opencode" / "plans")
                 if d.resolve() != shared_home_plans]
    repo_candidates = candidate_plans(*repo_dirs)
    for path in repo_candidates:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if not plan_format.is_complete(text):
            print(path)
            return 0

    shared_candidates = candidate_plans(Path.home() / ".opencode" / "plan")
    if not shared_candidates:
        print("plan-find: no unfinished plan in this repository, and ~/.opencode/plan has nothing either",
              file=sys.stderr)
        return 1

    project_slug = journal.slugify(root.name)
    scored = [(score(path, project_slug), path) for path in shared_candidates]
    for hits, path in scored:
        print(f"{hits} {path}")
    return 1


if __name__ == "__main__":
    sys.exit(main())

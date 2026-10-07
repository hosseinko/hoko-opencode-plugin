#!/usr/bin/env python3
"""Tests for journal.py. Run: python3 scripts/test_journal.py

Every run points HOKO_JOURNAL_PATH at a throwaway journal root and redirects HOME,
so the real journal is never touched.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "journal.py"
PROMPT = "add a --dry-run flag\n\nit must not write anything, and `--dry-run` wins over --force"
PLAN = "## Goal\nShip a dry-run flag.\n\n## Steps\n### 1. Parse the flag\n- Files: cli.py\n"
REPORT = "All 2 steps done.\n\n- 1. Parse the flag — `a1b2c3d` cli: add --dry-run\n- 2. Wire it — `e4f5g6h`\n\nTests: `pytest -q` green."

failures = []


def check(name, condition, detail=""):
    print(("ok   " if condition else "FAIL ") + name + (f" — {detail}" if not condition and detail else ""))
    if not condition:
        failures.append(name)


def make_repo(tmp):
    repo = tmp / "my-project"
    (repo / ".ai" / "plans").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    plan = repo / ".ai" / "plans" / "20260902084632-ship-dry-run.md"
    plan.write_text(PLAN)
    prompt_file = tmp / "first.prompt"
    prompt_file.write_text(PROMPT)
    return plan, prompt_file


def run(*args, stdin=None, home=None, cwd=None, journal=None, state=None):
    env = dict(os.environ)
    # HOME is redirected so no test can read the real ~/.config/opencode/hoko.json.
    env["HOME"] = str(home)
    Path(env["HOME"]).mkdir(parents=True, exist_ok=True)
    if journal is not None:
        env["HOKO_JOURNAL_PATH"] = str(journal)
    else:
        env.pop("HOKO_JOURNAL_PATH", None)
    if state is not None:
        env["HOKO_STATE_DIR"] = str(state)
    # Default cwd is the fake home: not a project, so cwd detection stays out of the
    # way unless a test opts into it.
    return subprocess.run([sys.executable, str(SCRIPT), *args], input=stdin,
                          capture_output=True, text=True, env=env,
                          cwd=str(cwd) if cwd else env["HOME"])


def main():
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        home = tmp / "home"
        # A space in the root is deliberate — the default is unset, so every real root
        # is one somebody typed, and notes directories have spaces in them.
        journal = tmp / "my notes" / "journal"
        plan, prompt_file = make_repo(tmp)
        repo = plan.parents[2]

        def write(*args, **kwargs):
            kwargs.setdefault("home", home)
            kwargs.setdefault("journal", journal)
            return run("write", *args, **kwargs)

        def report(*args, **kwargs):
            kwargs.setdefault("home", home)
            kwargs.setdefault("journal", journal)
            return run("report", *args, **kwargs)

        def register(*args, **kwargs):
            kwargs.setdefault("home", home)
            kwargs.setdefault("journal", journal)
            return run("register", *args, **kwargs)

        result = write("--plan", str(plan), "--prompt-file", str(prompt_file))
        check("write succeeds", result.returncode == 0, result.stderr.strip())
        entry = Path(result.stdout.strip())
        folder = entry.parent
        check("write prints plan-01.md", entry.name == "plan-01.md", entry.name)
        check("the round folder lands under <journal>/<repo name>",
              folder.parent == journal / "my-project", str(entry))
        check("folder name comes from the plan's Goal",
              folder.name.endswith("-ship-a-dry-run-flag"), folder.name)
        check("prompt.md is written", (folder / "prompt.md").is_file(), str(folder))
        check("prompt is verbatim", PROMPT in (folder / "prompt.md").read_text())
        check("plan is verbatim", entry.read_text() == PLAN.strip() + "\n", entry.read_text())

        second = write("--plan", str(plan), "--prompt-file", str(prompt_file))
        check("a collision on the same minute gets a distinct folder",
              second.returncode == 0 and Path(second.stdout.strip()).parent != folder,
              second.stdout.strip())

        backticked = tmp / "backticks.prompt"
        backticked.write_text("look at ```this``` block")
        third = write("--plan", str(plan), "--prompt-file", str(backticked))
        check("fence widens past inner backticks",
              "````text" in (Path(third.stdout.strip()).parent / "prompt.md").read_text())

        empty = tmp / "empty.prompt"
        empty.write_text("   \n")
        check("empty prompt is refused",
              write("--plan", str(plan), "--prompt-file", str(empty)).returncode != 0)
        check("missing plan is refused",
              write("--plan", str(tmp / "nope.md"), "--prompt-file", str(prompt_file)).returncode != 0)

        override = write("--plan", str(plan), "--prompt-file", "-",
                         "--project", "Other Project", stdin="from stdin")
        check("--project override and stdin prompt",
              override.returncode == 0
              and Path(override.stdout.strip()).parent.parent == journal / "other-project",
              override.stderr.strip())

        # slugs: plan files carry an auto-generated slug, so it must not leak
        junk = tmp / "auto-slug"
        junk.mkdir()
        auto = junk / "in-src-client-fbwebservice-fbwebservicec-parsed-hejlsberg.md"
        auto.write_text("## Goal\nMake the FB webservice client parse Hejlsberg records.\n")
        auto_plan = Path(write("--plan", str(auto), "--prompt-file", str(prompt_file),
                               cwd=repo).stdout.strip())
        check("an auto-slug filename does not leak into the folder name",
              "hejlsberg" in auto_plan.parent.name and "fbwebservicec" not in auto_plan.parent.name,
              auto_plan.parent.name)

        h1 = junk / "some-generated-slug.md"
        h1.write_text("# Retire the legacy importer\n\n## Goal\nSomething else entirely.\n")
        h1_plan = Path(write("--plan", str(h1), "--prompt-file", str(prompt_file),
                             cwd=repo).stdout.strip())
        check("an H1 wins over the Goal",
              h1_plan.parent.name.endswith("-retire-the-legacy-importer"), h1_plan.parent.name)

        bare = junk / "20260902-fallback-slug.md"
        bare.write_text("- just a bullet\n")
        bare_plan = Path(write("--plan", str(bare), "--prompt-file", str(prompt_file),
                               cwd=repo).stdout.strip())
        check("a plan with no title falls back to its filename",
              bare_plan.parent.name.endswith("-fallback-slug"), bare_plan.parent.name)

        wordy = junk / "wordy.md"
        wordy.write_text("## Goal\n" + "Rework the whole ingestion pipeline so that every supplier "
                         "feed is normalised before matching, including the legacy ones.\n")
        wordy_plan = Path(write("--plan", str(wordy), "--prompt-file", str(prompt_file),
                                cwd=repo).stdout.strip())
        # folder name is `<YYYYMMDD>-<HHMM>-<slug>`: drop the two stamp segments.
        wordy_slug = wordy_plan.parent.name.split("-", 2)[2]
        check("a long Goal is cut at a word boundary",
              len(wordy_slug) <= 60 and not wordy_slug.endswith("-")
              and wordy_slug.split("-")[-1] in "rework the whole ingestion pipeline so that every supplier feed is normalised".split(),
              wordy_slug)

        slug_override = Path(write("--plan", str(auto), "--prompt-file", str(prompt_file),
                                   "--slug", "Parse Hejlsberg", cwd=repo).stdout.strip())
        check("--slug overrides the derived slug",
              slug_override.parent.name.endswith("-parse-hejlsberg"), slug_override.parent.name)

        # report: located from the plan's Journal: line
        report_file = tmp / "final.md"
        report_file.write_text(REPORT)
        journaled = tmp / "journaled.md"
        journaled.write_text(f"Journal: {entry}\n\n{PLAN}")
        filed = report("--plan", str(journaled), "--report-file", str(report_file))
        check("report writes report-01.md beside the plan-01.md it names",
              filed.returncode == 0
              and Path(filed.stdout.strip()) == folder / "report-01.md",
              filed.stdout.strip() + filed.stderr.strip())
        check("the report is verbatim",
              (folder / "report-01.md").read_text() == REPORT.strip() + "\n",
              (folder / "report-01.md").read_text())

        round2 = folder / "plan-02.md"
        round2.write_text(PLAN)
        journaled2 = tmp / "journaled-round2.md"
        journaled2.write_text(f"Journal: {round2}\n\n{PLAN}")
        filed2 = report("--plan", str(journaled2), "--report-file", str(report_file))
        check("a round-02 plan writes report-02.md",
              filed2.returncode == 0 and Path(filed2.stdout.strip()) == folder / "report-02.md",
              filed2.stdout.strip() + filed2.stderr.strip())

        again = report("--plan", str(journaled), "--report-file", "-",
                       stdin="a second pass over the same plan")
        check("a second report of the same round overwrites the first",
              again.returncode == 0
              and (folder / "report-01.md").read_text().strip() == "a second pass over the same plan",
              (folder / "report-01.md").read_text())

        bare_plan = tmp / "bare-plan.md"
        bare_plan.write_text(PLAN)
        no_line = report("--plan", str(bare_plan), "--report-file", str(report_file))
        check("a plan without a Journal: line is refused",
              no_line.returncode != 0 and str(bare_plan) in no_line.stderr, no_line.stderr.strip())
        empty_report = tmp / "empty.md"
        empty_report.write_text("\n  \n")
        check("an empty report is refused",
              report("--plan", str(journaled), "--report-file", str(empty_report)).returncode != 0)
        check("a missing plan is refused",
              report("--plan", str(tmp / "nope.md"), "--report-file", str(report_file)).returncode != 0)

        # register: one row per (session, round, role), written atomically
        sessions = folder / "sessions.json"
        first = register("--entry", str(folder), "--session", "sess-1",
                         "--round", "1", "--role", "plan")
        rows = json.loads(sessions.read_text())
        check("register appends the session row",
              first.returncode == 0
              and {k: v for k, v in rows[0].items() if k != "since"}
              == {"session_id": "sess-1", "round": 1, "role": "plan"},
              rows)
        check("a new row is stamped with the registration time",
              bool(re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}\+00:00$", rows[0]["since"])),
              rows[0].get("since"))
        check("the registration time is now",
              abs((datetime.now(timezone.utc)
                   - datetime.fromisoformat(rows[0]["since"])).total_seconds()) < 60,
              rows[0].get("since"))

        register("--entry", str(folder), "--session", "sess-1", "--round", "1", "--role", "plan")
        check("a repeated registration adds no duplicate row",
              len(json.loads(sessions.read_text())) == 1, sessions.read_text())
        register("--entry", str(folder), "--session", "sess-1", "--round", "1", "--role", "execute")
        register("--entry", str(folder), "--session", "sess-2", "--round", "1", "--role", "plan")
        check("a different role or session gets its own row",
              len(json.loads(sessions.read_text())) == 3, sessions.read_text())

        explicit = register("--entry", str(folder), "--session", "sess-3",
                            "--round", "2", "--role", "plan",
                            "--since", "2026-10-06T10:00:00.000+00:00")
        row3 = [r for r in json.loads(sessions.read_text()) if r["session_id"] == "sess-3"][0]
        check("--since is recorded verbatim",
              explicit.returncode == 0 and row3["since"] == "2026-10-06T10:00:00.000+00:00",
              row3)
        check("the write is atomic: no scratch file is left behind",
              not (folder / "sessions.json.tmp").exists(), str(sorted(p.name for p in folder.iterdir())))
        check("register refuses an entry that does not exist",
              register("--entry", str(tmp / "nope"), "--session", "s",
                       "--round", "1", "--role", "plan").returncode != 0)

        check("journal path with a space works", " " in str(journal) and entry.is_file())

        # project resolution
        nogit = tmp / "no-git-project"
        (nogit / ".ai" / "plans").mkdir(parents=True)
        nogit_plan = nogit / ".ai" / "plans" / "20260902090000-add-cache.md"
        nogit_plan.write_text(PLAN)
        nogit_result = write("--plan", str(nogit_plan), "--prompt-file", str(prompt_file))
        check("non-git project resolves by its .ai dir",
              nogit_result.returncode == 0
              and Path(nogit_result.stdout.strip()).parent.parent == journal / "no-git-project",
              nogit_result.stdout.strip() + nogit_result.stderr.strip())

        loose = tmp / "loose" / ".ai" / "plans"
        loose.mkdir(parents=True)
        loose_plan = loose / "20260902090000-loose.md"
        loose_plan.write_text(PLAN)
        loose_result = write("--plan", str(loose_plan), "--prompt-file", str(prompt_file), cwd=tmp)
        check("a loose plan never files under plans/ or .ai/",
              loose_result.returncode == 0
              and Path(loose_result.stdout.strip()).parent.parent.name == "loose",
              loose_result.stdout.strip() + loose_result.stderr.strip())

        # plans written under the older conventions still resolve to their project
        for marker in (".opencode", ".claude"):
            legacy = tmp / f"legacy{marker}"
            (legacy / marker / "plans").mkdir(parents=True)
            legacy_plan = legacy / marker / "plans" / "20260902090000-legacy.md"
            legacy_plan.write_text(PLAN)
            result = write("--plan", str(legacy_plan), "--prompt-file", str(prompt_file))
            check(f"a plan under {marker}/plans still resolves its project",
                  result.returncode == 0
                  and Path(result.stdout.strip()).parent.parent == journal / f"legacy-{marker.lstrip('.')}",
                  result.stdout.strip() + result.stderr.strip())

        # a plan outside the project it belongs to
        (home / ".ai" / "plans").mkdir(parents=True, exist_ok=True)
        global_plan = home / ".ai" / "plans" / "elegant-hopping-book.md"
        global_plan.write_text(PLAN)
        no_hint = write("--plan", str(global_plan), "--prompt-file", str(prompt_file))
        check("a plan under the home directory lands in unsorted/",
              no_hint.returncode == 0
              and Path(no_hint.stdout.strip()).parent.parent.name == "unsorted",
              no_hint.stdout.strip() + no_hint.stderr.strip())
        from_cwd = write("--plan", str(global_plan), "--prompt-file", str(prompt_file), cwd=repo)
        check("cwd names the project when the plan is outside it",
              from_cwd.returncode == 0
              and Path(from_cwd.stdout.strip()).parent.parent == journal / "my-project",
              from_cwd.stdout.strip() + from_cwd.stderr.strip())

        # the captured prompt carries the project the plugin recorded
        state = tmp / "state"
        state.mkdir()
        anchor = state / "abc123.prompt"
        anchor.write_text(PROMPT)
        anchor.with_suffix(".project").write_text(str(repo))
        recorded = write("--plan", str(global_plan), "--prompt-file", str(anchor), state=state)
        check("the recorded project wins over cwd and the plan path",
              recorded.returncode == 0
              and Path(recorded.stdout.strip()).parent.parent == journal / "my-project",
              recorded.stdout.strip() + recorded.stderr.strip())
        check("filing rotates the anchor and its project sidecar",
              not anchor.exists() and not anchor.with_suffix(".project").exists()
              and (state / "abc123.prompt.used").exists()
              and (state / "abc123.project.used").exists(),
              str(sorted(p.name for p in state.iterdir())))

        # configuration
        config_home = tmp / "config-home"
        (config_home / ".config" / "opencode").mkdir(parents=True)
        config_journal = tmp / "ConfigJournal"
        (config_home / ".config" / "opencode" / "hoko.json").write_text(
            json.dumps({"journalPath": str(config_journal)}))
        from_config = run("write", "--plan", str(plan), "--prompt-file", str(prompt_file),
                          home=config_home)
        check("hoko.json supplies the journal path",
              from_config.returncode == 0
              and Path(from_config.stdout.strip()).parent.parent == config_journal / "my-project",
              from_config.stdout.strip() + from_config.stderr.strip())
        env_wins = run("write", "--plan", str(plan), "--prompt-file", str(prompt_file),
                       home=config_home, journal=journal)
        check("HOKO_JOURNAL_PATH beats hoko.json",
              env_wins.returncode == 0
              and Path(env_wins.stdout.strip()).parent.parent == journal / "my-project",
              env_wins.stdout.strip() + env_wins.stderr.strip())
        broken = tmp / "broken-home"
        (broken / ".config" / "opencode").mkdir(parents=True)
        (broken / ".config" / "opencode" / "hoko.json").write_text("{nope")
        check("invalid hoko.json is refused loudly",
              run("write", "--plan", str(plan), "--prompt-file", str(prompt_file),
                  home=broken).returncode != 0)

        # journaling is opt-in: no root anywhere means a clear refusal, not a guess
        bare_home = tmp / "bare-home"
        (bare_home / ".config" / "opencode").mkdir(parents=True)
        unconfigured = run("write", "--plan", str(plan), "--prompt-file", str(prompt_file),
                           home=bare_home)
        check("an unconfigured journal root is refused, not defaulted",
              unconfigured.returncode != 0
              and "HOKO_JOURNAL_PATH is not set" in unconfigured.stderr,
              unconfigured.stdout.strip() + unconfigured.stderr.strip())
        check("nothing is written outside the configured root",
              not any(bare_home.rglob("*.md")),
              str(sorted(str(f) for f in bare_home.rglob("*.md"))))

    print()
    if failures:
        print(f"{len(failures)} failed: {', '.join(failures)}")
        sys.exit(1)
    print("all passed")


if __name__ == "__main__":
    main()

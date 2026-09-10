#!/usr/bin/env python3
"""Tests for journal.py. Run: python3 scripts/test_journal.py

Every run points HOKO_JOURNAL_PATH at a throwaway journal root and redirects HOME,
so the real journal is never touched.
"""

import json
import os
import subprocess
import sys
import tempfile
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

        result = write("--plan", str(plan), "--prompt-file", str(prompt_file))
        check("write succeeds", result.returncode == 0, result.stderr.strip())
        entry = Path(result.stdout.strip())
        check("entry lands under <journal>/<repo name>", entry.parent == journal / "my-project", str(entry))
        check("filename comes from the plan's Goal",
              entry.name.endswith("-ship-a-dry-run-flag.md"), entry.name)
        check("title comes from the plan's Goal",
              entry.read_text().splitlines()[6] == "# Ship a dry-run flag",
              entry.read_text().splitlines()[6])

        body = entry.read_text()
        check("prompt is verbatim", PROMPT in body)
        check("plan is verbatim", PLAN.strip() in body)
        check("frontmatter names the project", "project: my-project" in body)
        check("frontmatter names the plan path", f"plan: {plan.resolve()}" in body)

        second = write("--plan", str(plan), "--prompt-file", str(prompt_file))
        check("second write does not overwrite",
              second.returncode == 0 and Path(second.stdout.strip()) != entry)

        backticked = tmp / "backticks.prompt"
        backticked.write_text("look at ```this``` block")
        third = write("--plan", str(plan), "--prompt-file", str(backticked))
        check("fence widens past inner backticks", "````text" in Path(third.stdout.strip()).read_text())

        empty = tmp / "empty.prompt"
        empty.write_text("   \n")
        check("empty prompt is refused",
              write("--plan", str(plan), "--prompt-file", str(empty)).returncode != 0)
        check("missing plan is refused",
              write("--plan", str(tmp / "nope.md"), "--prompt-file", str(prompt_file)).returncode != 0)

        override = write("--plan", str(plan), "--prompt-file", "-",
                         "--project", "Other Project", stdin="from stdin")
        check("--project override and stdin prompt",
              override.returncode == 0 and Path(override.stdout.strip()).parent == journal / "other-project",
              override.stderr.strip())

        # titles: plan files carry an auto-generated slug, so it must not leak
        junk = tmp / "auto-slug"
        junk.mkdir()
        auto = junk / "in-src-client-fbwebservice-fbwebservicec-parsed-hejlsberg.md"
        auto.write_text("## Goal\nMake the FB webservice client parse Hejlsberg records.\n")
        auto_entry = Path(write("--plan", str(auto), "--prompt-file", str(prompt_file),
                                cwd=repo).stdout.strip())
        check("an auto-slug filename does not leak into the entry name",
              "hejlsberg" in auto_entry.name and "fbwebservicec" not in auto_entry.name,
              auto_entry.name)
        check("an auto-slug filename does not leak into the title",
              "# Make the FB webservice client parse Hejlsberg records" in auto_entry.read_text(),
              auto_entry.read_text().splitlines()[6])

        h1 = junk / "some-generated-slug.md"
        h1.write_text("# Retire the legacy importer\n\n## Goal\nSomething else entirely.\n")
        h1_entry = Path(write("--plan", str(h1), "--prompt-file", str(prompt_file),
                              cwd=repo).stdout.strip())
        check("an H1 wins over the Goal",
              h1_entry.name.endswith("-retire-the-legacy-importer.md"), h1_entry.name)

        bare = junk / "20260902-fallback-slug.md"
        bare.write_text("- just a bullet\n")
        bare_entry = Path(write("--plan", str(bare), "--prompt-file", str(prompt_file),
                                cwd=repo).stdout.strip())
        check("a plan with no title falls back to its filename",
              bare_entry.name.endswith("-fallback-slug.md")
              and "# Fallback slug" in bare_entry.read_text(), bare_entry.name)

        wordy = junk / "wordy.md"
        wordy.write_text("## Goal\n" + "Rework the whole ingestion pipeline so that every supplier "
                         "feed is normalised before matching, including the legacy ones.\n")
        wordy_entry = Path(write("--plan", str(wordy), "--prompt-file", str(prompt_file),
                                 cwd=repo).stdout.strip())
        wordy_slug = wordy_entry.stem.split("-", 1)[1]
        check("a long Goal is cut at a word boundary",
              len(wordy_slug) <= 60 and not wordy_slug.endswith("-")
              and wordy_slug.split("-")[-1] in "rework the whole ingestion pipeline so that every supplier feed is normalised".split(),
              wordy_slug)
        check("a long title is trimmed too",
              len(wordy_entry.read_text().splitlines()[6]) <= 92,
              wordy_entry.read_text().splitlines()[6])

        slug_override = Path(write("--plan", str(auto), "--prompt-file", str(prompt_file),
                                   "--slug", "Parse Hejlsberg", cwd=repo).stdout.strip())
        check("--slug overrides the derived slug",
              slug_override.name.endswith("-parse-hejlsberg.md"), slug_override.name)

        # final report
        report_file = tmp / "final.md"
        report_file.write_text(REPORT)
        appended = report("--report-file", str(report_file), "--entry", str(entry))
        check("report appends to the named entry",
              appended.returncode == 0 and Path(appended.stdout.strip()) == entry,
              appended.stdout.strip() + appended.stderr.strip())
        with_report = entry.read_text()
        check("report section is added", "\n## Final report\n" in with_report)
        check("report is verbatim", REPORT in with_report)
        check("prompt and plan survive the append",
              PROMPT in with_report and PLAN.strip() in with_report)
        check("frontmatter gains completed:", "\ncompleted: 20" in with_report)

        completed_line = [l for l in with_report.splitlines() if l.startswith("completed:")][0]
        again = report("--report-file", "-", "--entry", str(entry),
                       stdin="a second pass over the same plan")
        twice = entry.read_text()
        check("a second report does not overwrite the first",
              again.returncode == 0 and "## Final report\n" in twice
              and "## Final report (2)\n" in twice and REPORT in twice, again.stderr.strip())
        check("completed: keeps the first completion",
              [l for l in twice.splitlines() if l.startswith("completed:")] == [completed_line])

        newest = report("--report-file", str(report_file), cwd=repo)
        check("report finds the project's newest entry without --entry",
              newest.returncode == 0
              and Path(newest.stdout.strip()).parent == journal / "my-project"
              and Path(newest.stdout.strip()) == sorted((journal / "my-project").glob("*.md"))[-1],
              newest.stdout.strip() + newest.stderr.strip())

        empty_report = tmp / "empty.md"
        empty_report.write_text("\n  \n")
        check("an empty report is refused",
              report("--report-file", str(empty_report), "--entry", str(entry)).returncode != 0)
        check("a missing entry is refused",
              report("--report-file", str(report_file), "--entry", str(tmp / "nope.md")).returncode != 0)
        check("an unfiled project is refused",
              report("--report-file", str(report_file), "--project", "never-filed").returncode != 0)

        # project resolution
        nogit = tmp / "no-git-project"
        (nogit / ".ai" / "plans").mkdir(parents=True)
        nogit_plan = nogit / ".ai" / "plans" / "20260902090000-add-cache.md"
        nogit_plan.write_text(PLAN)
        nogit_result = write("--plan", str(nogit_plan), "--prompt-file", str(prompt_file))
        check("non-git project resolves by its .ai dir",
              nogit_result.returncode == 0
              and Path(nogit_result.stdout.strip()).parent == journal / "no-git-project",
              nogit_result.stdout.strip() + nogit_result.stderr.strip())

        loose = tmp / "loose" / ".ai" / "plans"
        loose.mkdir(parents=True)
        loose_plan = loose / "20260902090000-loose.md"
        loose_plan.write_text(PLAN)
        loose_result = write("--plan", str(loose_plan), "--prompt-file", str(prompt_file), cwd=tmp)
        check("a loose plan never files under plans/ or .ai/",
              loose_result.returncode == 0
              and Path(loose_result.stdout.strip()).parent.name == "loose",
              loose_result.stdout.strip() + loose_result.stderr.strip())

        check("journal path with a space works", " " in str(journal) and entry.is_file())

        # plans written under the older conventions still resolve to their project
        for marker in (".opencode", ".claude"):
            legacy = tmp / f"legacy{marker}"
            (legacy / marker / "plans").mkdir(parents=True)
            legacy_plan = legacy / marker / "plans" / "20260902090000-legacy.md"
            legacy_plan.write_text(PLAN)
            result = write("--plan", str(legacy_plan), "--prompt-file", str(prompt_file))
            check(f"a plan under {marker}/plans still resolves its project",
                  result.returncode == 0
                  and Path(result.stdout.strip()).parent == journal / f"legacy-{marker.lstrip('.')}",
                  result.stdout.strip() + result.stderr.strip())

        # a plan outside the project it belongs to
        (home / ".ai" / "plans").mkdir(parents=True, exist_ok=True)
        global_plan = home / ".ai" / "plans" / "elegant-hopping-book.md"
        global_plan.write_text(PLAN)
        no_hint = write("--plan", str(global_plan), "--prompt-file", str(prompt_file))
        check("a plan under the home directory lands in unsorted/",
              no_hint.returncode == 0 and Path(no_hint.stdout.strip()).parent.name == "unsorted",
              no_hint.stdout.strip() + no_hint.stderr.strip())
        from_cwd = write("--plan", str(global_plan), "--prompt-file", str(prompt_file), cwd=repo)
        check("cwd names the project when the plan is outside it",
              from_cwd.returncode == 0
              and Path(from_cwd.stdout.strip()).parent == journal / "my-project",
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
              and Path(recorded.stdout.strip()).parent == journal / "my-project",
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
              and Path(from_config.stdout.strip()).parent == config_journal / "my-project",
              from_config.stdout.strip() + from_config.stderr.strip())
        env_wins = run("write", "--plan", str(plan), "--prompt-file", str(prompt_file),
                       home=config_home, journal=journal)
        check("HOKO_JOURNAL_PATH beats hoko.json",
              env_wins.returncode == 0
              and Path(env_wins.stdout.strip()).parent == journal / "my-project",
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

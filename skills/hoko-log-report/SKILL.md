---
name: hoko-log-report
description: Append the final report of a finished plan run to its journal entry, next to the initial prompt and the plan. Use when every step of a plan is done, or when asked to journal, log or record the final report, outcome or commits of a run.
---

# Log report

Plan: the absolute repository plan path the user gave, or the one this run already holds.

This closes the journal round that filing opened for this plan — its `Journal:` line
names the round. The `hoko-journal-writer` subagent runs one script; you supply the report
text and nothing else.

The normal way to close a run is one command, `plan-progress.py complete --plan <path>
--report-file -`, which sets `Status: complete` and files the report together. Reach
for this skill only as the manual fallback — the plan was marked complete some other
way, or a round still needs a report filed by hand. Do it now rather than after
replying — the entry is the only lasting record of how the run went.

## 1. The report

Use the closing report of this run exactly as you posted it, in this shape and nothing
else, no prose paragraphs, no restatement of the plan:

```
**Outcome:** <one line: done / stopped at step N and why>
**Branch:** <name>
**Commits:** - `<sha>` <subject>   (one per commit, QA fixes included)
**Gate:** lint <pass/fail> · analyse <pass/fail> · tests <pass/fail>, coverage <n>% (<up/down/flat>)
**QA debt:** none | <findings file paths, one per check> — want me to plan the fix?
**Specs:** <spec files and requirement ids touched> | no behaviour touched | off
**Review:** clean | <n> findings (<counts by severity>) → <follow-up plan path>
## Open items
- [ ] … | _none_
```

If you have not posted one yet, write it now: it is the record of what actually
happened, so name real commits and real test commands, not intentions.

Write it to a file with a heredoc so nothing is reworded on the way:

```bash
mkdir -p /tmp/hoko-journal
cat > "/tmp/hoko-journal/report-$(date +%s).md" <<'REPORT'
<the final report, verbatim>
REPORT
```

`## Open items` is always the last thing in the report: one unchecked box per loose
end, each a single line that names the thing concretely — a file, a command, a
symptom — so it still reads on its own in six months. It goes in whether or not the run
went well: anything left undone, deliberately deferred, carried forward, or turned up by
a review and not acted on. Write `_none_` under the heading when there is genuinely
nothing. One heading only, and boxes rather than prose.

Where the run's plan has steps marked `- Irreversible: <text>`, list each marked step
under `## Open items` as its own box, with its `Irreversible:` text, so the human
reviewing before merge sees what a revert cannot undo.

I close these by ticking the box in the entry itself, so do not tick one yourself and
do not restate items already open in an earlier entry.

## 2. Delegate the append

Invoke the `hoko-journal-writer` subagent:

> Run:
> `python3 "${HOKO_ROOT}/scripts/journal.py" report --plan "<absolute plan path>" --report-file "<absolute report file path>"`
> Run it from the project directory and do not `cd` anywhere.
> Report only the path it prints, or the error if it fails.

Use the plan path the user gave, or the repository plan path this run already
holds. The script reads that plan's `Journal:` line to find the round.

The entry's analytics folder (`<analyticsPath>/<project>/<entry folder>/`, or the entry
itself when `analyticsPath` is empty) holds `sessions.json` (the sessions that belong to
the plan) and the `invoice.md` / `invoice.json` priced from them. `plan-progress.py
complete` rewrites the invoice; this fallback does not, so regenerate it with
`python3 "${HOKO_ROOT}/scripts/invoice.py" write --entry "<the round's folder>"`
when the report is filed by hand.

## 3. Report

One line: the report path, and that it is filed. If the script says the plan has no
`Journal:` line, it was never filed — run `plan-file.py file --plan <path>` first, then
come back.

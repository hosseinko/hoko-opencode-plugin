---
name: hoko-log-plan
description: Archive the initial prompt and the approved plan of a plan-mode cycle into the per-project journal. Use right after approving a plan, or when asked to journal, log, or record a prompt and plan.
---

# Log plan

Plan: the absolute path the user gave, or the plan file this session just wrote.

Approval normally files the plan by itself: `plan-file.py file` runs when the plan is
handed off, and the session stops right after. Run this only when that did not happen —
the plan was not filed, or it needs re-filing by hand.

Filing is one script call: write no entry yourself and do not read the plan.

## 1. The plan file

Use the path the user gave. If none was given, use the plan file you just wrote in
this session — plan mode keeps it in the plans directory (`settings.py plansDir`,
`.ai/plans` by default). If you have neither, run:

```bash
python3 "${HOKO_ROOT}/scripts/plan-find.py"
```

and confirm the newest one with me before filing. Do not invent a plan.

## 2. File it

Run it yourself, from the project directory, without `cd`-ing anywhere:

```bash
python3 "${HOKO_ROOT}/scripts/plan-file.py" file --plan "<absolute plan path>"
```

The prompt and the project are settled without you: it passes no session id, so the
project comes from the working directory, which is why you must not `cd`, and the prompt
falls back to the project's own prompt anchor, or a placeholder when that is gone too. Since it is the project's anchor rather than this session's, note: if
`/hoko/execute-plan` already ran in this session, that anchor may hold its prompt rather
than the original one.

## 3. Report

One line: the path it printed. If the script failed, say why — a missing `journalPath`
in `hoko.json`, an unreadable plan, or no repository found from the working directory.
Do not retry with a hand-written entry.

If the entry landed under `unsorted/`, the project could not be determined: say so.

Keep the entry path. When every step of the plan is done, `hoko-log-report` appends
the run's final report to that same file.

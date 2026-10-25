---
id: SPEC-006
title: Run session registry and invoicing
covers:
  - plugin/hoko.ts
  - plugin/invoice.ts
  - scripts/journal.py
  - scripts/task.py
---

# Run session registry and invoicing

## Context

A run's cost outlives the checkout that ran it, so it is filed in the journal entry's
analytics folder beside the run's events: `sessions.json` names the sessions the run used,
`usage.json` and `rates.json` hold what a live plugin could read from them, and
`invoice.json` and `invoice.md` price them. Only a live plugin process can read a session's
messages, so the plugin records sessions as they appear and turns usage into an invoice
once the run has finished. The *project registry* is the per-repository list of sessions the
plugin has seen; *run registration* is the task's finish step that copies it into the run's
registry, one row per round.

## Requirements

- **REQ-1** The plugin shall record every top-level session it sees created in the project registry of the git repository that session runs in.
- **REQ-2** The project registry shall hold at most one row per session id.
- **REQ-3** The project registry shall keep at most 100 rows, dropping the oldest recorded rows first.
- **REQ-4** If a record request names no session, then the recording command shall exit non-zero and write no row.
- **REQ-5** If a project registry row names no readable transcript, then the run registration shall keep the row when the row was recorded at or after the run's start.
- **REQ-6** When a task's report is filed, the run registration shall write one row per project-registry session and round, each stamped with that round's start time.
- **REQ-7** The run registration shall write a row for the session that conducted the task whenever the project registry names it.
- **REQ-8** When a turn ends while the project's newest task run is `done` and has no invoice, the plugin shall write that run's usage and the model rates into its analytics folder.
- **REQ-9** When a finished task run's usage is written, the plugin shall render `invoice.json` and `invoice.md` whose total is the sum of the run's usage costs.
- **REQ-10** If a finished task run already has an invoice, then the plugin shall write no usage, no rates and no invoice for it at a later turn end.
- **REQ-11** While a task run's status is `in_progress` or `stopped`, the plugin shall write no usage and no invoice for that run.
- **REQ-12** If a task run has no journal entry, then the plugin shall write no usage and no invoice for it and shall leave the turn's outcome unchanged.
- **REQ-13** The plugin shall bill each assistant response to at most one run-registry row, including when that response's session is also a descendant of another row.
- **REQ-14** If a session's messages cannot be read, then the plugin shall note that session and continue collecting the other sessions of the same run.
- **REQ-15** The plugin shall resolve the folder holding the run registry, the usage, the rates and the invoice with the same rule the journal scripts use, so a journal entry never holds its own copy beside its analytics folder.

## Acceptance criteria

```gherkin
Feature: Run session registry and invoicing

  Scenario: a task run is invoiced from the conductor's turn end
    Given a finished task run whose plan a subagent wrote, whose conductor wrote no plan, and whose analytics folder holds no usage
    When the conductor's turn ends
    Then the analytics folder holds usage.json, rates.json, invoice.json and invoice.md
    And the invoice total is the sum of the usage rows' costs

  Scenario: a second turn end invoices the same run once
    Given a task run that has already been invoiced
    When the conductor's turn ends again
    Then the invoice files are unchanged and no second invoice is written

  Scenario: a run still in progress is not invoiced
    Given the newest task run's status is in_progress
    When a turn ends in a session that wrote no plan
    Then that run has no usage.json and no invoice

  Scenario: a session recorded without a transcript still registers
    Given a project registry row with an empty transcript path recorded after the task started
    When the task's report is filed
    Then sessions.json holds a row for that session in every round
```

## Design notes

`journal.py` gains a `record` mode beside `register`: it calls `record_session`, writing
`sessions-<sha256(root)[:16]>.json` under the state dir, one row per session (`session_id`,
`transcript_path`, round 1, role `execute`, `since` now), at most `RECORDED_SESSIONS_LIMIT`
(100). The plugin calls it over its `journal()` helper from the `session.created` handler for
a session with no `parentID`, passing the git toplevel of the session's directory because
`task.py` keys the same file on `git rev-parse --show-toplevel`.

opencode exposes no transcript path for a session and keeps messages in `opencode.db`, so the
row carries an empty `transcript_path`. `task.py finish` always reads the registry with
`after=started`, so `journal.written_since` falls back to the row's own `since` when the
transcript is absent, which is what keeps `task.py` unchanged.

`task.py finish` writes `<task folder>/finish-pending.json` naming the journal entry and the
newest plan. Invoicing moves out of the journaling path into `plugin/invoice.ts`, called from
its own end-of-turn handler: usage collection, rate lookup, the finish-marker close and the
invoice write. The marker is deleted once the invoice exists, and the `progress.json` status
of `done` is the second guard, which is what makes the close idempotent and what keeps
`in_progress` and stopped runs untouched.

`sessions.json` lives in the analytics folder (`analytics.folder_for`), not in the journal
entry, and the plugin asks `journal.py` for that path instead of rebuilding the rule in
TypeScript. Descendant sessions are billed to the row that spawned them, so a subagent that
is itself a row is not visited again as a descendant. Rates come from the model catalog at
close, and an unreadable model list yields an empty table rather than a failed invoice.

## Open questions

- A run whose conductor turn never ends after `task.py finish` keeps its finish marker and stays uninvoiced. Whether a later turn end in the same project should pick the oldest stale marker, or only the newest done run, is not settled.

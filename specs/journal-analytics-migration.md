---
id: SPEC-002
title: Journal analytics migration
covers:
  - scripts/migrate-analytics.py
  - scripts/analytics.py
---

# Journal analytics migration

## Context

A journal entry's analytics — its session registry, its invoice and its runs' event logs —
outlive the journal tree they grew in, so a one-off migration moves them into an analytics
root laid out as `<analytics root>/<project>/<entry>/` and backfills the event logs that a
round never had. A *round* is one numbered `plan-<NN>.md` and `report-<NN>.md` pair of an
entry. A *synthesized* event stands in for a run whose live log was never copied; it is
identified by its run id `<entry>-r<NN>`, a form a real run's 26-character ULID never
takes, and by its `payload.migrated` marker.

## Requirements

- **REQ-1** When the migration processes a journal entry, it shall move the entry's `sessions.json`, `invoice.json`, `invoice.md` and every `events-<NN>.jsonl` into that entry's analytics folder, overwriting a target file that already exists.
- **REQ-2** When a round has no event copy and has a plan file, the migration shall synthesize a `run.started` event dated from that plan file's modification time.
- **REQ-3** When a round has no event copy and has a report file, the migration shall synthesize a `run.finished` event dated from that report file's modification time.
- **REQ-4** The migration shall write a synthesized round under the run id `<entry>-r<NN>`.
- **REQ-5** A synthesized `run.started` event shall set `payload.migrated` to `true`.
- **REQ-6** A synthesized `run.started` event shall set `payload.text` to the plan's first `# ` heading, else the plan's first non-empty line, cut to at most 120 characters.
- **REQ-7** A synthesized `run.started` event shall set `payload.path` to the round's `plan-<NN>.md` in the journal.
- **REQ-8** When the migration synthesizes an event for an entry of a Claude journal, it shall set `payload.backend` to `claude-code` rather than `opencode`.
- **REQ-9** A synthesized event shall validate against the committed event schema.
- **REQ-10** When an existing event file's run id matches `<entry>-r<NN>`, the migration shall rewrite its `run.started` payload to the slim shape — the marker, the title-line text, the plan path and the journal's backend — and leave every other event in the file unchanged.
- **REQ-11** The migration shall leave every event file whose run id is a 26-character ULID unchanged.
- **REQ-12** When the migration fills an entry's analytics folder, it shall write `entry.json` naming the journal entry's absolute path, its project and entry names, the run ids the folder already lists plus the synthesized ones, and the session ids of its `sessions.json`.
- **REQ-13** If a round has neither a plan nor a report, then the migration shall skip that round with a note on stderr naming it.
- **REQ-14** When the migration runs a second time over an entry whose rounds all have an event copy, it shall change no file.
- **REQ-15** If the journal tree does not exist or a file operation fails, then the migration shall report the reason on stderr and exit non-zero.

## Acceptance criteria

```gherkin
Feature: Journal analytics migration

  Scenario: a round without an event copy is backfilled with a slim migrated event
    Given a journal entry with plan-01.md, report-01.md and no events-01.jsonl
    When the journal is migrated
    Then events-01.jsonl holds a run.started and a run.finished under run id <entry>-r01
    And the run.started payload's text is the plan's title line, its path the journal plan-01.md, its migrated marker true

  Scenario: a real run's event file survives a migration pass
    Given an analytics events-01.jsonl whose run id is a 26-character ULID
    When the journal is migrated
    Then that file is byte-for-byte what it was

  Scenario: an existing synthesized file is slimmed
    Given an events-02.jsonl whose run id is <entry>-r02 and whose run.started text is a whole plan
    When the migration runs
    Then its run.started payload carries the title-line text and the migrated marker
    And its run.finished event is unchanged
```

## Design notes

`migrate-analytics.py <journal root> <analytics root>` moves `MOVED_FILES` plus the
`events-<NN>.jsonl` copies, then walks the union of the rounds its plans, reports, event
copies, `sessions.json` and `invoice.json` name. A synthesized run is two events: the
`run.started` payload holds `source: plan`, `text`, `path` and `backend`, and `run.finished`
holds `{"status": "done"}`. Today `text` is the whole plan, which leaves the migrated files
at 7–46 KB.

`payload.migrated` is a payload key, not a ninth envelope field: the schema's own test
pins the envelope at eight fields, while the schema leaves payload objects open, so a
consumer that validates strictly against the schema accepts the key and drops it.

`backend` comes from `events.BACKEND`, the constant `opencode`, for every tree today; a
Claude tree needs its own value passed in. The rewrite of an existing synthesized file is a
separate step keyed on the `<entry>-r<NN>` run id, because the migration's own idempotence
check skips any round that already has an event copy. The journal path of an entry is read
back from its analytics folder's `entry.json`, so a tree whose files already moved needs no
journal root argument.

## Open questions

- Whether a Claude tree's backend reaches the migration as an argument or is derived from the analytics root is not settled. REQ-8 fixes only that those events carry `claude-code`, never `opencode`.

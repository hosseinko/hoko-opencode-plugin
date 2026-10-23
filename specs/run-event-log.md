---
id: SPEC-001
title: Run event log storage and retention
covers:
  - scripts/events.py
  - scripts/progress.py
  - scripts/plan-progress.py
---

# Run event log storage and retention

## Context

Every plan run and every `/hoko/task` run keeps an append-only event log in the
hoko-code event schema: one JSON object per line, numbered from 1. The log is written live
under the repository's events directory and copied into the run's journal analytics folder
when the run closes, because the analytics folder is the record that outlives the checkout.
A *run id* is the 26-character ULID naming one run, and the *events directory* is the
`eventsDir` setting, `.ai/runs` by default.

## Requirements

- **REQ-1** The event writer shall append each event as one JSON object holding exactly the eight fields `v`, `event_id`, `run_id`, `seq`, `ts`, `type`, `project` and `payload`.
- **REQ-2** While several processes write events for one run, the event writer shall number the events with `seq` 1, 2, 3 … with no gap and no repeat.
- **REQ-3** The event writer shall keep a run's live log at `<repository root>/<events directory>/<run id>/events.jsonl`.
- **REQ-4** When the events directory is first written to, the event writer shall mark its top folder ignored, so `git add -A` never stages an event file.
- **REQ-5** If an event cannot be written, then the event writer shall disable events for that run and leave the calling command's exit status unchanged.
- **REQ-6** While the `events` setting is off, the event writer shall write no event.
- **REQ-7** When a run completes, the closing command shall copy the run's live log into the journal round's analytics folder as `events-<NN>.jsonl`.
- **REQ-8** When the copy of a run's live log succeeds, the closing command shall delete the run's live directory.
- **REQ-9** If no copy is made — journaling off, no journal round for the plan, or an unreadable source — then the closing command shall retain the run's live directory and shall not fail the completion.
- **REQ-10** If a run is aborted, then the closing command shall retain the run's live directory and shall not copy it into the analytics folder.

## Acceptance criteria

```gherkin
Feature: Run event log storage and retention

  Scenario: a completed run's live directory is pruned after the copy
    Given a run whose events are under the events directory and a journal round for its plan
    When the run completes
    Then the journal round's analytics folder holds events-<NN>.jsonl
    And the run's live directory is gone

  Scenario: an aborted run keeps the only copy of its events
    Given a run whose events are under the events directory
    When the run is aborted
    Then the run's live directory still holds events.jsonl
    And no events-<NN>.jsonl is written for it
```

## Design notes

`events.py` builds the eight-field envelope, derives `seq` from the newline count under an
exclusive `flock` on `events.jsonl.lock`, and writes one `os.write` on an `O_APPEND`
descriptor. The failed-write path drops an `events.disabled` file in the run directory and
notes `events not recorded: <reason>` once on stderr.

The copy lives in `plan-progress.py`'s `write_closing_events`, which both `plan-progress.py
complete` and `task.py finish` reach: the run's `run.finished` is written, then the log is
copied, then the run id is listed in the folder's `entry.json`. The analytics folder is
`<analyticsPath>/<project>/<entry>`, or the journal entry itself when `analyticsPath` is
empty. An `eventsDir` that is absolute is used as given; a relative one is resolved against
the git toplevel, and the `.gitignore` holding `*` lands in its first path component.

`abort` writes `stage.failed` and then `run.finished` with `status: failed`, and never
copies, which is why an aborted run's events exist only under the events directory. The
same holds for a run whose process died before any close command ran.

## Open questions

- A run that completes with journaling off makes no analytics copy, so under REQ-9 its live directory stays under the events directory for good. Whether such a completed run should be pruned anyway, discarding its only log, is not settled.
- The answers give a successful copy as the trigger for pruning but say nothing about a directory that cannot be deleted. Whether that is a note on stderr, as an unwritable analytics folder is, or a failed completion is undecided.

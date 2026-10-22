---
name: hoko-task
description: Run a task through the whole pipeline — specifier, spec writer, planner, implementer, QA, reviewer — with automatic fix loops, interrupting the user only for product decisions. Use when handed a task to do end to end, a plan file to run, or a task folder to resume.
---

# Task

Task: $ARGUMENTS

You are the conductor. `task.py` is the state machine: it holds the stage order, the skip
rules, the cycle count, the loop limit and the spec hand-back in code. You do not decide
the flow, you dispatch it. The loop is always the same: ask `task.py next`, do the one
action it prints, report the result with `task.py record` (or `answer`), ask again.

The pipeline spawns agents that write and commit, so each stage agent carries the edit and
shell permissions it needs; the conductor runs on `build` and every stage runs in a child
session through the `subagent` tool.

## Calling task.py

```bash
python3 "${HOKO_ROOT}/scripts/task.py" <command> …
```

Every call names the task folder by `--task "<dir>"`, the `dir` that `start` printed, and
no `--root`: the call is then a plugin script run with no repository path, and the
plugin's loop guard lets it through. Free text (the prompt, an answer, a reason, the
report) goes in on a stdin heredoc (`-`), not on the command line. A call that exits
non-zero printed why on stderr: read it before trying again.

## Starting

Read the argument and pick one:

- **A task folder** (a directory holding a `progress.json`, under the `plansDir` setting):
  resuming. Skip to *The loop*. `next` reconciles the checklist itself and returns the
  first unticked step, or spawns a stage that has no hand-off again.
- **A plan file** (an existing `.md` file that is not under `specs/`): start from the plan.
  `start` skips Refine, Spec and Plan, and keeps the run id the plan's own
  `<stem>.progress.json` carries. The title is the plan's first heading, at most six
  words.

  ```bash
  python3 "${HOKO_ROOT}/scripts/task.py" start --title "<title>" --plan "<absolute plan path>" --prompt-file - <<'PROMPT'
  Run the plan at <absolute plan path>.
  PROMPT
  ```

- **A spec file** (a path under `specs/`): start from the spec. `start --spec` skips
  Refine and Spec, writes `spec.json` from the file's front-matter id and its live
  requirements, and goes to Plan. The title is the spec's first heading, at most six
  words. It exits 2, naming why, when the file is missing, outside the repository or has
  no front-matter `id:`: bring that to the user, no task folder was made.

  ```bash
  python3 "${HOKO_ROOT}/scripts/task.py" start --title "<title>" --spec "<spec path>" --prompt-file - <<'PROMPT'
  Implement the spec at <spec path>.
  PROMPT
  ```

- **Free text**: start from a prompt. Title: at most six words from the prompt.

  ```bash
  python3 "${HOKO_ROOT}/scripts/task.py" start --title "<title>" --prompt-file - <<'PROMPT'
  <the user's prompt, verbatim>
  PROMPT
  ```

- **Nothing**: ask what the task is, and stop.

`start` prints one JSON object: `task` (the folder's name), `dir`, `run_id`, `journal`.
It refuses, exiting non-zero, when `plansDir` is tracked by git. Bring that to the user:
`step-commit.py` stages with `git add -A`, so the plans directory must be ignored. A
`/hoko/execute-plan` run that cannot start this way follows its own conductor instead.

## The ticket

No ticket is fetched or edited: there is no Jira integration here. The key only names the
branch, and it comes from the plan's `Ticket:` header line on a plan start, or from
`ticket` in the task folder's `scope.json`. When there is no key, skip this section
silently.

## Division of labour

You write no implementation code, specs or plans, and you review no diff. Every stage has
an agent, and `hoko-plan-executor` owns the code. You do not gate, stage or
commit by hand: `step-commit.py` runs the fast gate, commits and ticks the plan in one
enforced call. You never run `git add`, `git commit` or `plan-progress.py tick`.

The conductor does not modify or open a source or spec file by any route: not `write`,
`edit` or `patch`, not `sed -i`, redirection, a heredoc into an interpreter, `php -r`,
`python3 -c`, `patch`. The files you may read and the only ones you write are in the task
folder under `plansDir`: hand-offs, `progress.json`, plans. The plugin's loop guard
enforces that while a run is `in_progress`. If it denies a call, you skipped a
delegation; launch the agent instead.

Keep your context small. Do not paste an agent's report back to the user verbatim, and do
not re-derive what a hand-off already states.

## The loop

Run:

```bash
python3 "${HOKO_ROOT}/scripts/task.py" next --task "<dir>"
```

It prints one JSON object and writes nothing a second ask would repeat. Do what its
`action` says.

### spawn

Launch the agent the action names with the `subagent` tool:

- `agent`: the action's `agent` (`hoko-specifier`, `hoko-spec-writer`, `hoko-planner`,
  `hoko-quality-assurance`, `hoko-final-reviewer` or, for a blocked step, `hoko-researcher`)
- `description`: the action's `name`, so the child session is findable in the UI
- `prompt`: the action's `prompt`, verbatim. It names the hand-off file the agent writes.
- `model`: the action's `model`, when it carries one, so it wins over the agent file. Its
  `#variant` already carries the stage's effort, written by `task.py`; the plugin appends the
  same effort to the agent's own model for a launch that passes none. Pass the reference
  through unchanged.

It returns the child session's `sessionID`. Record the stage with that id, so a later
answer can resume the same child:

```bash
python3 "${HOKO_ROOT}/scripts/task.py" record --task "<dir>" --stage <the action's stage> --agent-session "<sessionID>"
```

and ask `next` again. The agent answers with the path of its hand-off and one line; the
file is what counts.

`record` validates the hand-off before it changes anything. If it exits non-zero naming a
problem in the file, the agent wrote a bad hand-off: resume that child with the `subagent`
tool, `sessionID` set to the id you recorded and `prompt` naming the problem, and ask it to
rewrite the file. Record again. A second failure ends the task with `task.py stop` and the
problem as the reason.

A `Plan` spawn after the user sent the plan back (`Revise`, see *ask*) carries the user's
changes in its prompt and rewrites the same `plan-01.md`; record it as any Plan. A `Plan`
spawn with `mode` `replan` follows an implementer's blocker (see *step*): the planner
writes the next round's plan, and `record --stage Plan` adds it to the same cycle.

A `hoko-researcher` spawn is not a stage: when it returns its findings file, record the
path (see *step*) and ask `next` again.

A `Spec` spawn has `mode` (`write` or `revise`) and, when the `specs` setting is off, a
`spec_path` for a local spec. The prompt already says all of that. A spec hand-back from
the planner is routed by `next` alone: a Spec `revise` spawn, then Plan again, and after
the third hand-back an `ask`.

### resume

`next` returns `resume` after an `answer`: the agent that asked is carried on with what
the user said. Continue that child with the `subagent` tool, `sessionID` set to the
action's `session_id` and `prompt` set to the action's `message`. When it returns,
`record --stage <the action's stage> --agent-session "<sessionID>"` as for a spawn.

If the child cannot be reached (it is gone, or the call fails), ask `next` again with
`--resume-failed`: it returns a fresh `spawn` that points the new agent at `answers.json`.

### ask

Put the action's `questions` (1 to 4) to the user with the `question` tool, one entry per
question: the action's `question` as the text, its `stage` as the header, its `options` as
the labels with the `recommended` one first and marked `(Recommended)`, and its `why` as
that option's description. Then store the answers, one JSON object of question id to the
answer text:

```bash
python3 "${HOKO_ROOT}/scripts/task.py" answer --task "<dir>" --answer-file - <<'ANSWER'
{"<question id>": "<the chosen option, verbatim>"}
ANSWER
```

The answer text starts with the option's own words. When the user types a reply beyond the
option, keep the option they started from and put their words after it (`Continue also
cover the empty case`), since that is how the pipeline reads a loop-limit answer. Then ask
`next` again.

An `ask` is the only way the pipeline interrupts the user. Questions from the agents are
product decisions; the loop-limit question (stage `Cycles`) is the user's call on whether
to continue, accept the open findings as a follow-up plan, or stop. With `loopLimit` 0 the
pipeline asks no such question: it accepts the open findings itself and `finish` follows.

The plan gate (stage `Plan`, on by default; `"planGate": false` in
`~/.config/opencode/hoko.json` or `HOKO_PLAN_GATE=false` turns it off) comes right after
the Plan hand-off is recorded, with the options `Approve`, `Revise` and `Stop`. Pass the
answer on as the option's own word. When the user wants changes, they pick `Revise` and
say what to change: send `Revise: <their words>`. `answer` refuses a bare `Revise`, so ask
what to change and answer again. `Approve` goes on to the steps, `Revise` returns a `Plan`
spawn, `Stop` ends the task.

### branch

The task is on a protected branch (`current`). No agent can fix that from inside a
commit, so settle it here, naming the branch by the *Branch names* rule in the
session-start context (`<prefix>/<KEY>-<slug>`), then `git checkout -b <name>`:

- **`ticket` set** (see *The ticket*): build the name from its key and the action's `slug`,
  create the branch without asking and state its name in one line.
- **No `ticket`:** ask the user for the ticket key or the full branch name. Create no
  branch without a key unless the user named it that way.

Then ask `next` again.

### preflight

Run the action's `command` (the fast gate) once, timed, and report its exit status:

```bash
start=$(python3 -c 'import time; print(int(time.time() * 1000))'); <the action's command>; code=$?
end=$(python3 -c 'import time; print(int(time.time() * 1000))')
python3 "${HOKO_ROOT}/scripts/task.py" record --task "<dir>" --stage Preflight --exit-code "$code" --duration-ms $((end - start))
```

A red gate comes back as an `ask`: the project was red before this task touched anything,
and only the user can say whether to run alongside it.

### step

The next unticked step of the plan. Mark it started, in the same message that launches the
implementer:

```bash
python3 "${HOKO_ROOT}/scripts/plan-progress.py" start --plan "<the action's plan>" --step <the action's step>
```

Launch `hoko-plan-executor` with the `subagent` tool: `description` `<action's
title>`, `model` from the action when it carries one (its `#variant` carries the implement
effort, written by `task.py`; the plugin applies the same effort to the agent's model when
none is passed), and this prompt:

> Implement step `<step>` of the plan. Everything you need is in `<the action's slice>`
> — read it first, then implement and test only that step. Do not commit and do not edit
> that file or the plan it names.

Then when it returns, trust its report over anything else; do not re-run `git status` or
the gate yourself, and turn the report into a commit:

- **Blocker.** The report's `Blocker: <kind> — <text>` line is recorded with `task.py`,
  whatever the kind; you route nothing yourself. Build the JSON from that line (`step` is
  the action's `step`, `text` the executor's own words) and send it on stdin:

  ```bash
  python3 "${HOKO_ROOT}/scripts/task.py" record --task "<dir>" --stage Implement --agent-session "<sessionID>" --blocker-file - <<'BLOCKER'
  {"kind": "<spec|plan|external|product>", "text": "<the blocker text>", "step": <the action's step>}
  BLOCKER
  ```

  The `sessionID` is the executor's, so a product question can resume the agent that
  found the blocker. The step stays `in_progress` and `next` says what follows: a `Spec`
  spawn (`revise`) and then a `Plan` spawn (`replan`) for `spec`; a `Plan` spawn (`replan`)
  for `plan`, and after the third in a cycle an `ask`; a `hoko-researcher` spawn for
  `external`; an `ask` for `product`, and for a second `external` on the same step.
  Dispatch it as any action.
  Do not launch the step again yourself or decide that a blocker is not one: a `spec`
  blocker of a task that has no spec is refused with the reason, so record it as `plan`.

  When the researcher returns its findings file, record its path, then ask `next`, which
  returns the same step:

  ```bash
  python3 "${HOKO_ROOT}/scripts/task.py" record --task "<dir>" --stage Implement --research "<the findings path>"
  ```

  A step action may carry `context` (the user's answer to a blocker, or the findings path
  of the research): add it to the executor's prompt verbatim, as its last paragraph.
- **Nothing needed changing** (a step already satisfied by earlier work):

  ```bash
  python3 "${HOKO_ROOT}/scripts/step-commit.py" --plan "<the action's plan>" \
    --step <N> --no-op "<the executor's own reason>"
  ```

- **Otherwise**, write the commit message yourself from the step's own text in the plan
  and the executor's *What you did*, in `hoko-commit`'s format: a plain, why-focused
  summary line ending in a full stop, a blank line, then one `* `-bulleted, imperative
  sentence per change, each ending in a full stop. No ticket key on its own;
  `step-commit.py` adds it from the branch name.

  ```bash
  python3 "${HOKO_ROOT}/scripts/step-commit.py" --plan "<the action's plan>" \
    --step <N> --message-file - <<'MSG'
  <the commit message, verbatim>
  MSG
  ```

`step-commit.py`'s exit code: 0 the step is done (report one line: step, commit subject or
no-op reason, gate result) and you ask `next` again. 5 the message broke the mechanical
format: fix it from the rules it printed and rerun. 1, 3, 4 or 6 is a blocker: 1 a red
gate, 3 a protected branch, 4 a tree or mode mismatch, 6 a failed `git commit`. None tick
the step. Stop the task with the script's own output as the reason.

### finish

Every cycle is green, or, with `loopLimit` 0, the open findings were accepted and the
action's `followup` is the plan they became. Compose the closing report in this shape and
nothing else. The facts come from the task folder: `progress.json` (`base`, `spec`,
`cycle`, `loop_limit`, `flow.accepted`), the last `qa-<NN>.json` and `review-<NN>.json`,
and `git log --format='%h %s' <base>..HEAD`.

```
**Outcome:** <one line: done, or done with the open findings accepted>
**Branch:** <name>
**Commits:** - `<sha>` <subject>   (one per commit, QA fixes included)
**Gate:** the last qa-<NN>.json's gates, one `<check> <status>` per gate
**QA debt:** none | <the debt paths, one per check> — want me to plan the fix?
**Specs:** <the spec paths from progress.json and the requirement ids> | none
**Review:** clean | skipped (trivial task) | <n> findings → <the accepted follow-up plan's path>
**Cycles:** <cycles run> of <1 + loop_limit>
## Open items
- [ ] … | _none_
```

`**QA debt:**` is `none` when the last QA's `debt` is empty; an offer to plan the fix is
an offer only, never a plan started unasked. `**Review:**` names the follow-up plan only
when `flow.accepted` is set (the action's `followup` is its path): a task closed by Accept
leaves its open findings as that plan, in the task folder, and it is not run. The
`## Open items` heading takes one unchecked box per loose end, named concretely, or
`_none_`. Where a round's plan has steps marked `- Irreversible: <text>`, list each marked
step of every round's plan under it as its own box, with its `Irreversible:` text, so the
human reviewing before merge sees what a revert cannot undo.

Close the task with that report, fed through a heredoc so nothing is reworded:

```bash
python3 "${HOKO_ROOT}/scripts/task.py" finish --task "<dir>" --report-file - <<'REPORT'
<the closing report, verbatim>
REPORT
```

It writes `report.md`, the closing events and the journal entry. Then post the same
report to the user, after filing it, not before. With the task finished the branch is
done but not integrated: merging, pushing and branch handling follow the standing rules in
the session-start context. Say the branch is ready for a pull request and leave it to the
user.

### stop

The task ended: `status` says how, `reason` why. Tell the user in one line and end. A
`failed` status is a stopped task: do not restart it by repeating the stage by hand.

## Stopping the task yourself

A bad hand-off twice, a red commit gate: end the task with one
call that marks it stopped and writes its `stage.failed` and `run.finished` events, the
reason on stdin:

```bash
python3 "${HOKO_ROOT}/scripts/task.py" stop --task "<dir>" --reason - <<'REASON'
<one line: why the task stopped>
REASON
```

Then bring the reason to the user and end. A stopped task never runs `finish`.

## What the agents are, and what they hand back

Every agent writes one JSON hand-off into the task folder and returns only its path and a
one-line summary. The state machine reads these, and `record` rejects one that fails its
schema:

| Stage | Agent | Hand-off |
|---|---|---|
| Refine | `hoko-specifier` | `scope.json` |
| Spec | `hoko-spec-writer` | `spec.json` (the spec files themselves live under `specs/`, or `spec.md` in the task folder when `specs` is off) |
| Plan | `hoko-planner` | `plan-01.md`, `plan.json` |
| Implement | `hoko-plan-executor` | its report, then `step-commit.py` |
| QA | `hoko-quality-assurance` | `qa-<NN>.json`, `NN` the cycle |
| Review | `hoko-final-reviewer` | `review-<NN>.json`, the findings array |

A fix cycle gets the next round's `plan-<NN>.md` from the state machine, one step per
finding, and a re-plan after a blocker adds a round to the same cycle; the loop for both
is the same one above. There is no end-of-run spec pass here:
the spec is written before planning, and the reviewer checks the code against it.

Write no hand-off yourself and edit none an agent wrote.

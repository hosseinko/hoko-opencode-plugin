---
description: Execute an approved plan one committed step at a time through the deterministic engine
agent: build
---

<!-- hoko:command -->
# Execute plan

Plan: $ARGUMENTS

Plan mode normally starts this for you: approving a plan there lints it, files it, opens a
fresh session, switches the TUI to it, and hands the filed path straight to this command
on the build agent, so the run carries none of the planning transcript. Running it by hand
is the fallback — a fresh session, or a plan from an earlier day.

## Find the plan

If a path was given and the file exists, use it. A relative path resolves against the
repository root (`git rev-parse --show-toplevel`) before that check. Otherwise — no path,
or a path that is not there — look before you ask:

```bash
python3 "${HOKO_ROOT}/scripts/plan-find.py"
```

It searches this repository's own plans directory first: the newest file there that is not
marked `Status: complete` wins outright, printed as its path, exit 0. Use it.

Only when this repository holds no unfinished plan does it fall through to
`~/.opencode/plan`, shared by every project on this machine, and exit non-zero: each
candidate there is printed with a score — 1 when its `Project:` line matches this
repository's project slug, 0 otherwise.

- Exactly one candidate scores above zero: say which file, its score, then use it.
- Several score above zero: list them with their scores and ask which.
- Every candidate scores zero: say so and ask for a path, rather than picking the newest.
- The script found nothing at all, but this session's earlier messages contain the plan
  text (plan mode could not write it): write it verbatim to
  `~/.opencode/plan/$(date +%Y%m%d%H%M%S)-<short-kebab-slug>.md`, then run the filer below
  on that path. Say that you recovered it from the conversation.
- Nothing at all and no plan in the conversation — ask for a path and stop. Do not invent
  a plan.

## 0. Stabilise the plan file

The path must be stable, `Project:`- and `Journal:`-stamped, and inside the repo. Run:

```bash
python3 "${HOKO_ROOT}/scripts/plan-file.py" file --plan "<absolute plan path>"
```

Use the path it prints from here on — the repository copy. On a plan already filed (the
usual case: approval filed it and this is the same run, just after `/clear`) it prints the
existing repository copy and files nothing new; otherwise it stamps the header, opens the
journal entry and copies the plan in, gitignoring the plans directory unless the repo
already tracks it. If this is not a git repository, ask me which directory is the project
root before doing anything.

Read the whole plan. If **Open questions** contains something that blocks step 1, ask it
and stop. If the open questions only affect later steps, note that and start anyway.

## The ticket

The plan's `Ticket:` line names a key, and that is all it is for here: the branch name.
There is no ticket fetch or edit in this port. Keep the key for *Working branch*.

## The progress checklist and the base

The plan's `## Progress` section is the single source of truth for how far this run has
got, and its header's `Base:` line is the commit the final gate and the review diff from.

```bash
python3 "${HOKO_ROOT}/scripts/plan-progress.py" init --plan "<absolute plan path>"
```

When the plan has no `## Progress` section it adds one directly above `## Steps`, one
unchecked `- [ ] <N>. <title>` box per step, titled from the `### <N>.` headings, and
writes `Base: <HEAD>` into the header. When one already exists it reconciles it instead:
every already-checked box stays checked, a step missing a box gets one, a legacy
`Status: done` line left inside a step's body is dropped and turned into a checked box,
and `Base:` is kept as it was. Already-ticked boxes are work from an earlier run — skip
those steps.

With the checklist settled, lint the plan's structure:

```bash
python3 "${HOKO_ROOT}/scripts/plan-lint.py" --plan "<absolute plan path>" --structural
```

Silent and exit 0: nothing to fix. Otherwise it printed what would have blocked approval,
and approval already settled most of that. The one thing that still stops this run is a
plan whose steps genuinely cannot be worked from: no `## Steps`, no `### <N>.` headings,
or step numbers that are duplicated or gapped. Say so, abort the run (*Stopping the run*)
and stop. Rewriting the plan into the format is a planning session's job, not this one's.
Anything else it printed — an undeclared or double-claimed requirement id, a requirement
with no ` shall ` — mention once in passing and go on to step 1.

## Stopping the run

Every branch below that stops the run — a plan that cannot be worked from, a blocker, a
red gate or commit failure, a `not ready` final gate — ends with one call that marks the
run stopped and writes its `stage.failed` and `run.finished` events:

```bash
python3 "${HOKO_ROOT}/scripts/plan-progress.py" abort --plan "<absolute plan path>" \
  --stage <Implement|QA|Review> --reason - <<'REASON'
<one line: why the run stopped>
REASON
```

`--stage` is `QA` for a `not ready` gate, `Review` when the review itself could not be
run, and `Implement` everywhere else. A branch that stops before there is a plan (no plan
found, a blocking open question you ask and wait on) has nothing to abort.

## Working branch

Before step 1, check the branch this run would commit to: `git branch --show-current`. On
`main`, `master`, `staging` or `develop` no subagent this run launches can fix that from
inside a commit, and `step-commit.py` refuses one. Settle it here, naming the branch by
the *Branch names* rule in the session-start context (`<prefix>/<KEY>-<slug>`), then
`git checkout -b <name>` before going on:

- **`Ticket:` line:** the key is known. Ask me, proposing
  `feature/<KEY>-<slug of the plan title>`.
- **No `Ticket:` line:** ask me for the ticket key or the full branch name. Do not create
  a branch without a ticket key unless I named it that way.

On any other branch nothing changes: stay on it.

## Preflight

Before step 1, run the one gate the conductor runs itself, standalone — everywhere else in
this run, gating a step runs inside `step-commit.py`:

```bash
python3 "${HOKO_ROOT}/scripts/fast-gate.py"
```

If it exits non-zero, the project was already red (or unchecked) before this run touched
anything — show me the failing output and ask whether to continue rather than stopping
outright: a pre-existing failure unrelated to this plan is often fine to run alongside,
and only I can say.

Then mirror the checklist into the session todo list when this build exposes `todowrite`:
one entry per unticked step, `<N>. <title>`, all `pending`. If it does not, skip the
mirror without comment — the `## Progress` checklist and the one-line step reports are the
record. A tick in the todo list is never the record of a finished step.

## Division of labour

You are the conductor. You write no implementation code and review no diff —
`hoko-plan-executor` owns the implementation of a whole step, launched directly by you. You
do not gate, stage or commit by hand either: `step-commit.py` runs the fast gate, commits
and ticks the plan's checklist in one enforced call, so "gate before commit, tick after
commit" holds in code rather than in what you remember to do.

Concretely: you do not modify a source file by any means — not `write`, `edit` or `patch`,
not `sed -i`, shell redirection, a heredoc piped into an interpreter, `patch`. Those calls
belong to `hoko-plan-executor`. You do not run `git add`, `git commit` or
`plan-progress.py tick` yourself either; `step-commit.py` is the only route to any of
those inside the loop. The plugin's loop guard enforces that while the run is
`in_progress`; if it denies a call, that is not a retry signal — you skipped the
delegation.

You may write the plan file itself: its `## Progress` checklist, its `Status:`, and a note
on why a finding does not apply.

Keep your own context small. Do not paste the subagent's report back to me verbatim, and do
not re-derive what the plan already states.

## The loop

Work the unticked steps in checklist order, one step per cycle. Each numbered stage below
is one message.

1. **Slice and delegate**, in one message. Mark the step started, then cut it out of the
   plan:

   ```bash
   python3 "${HOKO_ROOT}/scripts/plan-progress.py" start --plan "<absolute plan path>" --step <N>
   python3 "${HOKO_ROOT}/scripts/plan-slice.py" --plan "<absolute plan path>" --step <N>
   ```

   `start` prints nothing and sets the step `in_progress`; a failed write is a note on
   stderr, never a stop. `plan-slice.py` prints the slice path. Slice per step, here in
   the loop, not all of them up front. If it exits non-zero it has told you which heading
   it could not find: hand `hoko-plan-executor` the plan path instead, say in one clause
   that you did and why, and carry on. Do not repair the slice by hand.

   Mark that step's todo `in_progress` in the same message — exactly one todo is
   `in_progress` at a time — then launch `hoko-plan-executor` with the `subagent` tool:
   `agent` `hoko-plan-executor`, `description` `Step <N>`, and a prompt carrying the slice
   path (or the plan path), the step number and the plan's absolute path:

   > Implement step `<N>` of the plan at `<absolute plan path>`. Everything you need is in
   > `<absolute slice path>` — read it first, then implement and test only that step. Do
   > not commit and do not edit that file or the plan it names.

2. **Turn the report into a commit**, once `hoko-plan-executor` returns. Trust its
   report over anything else — do not re-run `git status` or the gate yourself.

   - **Blocker** — abort the run, then stop and bring it to me rather than re-delegating
     the same step hoping for a better result. One exception: if the blocker is an
     external unknown — a library behaving unlike the plan assumed, an API contract nobody
     checked — launch the `hoko-researcher` subagent with that question first, then bring
     me its finding along with the blocker.
   - **Nothing needed changing** — a verification-only step, or one already satisfied by
     earlier work — run:

     ```bash
     python3 "${HOKO_ROOT}/scripts/step-commit.py" --plan "<absolute plan path>" \
       --step <N> --no-op "<the executor's own reason>"
     ```

   - **Otherwise**, write the commit message yourself from the step's own text in the plan
     and the executor's *What you did* — `hoko-commit`'s *Commit messages* format in one
     short paragraph: a plain, why-focused summary line ending in a full stop, a blank
     line, then one `* `-bulleted, imperative sentence per change, each ending in a full
     stop. No ticket key on its own — `step-commit.py` adds that from the branch name.
     Then run:

     ```bash
     python3 "${HOKO_ROOT}/scripts/step-commit.py" --plan "<absolute plan path>" \
       --step <N> --message-file - <<'MSG'
     <the commit message, verbatim>
     MSG
     ```

3. **Handle the exit code.** `step-commit.py` already ran the fast gate, staged and
   committed (or ticked a no-op) and printed what it saw at each stage.

   - **0** — mark the todo `completed` and report one line: step done, commit subject or
     no-op reason, gate result.
   - **5** — the message broke the mechanical format; fix it from the rules it printed and
     rerun the same command.
   - **1, 3, 4 or 6** — a blocker. Bring me the script's own output rather than retrying
     blind: 1 is a red gate, 3 a protected branch, 4 a tree/mode mismatch, 6 a failed
     `git commit`. None of these tick the step. Abort the run before you stop.

   The tick lands only inside `step-commit.py`, on exit 0, so a step you had to stop on
   stays unticked. Then move to the next step.

## The final gate

When every box is ticked — and only then — the full quality gate runs once, over the whole
run:

```bash
BASE="$(sed -n 's/^Base: //p' "<absolute plan path>" | head -1)"
```

Launch the `hoko-quality-assurance` subagent with the absolute plan path and `<Base>..HEAD`.
It runs lint, static analysis and the full suite with coverage, fixes what it can, commits
those fixes, and reports every gate, every fix and every blocker. Do not run the gate
yourself and do not invoke `hoko-quality-assurance` as a skill here.

If the plan carried no `Base:` line — no commit existed when it was filed — take the
commit the run started from instead (`git rev-parse HEAD` before step 1, or the parent of
the run's first commit) and say which you used.

If it comes back `not ready`, the run is not finished: the plan file does not get
`Status: complete`. Abort the run with `--stage QA`, bring me the blockers and stop.

`green` and `green with debt` both count as green. `green with debt` means only CRAP or
mutation findings remain: the run warns and goes on, and keeps the **Debt:** line for the
closing report's `**QA debt:**` line. Debt never stops the run.

## Update the specs

With the gate green, run the spec pass before the review:

```bash
python3 "${HOKO_ROOT}/scripts/settings.py" specs
```

On `false`, skip this section: no subagent, and the closing report's `**Specs:**` line is
`off`. On `true`, launch the `hoko-spec-writer` subagent with the absolute plan path and
the same `<Base>..HEAD` range. When the plan has a `Spec:` line, the spec was written up
front, so the pass reconciles it with the code; a plan without one has the pass derive the
requirements of each behaviour the run touched. It commits as one commit, separate from
every step commit, and writes nothing when the diff touches no behaviour. Keep its report
for the closing report's `**Specs:**` line. Write no spec yourself, and fold the pass into
no step commit.

## The strict review

With the specs done, run the one strict review the whole diff gets, over the same range.
Name the findings file under the plans directory, in the gitignored `.slices/` folder:

```bash
BASE="$(sed -n 's/^Base: //p' "<absolute plan path>" | head -1)"
FINDINGS="$(dirname "<absolute plan path>")/.slices/$(basename "<absolute plan path>" .md).review.json"
```

Launch the `hoko-final-reviewer` subagent with the absolute plan path, `<Base>..HEAD` and
`$FINDINGS`, and tell it to check the spec's requirements against the code when the spec
pass ran. It reviews by `hoko-code-review`, fixes nothing, commits nothing, and writes its
findings JSON array to that path.

When that array is non-empty, render it into a follow-up plan:

```bash
python3 "${HOKO_ROOT}/scripts/review-findings.py" --from "$FINDINGS" \
  --root "$(git rev-parse --show-toplevel)" --plan "<absolute plan path>"
```

A findings file that is missing means the review did not run: abort with `--stage Review`
and bring me its report.

`--plan` chains the follow-up into this run's own journal round. Tell me the follow-up
plan's path and that it needs a fresh run — never start fixing its findings in this
session. A non-empty findings array does not block `Status: complete`. An empty array needs
no follow-up plan; say the review came back clean.

## The pull request

With the gate green and the review clean, the branch is finished but not integrated.
Invoke the `hoko-pull-request` skill and follow it: it checks whether `origin` is GitHub
and, if it is, pushes the branch and opens a PR against the integration branch —
`HOKO_BASE_BRANCH`, or the remote's own default branch when that is unset. On any other
remote, or none at all, it leaves the branch where it is and says so, which is a normal
ending. A review that found anything never reaches this section: report the follow-up plan
instead and open no PR.

Never integrate the branch yourself, here or anywhere else: no `git merge` into the base
branch, no `gh pr merge`, no auto-merge. A PR that could not be opened is not a blocker —
the work is committed and gated, so report what stopped it and finish the run.

## Closing the run

Check that no todo is left `pending` or `in_progress`, then compose the closing report in
this shape and nothing else, no prose paragraphs, no restatement of the plan:

```
**Outcome:** <one line: done / stopped at step N and why>
**Branch:** <name>
**Commits:** - `<sha>` <subject>   (one per commit, QA and spec fixes included)
**Gate:** lint <pass/fail> · analyse <pass/fail> · tests <pass/fail>, coverage <n>% (<up/down/flat>)
**QA debt:** none | <findings file paths, one per check> — want me to plan the fix?
**Specs:** <spec files and requirement ids touched> | no behaviour touched | off
**Review:** clean | <n> findings (<counts by severity>) → <follow-up plan path>
## Open items
- [ ] … | _none_
```

Where the plan has steps marked `- Irreversible: <text>`, list each under `## Open items`
as its own box with that text, so the human reviewing before merge sees what a revert
cannot undo.

Then set `Status: complete` in the plan's header and post the report above as the last
thing you say in this run. That message is the report: the plugin sees the status, files
the report as this round's report, collects the run's usage and writes the invoice. Do not
run `plan-progress.py complete`, `journal.py` or `invoice.py` yourself, and add nothing
after the report.

A run that stopped short never sets `Status: complete`, so nothing is filed and nothing is
invoiced; the branch stays as the step commits left it.

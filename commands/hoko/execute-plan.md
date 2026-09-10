---
description: Execute an approved plan one reviewed, committed step at a time
agent: build
---

<!-- hoko:command -->
# Execute plan

Plan: $ARGUMENTS

Plan mode normally starts this for you: approving a plan there hands the path straight to
this command on the build agent. Running it by hand is the fallback — a fresh session, or
a plan from an earlier day.

## Find the plan

If a path was given and the file exists, use it. Otherwise — no path, or a path that is
not there — look before you ask:

```bash
PLANS="${HOKO_PLANS_DIR:-.ai/plans}"
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
ls -t "$ROOT/$PLANS"/*.md "$ROOT"/.ai/plans/*.md "$ROOT"/.opencode/plans/*.md "$ROOT"/.claude/plans/*.md 2>/dev/null
```

- Exactly one candidate, or one clearly newest and not yet `Status: complete` — say which
  file you picked and its timestamp, then use it.
- Several plausible ones — list them newest first and ask which.
- **Nothing at all, but this session's earlier messages contain the plan text** (plan
  mode could not write it): write it to
  `$ROOT/$PLANS/$(date +%Y%m%d%H%M%S)-<short-kebab-slug>.md` yourself, verbatim, then
  execute that file. Say that you recovered it from the conversation.
- Nothing at all and no plan in the conversation — ask for a path and stop. Never invent
  a plan.

## 0. Stabilise the plan file

The executor subagent reads this file directly and cannot see this conversation, so
the path must be stable and inside the repo. Run:

```bash
PLANS="${HOKO_PLANS_DIR:-.ai/plans}"
TOP="${PLANS%%/*}"
ROOT="$(git rev-parse --show-toplevel)" || exit 1
mkdir -p "$ROOT/$PLANS"
if git -C "$ROOT" ls-files --error-unmatch "$TOP" >/dev/null 2>&1; then
  : # repo tracks it — the plan is reviewed source, commit it with the work
else
  grep -qxF "/$TOP/" "$ROOT/.gitignore" 2>/dev/null || printf '/%s/\n' "$TOP" >> "$ROOT/.gitignore"
fi
```

If the plan file is not already under `$ROOT/$PLANS/`, copy it there as
`$(date +%Y%m%d%H%M%S)-<short-kebab-slug>.md` and use the copy from here on. Print the
path you settled on. If this is not a git repository, ask me which directory is the
project root before doing anything.

Read the whole plan. If **Open questions** contains something that blocks step 1, ask
it and stop. If the open questions only affect later steps, note that and start anyway.

## The progress checklist

The plan's `## Progress` section is the single source of truth for how far this run
has got, so it survives a compaction or a session restart. Before starting:

- If the plan has no `## Progress` section, add one directly above `## Steps` with an
  unchecked `- [ ] <N>. <title>` line per step, in plan order, titles copied from the
  `### <N>.` headings.
- If it has one, reconcile it: every step must appear exactly once. If a step also
  carries a legacy `Status: done` line, tick its box and drop the line.
- Already-ticked boxes are work from an earlier run — leave them ticked and skip those
  steps.

Then mirror the checklist into the session todo list with `todowrite`: one todo per
unticked step, `<N>. <title>`, all `pending`. Keep the two in sync for the rest of the
run — the todo list is what I watch live, the checklist is what survives the session.

## Division of labour

You are the conductor and the reviewer. You do **not** write implementation code here —
the `hoko-plan-executor` subagent does, on a cheaper model, in its own context window.

Concretely: **you must not call `edit`, `write` or `patch` on source files for a step.**
Those calls belong to the subagent. If you find yourself about to make one, you have
skipped the delegation — stop and launch the `task` tool instead. The only files you may
write yourself are the plan file's `## Progress` checklist and a small fix to something
the subagent already produced.

Keep your own context small. Do not read source files the subagent is about to
rewrite, do not paste its report back to me verbatim, and do not re-derive what the
plan already states.

## The loop

Work the unticked steps in checklist order, **one step per cycle**.

1. **State** the step number, title, and what "done" means — one line. Mark that
   step's todo `in_progress` with `todowrite` before you delegate — exactly one todo is
   `in_progress` at a time.

2. **Delegate.** Launch the `hoko-plan-executor` subagent with the `task` tool
   (`subagent_type: hoko-plan-executor`). Its prompt must be self-contained, because
   it starts with an empty context:

   > Implement step `<N>` of the plan at `<absolute plan path>`. Read the whole plan
   > first, then implement and test only that step. Do not commit and do not edit the
   > plan file.

   Add a sentence of context **only** if the plan itself does not carry it — a
   decision we reached in this session that never made it into the file. Do not
   restate the plan; the subagent reads it.

3. **Verify.** When it returns, run `git status --short` and `git diff` yourself.
   Trust the diff, not the subagent's summary of it. Do **not** re-run tests, lint,
   static analysis or coverage here — the reviewer in the next step runs the fast gate,
   and the full gate runs once at the end of the run. Re-running them per step is exactly the
   drag this loop is shaped to avoid.

   Stop and ask me if the subagent reported a blocker, the diff is empty, or the diff
   touches files the step never mentions. Both mean the plan was wrong. Do not
   re-delegate the same prompt hoping for a better result.

   One exception: if the blocker is an external unknown — a library behaving unlike the
   plan assumed, an API contract nobody checked — launch the `hoko-researcher` subagent
   with that question first, then bring me its finding along with the blocker. The
   executor cannot do this itself: subagents cannot launch subagents at opencode's
   default nesting depth.

4. **Review — every step, no exceptions.** This is not a judgement call and you do not
   get to skip it because the diff looks small.

   Read the diff yourself first, so you can weigh what comes back. Then launch the
   `hoko-code-reviewer` subagent (`subagent_type: hoko-code-reviewer`) with the absolute
   plan path, the step number, and the exact diff command to run, for example
   `git diff` or `git diff HEAD~1`. It reads the diff in its own context, reviews it
   with the `hoko-code-review` skill, runs the fast gate — static analysis and the unit
   tests, nothing else — and reports back with both.

   Its fast gate is the step's only verification. A red analyser or a failing unit test
   comes back as a finding and is handled like any other finding; you do not re-run
   either yourself to confirm it.

   Address every finding, or note in the plan why it does not apply. A trivial diff
   comes back as one clean line — that is a normal, common result, and one cheap
   subagent call is the price of never quietly skipping a review.

   Do not invoke `hoko-code-review` yourself in this loop. The `hoko-code-reviewer`
   subagent runs it for you, in its own context — which is the whole point of
   delegating the review rather than doing it here.

   If the step listed a *Risks* mitigation, confirm it is actually present.

   Fix small findings yourself. If a fix is substantial, send it back to the same
   `hoko-plan-executor` task as a follow-up — it still has the full context, so the
   correction happens there instead of being rebuilt here.

5. **Commit.** Invoke the `hoko-commit` skill and follow it, telling it this is a
   plan-run step commit so it holds to the fast gate the reviewer already ran rather
   than starting the full one. One commit per step — never batch steps into one commit. Then tick that step's box in the plan's
   `## Progress` section (`- [ ] 3.` → `- [x] 3.`) and mark its todo `completed`. Tick
   nothing before the commit lands, and never tick a step you had to stop on. If the
   plans directory is gitignored, the plan file is never part of a commit and must never
   be force-added. If the repo tracks it, the plan file is reviewed source and is
   committed along with the step.

6. **Report** one line: step done, commit subject, tests run — and name the subagents you
   launched for it, so a skipped delegation is visible rather than silent. Then move to
   the next step.

## The final gate

When every box is ticked — and only then — the full quality gate runs once, over the
whole run:

Launch the `hoko-quality-assurance` subagent (`subagent_type: hoko-quality-assurance`)
with the absolute plan path and the commit range this run produced, for example
`<first commit>^..HEAD`. It runs lint, static analysis and the full suite with coverage,
fixes what it can, commits those fixes, and reports every gate, every fix and every
blocker.

Do not run the gate yourself and do not invoke `hoko-quality-assurance` as a skill
here — the subagent runs it in its own context, which is the point of delegating it.

If it comes back `not ready`, the run is not finished: the plan file does not get
`Status: complete`. Bring me the blockers and stop.

## The pull request

With the gate green the branch is finished but not integrated. Invoke the
`hoko-pull-request` skill and follow it: it checks whether `origin` is GitHub and, if it
is, pushes the branch and opens a PR against the integration branch — `HOKO_BASE_BRANCH`,
or the remote's own default branch when that is unset. On any other remote, or none at
all, it leaves the branch where it is and says so, which is a normal ending.

Do this before you set `Status: complete`, because the PR body is the closing report you
are about to post: draft the report first, hand it to the skill as the body, then add the
PR URL — or the reason there is none — to the version you actually post.

Never integrate the branch yourself, here or anywhere else in the run: no `git merge`
into the base branch, no `gh pr merge`, no auto-merge. And a PR that could not be opened
is not a blocker — the work is committed and gated, so report what stopped it and finish
the run.

Then set `Status: complete` at the top of the plan file, check that no todo is left
`pending` or `in_progress`, and list the commits you made. The closing report must
carry the final gate verbatim — the three commands and their results, the coverage
number and its direction, one line per fix the QA subagent made with its commit
subject, and the PR URL or the reason there is none — because that report is what gets
journaled. A fix that happened but is not in
the report is a fix nobody will find again.

That report is journaled for you. Setting `Status: complete` is the signal: the plugin
takes the last thing you post in this run and appends it to the journal entry it opened
when the plan was approved. So **the closing report must be the last thing you post** —
finish with it, add nothing after it, and do not write the journal entry or run
`journal.py` yourself.

A run that stopped short never sets `Status: complete`, so nothing is journaled and the
entry stays open until the run actually finishes.

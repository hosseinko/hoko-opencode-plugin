# The workflow

One cycle, one Tab press:

```
Tab → plan                    grill → plan file → "approve?"
you: approved                 hoko_execute: lint → file → fresh session → hand off
build (fresh session)         per step: executor → step-commit.py (gate, commit, tick)
                              → full gate → specs → one review → PR or follow-up plan
                              → Status: complete → report + invoice
```

Commands, all optional entry points:

```
/hoko/plan <request>          the planning protocol, from a command instead of a message
/hoko/execute-plan <path>     run a plan by hand — a fresh session, or an older plan
/hoko/task <request>          run a task through the whole pipeline, refine to review
/hoko/commit                  commit the working tree to the message conventions
/hoko/pr                      open the PR for the current branch
/hoko/research <question>     research an external question, file it under .ai/research/
/grill-me <topic>             get interrogated on anything, no plan required
```

## 1. Planning is what plan mode is

The protocol is the `plan` agent's own prompt (`agents/plan.md`), not something a
command bolts on: Tab into plan mode, type the request, and it grills you one question
at a time (the `grill-me` skill), reads the code, then writes
`<project>/<plans-dir>/<YmdHis>-<slug>.md`, posts the step breakdown and asks you to
approve. Questions and exploration still get plain answers — the protocol starts when
you ask for work. A task too small to plan gets handed back instead of a plan file.

The plan carries a `## Requirements` section: the change's observable behaviour as
numbered `R<N>` lines in EARS form — *While `<state>`, when `<trigger>`, the
`<component>` shall `<response>`* — one behaviour per line. The grilling is shaped to
fill the five EARS buckets, so a failure path nobody asked about shows up as an empty
one rather than as silence. Each step then claims the ids it delivers on a `Satisfies:`
line, and that line is what the executor builds to, what the end-of-run review checks the
branch against — a requirement claimed but not delivered is a finding that defers the
PR, as is behaviour no requirement asks for — and what the final gate reports coverage
against. A change with no observable behaviour, a rename or a pure refactor, states no
requirements and says so.

Before posting, the plan agent lints the file with `plan-lint.py --plan`: a numbered
`## Steps` list is rewritten into `### <N>. <title>` headings in place, and the checks
that a machine can make are reported — a step-number gap or duplicate, a `Satisfies:` id
that is undeclared or claimed twice, a requirement without ` shall `. The plan agent has
that one command pre-allowed so the check never stalls on a prompt.

The plan agent writes that file through one permission exception the plugin adds: `edit`
is denied except the plans directory (spelled relative, `*/`-prefixed and `**/`-prefixed,
since opencode does not document which form the matcher sees), and `date`, `mkdir -p`,
`git rev-parse`, `ls` and `test -f` are pre-allowed so resolving the path never stalls on
a prompt. The prompt comes from `agents/plan.md`, installed into
`~/.config/opencode/agents/`; the plugin only layers the permissions on.

## 2. Approval is linted, filed, and handed off

Say "approved" — or "go ahead", or anything that means yes — and the plan agent calls
the `hoko_execute` tool. That tool, not the model, does the switching:

1. lints the plan with `plan-lint.py --plan --structural` and refuses a blocking finding
   before anything is filed. `--structural` skips the `## Progress` check because filing
   generates that section next; everything else that would block approval still does.
   A refused plan names the finding, creates no session and says nothing was filed;
2. creates a new opencode session for the run, titled from the plan's `#` heading (or the
   plan's filename when it has none), on the `build` agent — the planning session keeps
   its transcript and is left untouched;
3. files the plan with `scripts/plan-file.py file`: it renames a plan that lives outside
   the plans directory to `<stamp>-<slug>.md`, stamps `Project:` and, when journaling is
   on, `Journal:`, copies the plan in, generates its `## Progress` checklist and writes
   the run's `Base:` sha, and registers the approving session as round 1, role `plan`;
4. queues the plan on the approval session, and when that turn ends runs
   `/hoko/execute-plan <path>` in the fresh session on the `build` agent.

The run's context is the plan file and nothing else — none of the planning transcript
rides along. So there is no Tab-to-build step and no command to remember, and build never
starts from a blank slate: it starts inside the execute-plan protocol with the plan path
in hand. The server plugin cannot move the screen itself, so `plugin/tui.ts` navigates
the current view to the new session's `hoko: run` marker. The run appears in the tab the
approval already occupies, and only the run's root session is followed: a descendant
inherits the marker, and a `parentID` check keeps each executor, reviewer and QA
subagent out of the tab bar.

`HOKO_FRESH_SESSION=0` — or `false`, `no`, `off` — skips the new session and queues the
handoff on the approval session, so the plan runs there as before. When creating the
session fails, the tool refuses before anything is filed or queued, and the failure
comes back in the tool result for the plan agent to report, naming
`HOKO_FRESH_SESSION=0` and the manual `/hoko/execute-plan <path>` as the ways out.

In fresh mode the run starts in a session the plugin created, not the planning session, so
it no longer inherits the planning session's model. `HOKO_BUILD_MODEL` is what pins the
conductor, which is worth doing either way — the model a run otherwise lands on is not
always the one you want conducting every step. It sets the `build` agent's model like the
other variables set theirs, so it applies to plain build-mode chat too.

Ask for changes instead of approving and the plan file is edited in place at the same
path — nothing is filed until you approve.

If you run opencode with `OPENCODE_EXPERIMENTAL_PLAN_MODE=1`, ignore its `plan_exit`
tool: that approves opencode's own plan workflow, which implements inline. The prompt
says so too.

## 3. Execution is one deterministic loop

`/hoko/execute-plan` runs on `build` and is a conductor, not an implementer. The engine
does the parts a model should not be trusted to remember:

1. **Init and base.** `plan-progress.py init` reconciles `## Progress` against the
   `### <N>.` headings — every ticked box from an earlier run stays ticked, a missing box
   is added — and writes `Base: <HEAD>` into the header once. The linter then runs in
   `--structural` mode: only an unworkable plan (no steps, gapped or duplicate numbers)
   stops the run.
2. **Preflight.** `fast-gate.py` runs once, so a project that was already red is shown to
   you before the run touches anything. It exits 2 when neither an analyser nor a test
   command resolves — nothing was checked, and that is reported as `unchecked` rather
   than passing quietly.
3. **Per step.** `plan-progress.py start` marks the step `in_progress`, gives the run its
   id and first event on first use, and appends one `stage.started`. `plan-slice.py` cuts
   that step out of the plan, and the conductor launches `hoko-plan-executor` on the slice
   with its own context. On return,
   `step-commit.py` is the only way the step lands: it runs the fast gate (the project's
   static analyser and unit tests), validates the commit message's mechanical shape,
   stages every change, commits, ticks the checklist box with the commit sha or the no-op
   reason, and appends the gate's `check.result` and the step's `stage.completed` events.
   It refuses a protected branch, a tree that does not match what the step produced, and a
   malformed message, and the step stays unticked. When the branch name carries a ticket
   key, the commit message ends with it.
4. **The closing pass.** With every box ticked, `hoko-quality-assurance` runs the full
   gate once — lint, static analysis, the full suite with coverage, then CRAP and mutation
   — fixes what it can and commits those fixes. With `specs` on, `hoko-spec-writer`
   reconciles the spec, and one `hoko-final-reviewer` reviews the whole `<Base>..HEAD`
   range against the plan's requirements. Findings become a follow-up plan through
   `review-findings.py` and the PR is deferred to that plan's run; a clean review invokes
   `hoko-pull-request`, which pushes and opens a PR on GitHub and leaves the branch alone
   on any other remote. Nothing merges: no `git merge`, no `gh pr merge`, no auto-merge.
5. **Closing.** The conductor sets `Status: complete` and posts the closing report as the
   last thing it says. On the turn's end the plugin collects the run's usage and the model
   catalog's rates into `usage.json` and `rates.json`, then calls
   `plan-progress.py complete`, which sets the status, files the report and renders the
   invoice in one command. A run that stopped short never sets the status, so nothing is
   filed and nothing is invoiced.

The gate scripts assume no toolchain. `scripts/commands.py --root <repo>` resolves each
gate from, in order, a `Makefile`/`justfile`/`Taskfile.yml` target, the manifest's script
block, a CI `run:` line, then the ecosystem default when the tool is present, and says
which command it settled on. PHP commands are wrapped to run in the project's container,
never against host PHP. `fast-gate.py` runs the analyser and unit tests; the full gate in
`hoko-quality-assurance` runs all of it, with CRAP and mutation held to `crapMax` and
`mutationMin`.

While the run is `in_progress` the loop guard denies the conductor any `read`, `edit`,
`write` or `patch` inside the repository outside the plans directory, and keeps the
plugin's own `scripts/`, `agents/`, `commands/` and `skills/` reachable so the engine can
be called. A `hoko-*` subagent is never restricted, and neither is a shell call or a path
outside the repository. A denied call is not a retry signal: it means a step's work was
about to be done in the conductor's own context.

Every run writes its events to `.ai/runs/<run_id>/events.jsonl`: one JSON object per line
with the schema version, run id, a gap-free `seq` assigned under a file lock, timestamp,
type and payload. The event directory gitignores itself before the first run, so
`git add -A` never stages an event. `HOKO_EVENTS=0` writes none; a write that fails
disables events for that run, prints the reason once, and changes no command's exit
status.

## 4. `/hoko/task` runs a whole task

`/hoko/task <request>` is the second front door. It runs on `build` and follows the
`hoko-task` skill, which is a thin conductor around `scripts/task.py`: the state machine
in the script holds the stage order, the skip rules, the cycle count, the loop limit and
the spec hand-back, and the conductor does what `task.py next` prints. It never decides
the flow, and it writes no implementation code.

```
Refine → Spec → Plan → [plan gate] → Implement → QA → Review → next cycle | finish
```

- **Stages.** `hoko-specifier` refines the prompt into `scope.json`; `hoko-spec-writer`
  writes the spec when one is needed; `hoko-planner` writes `plan-01.md` and `plan.json`;
  `hoko-plan-executor` implements one step at a time through the same `step-commit.py`;
  `hoko-quality-assurance` gates the cycle; `hoko-final-reviewer` reviews it. Each stage
  writes one JSON hand-off into the task folder and returns its path, and
  `task.py record` validates it before changing anything.
- **The loop.** A QA `not ready` or review findings open the next cycle, with the
  findings rendered as `plan-<NN>.md`. After `1 + loopLimit` cycles the pipeline stops and
  asks Continue / Accept / Stop; `loopLimit` 0 accepts the open findings without asking and
  files them as a follow-up plan that is not run.
- **The plan gate.** By default a task's plan is put to you as Approve / Revise / Stop
  before a step runs, after the plan hand-off is recorded. Revise sends the planner back to
  the same file with your words.
- **Asks.** Only product decisions interrupt the run: an agent hand-off with
  `needs_input`, a red preflight gate, the plan gate, a loop limit, or a product blocker.
  The answers are stored in `answers.json` and the same child session is resumed with
  `--agent-session` / `resume`; `--resume-failed` returns a fresh spawn instead.
- **Blockers.** An implementer's blocker is routed by kind: `spec` back to the spec
  writer and then a replan, `plan` to a replan, `external` to `hoko-researcher`, `product`
  to you.
- **The folder.** `task.py start` makes `.ai/plans/<YYYYmmdd-HHMM>-<slug>/`, keeps the
  prompt as `prompt.md`, writes `progress.json` and the first run event, and prints the
  folder, run id and journal entry as JSON. `finish` writes `report.md`, closes the events
  and files the report; `stop` marks the task failed and writes its failure events. A task
  can start from a prompt, from a spec file, or from an existing plan.

`/hoko/task` is the pipeline to reach for when there is no plan yet, or when one task
should run through to a reviewed branch on its own.

## 5. The run is visible while it runs

`plugin/tui.ts` registers three slots from `plugin/status.tsx` and keeps them refreshed
on the session's own events plus a two-second tick:

- the status line, appended to both `prompt.footer.status` and `home.footer.status`, reads
  `hoko · <project>@<branch> · <stage> <n>/<total> · cycle <c>`. The `<n>/<total>` part is
  the current round's step progress, so it appears during Implement and is left out while
  a task is still refining, specifying or planning;
- the pane, appended to `sidebar.content`, lists the run's title and repo, the stage and
  `cycle <c>/<1 + loopLimit>`, every stage with its status, the current round's steps with
  their commit sha and any blocker, and the agents currently working in the session's
  family (at most eight, so the steps stay in view);
- with no run in progress the line reads `hoko · <project>@<branch>` and no pane is
  drawn. A detached `HEAD` shows the short sha instead of a branch name.

The reader (`plugin/status.ts`) takes the newest `progress.json` under `plansDir` — a
task folder's own file or a flat plan's `<stem>.progress.json` — and only shows it while
it reports `in_progress`. Nothing in the display writes, and the branch is read out of
`.git/HEAD` rather than by spawning git, so a refresh is a handful of file reads. The
status line is worth more than the pane, which the sidebar may be hiding; the plan file
and its `progress.json` remain the durable record either way.

## 6. The journal, the analytics folder and the invoice

**Journaling is off unless you set `HOKO_JOURNAL_PATH`.** With a root configured, each
cycle is a folder `<journal>/<project>/<stamp>-<slug>/` holding `prompt.md`, `plan-01.md`,
`report-NN.md` and, for a task, the round's `plan-NN.md` files.

- The plugin captures the first prompt of each cycle verbatim, before any model sees it,
  and retires it once filed so the next cycle captures its own.
- `hoko_execute` files the entry at approval through `plan-file.py file`. No model
  composes it. The approving session is registered as round 1, role `plan`; the run's
  session, when it is a fresh one, as round 1, role `execute`. Each
  `(session, round, role)` appears once, stamped with its registration time.
- A plan run closes through `plan-progress.py complete`: it reads the run's `Journal:`
  line, writes the last thing the conductor posted as `report-NN.md` beside `plan-NN.md`,
  and renders the invoice. A `/hoko/task` run closes through `task.py finish`, which files
  its report the same way; when the task reports `done`, the plugin then writes
  `usage.json` and re-renders that entry's invoice, because only it can read the run's
  sessions.
- `usage.json` is the plugin's job, because only it can read a session's messages: every
  assistant response of every registered session and its descendants, with its tokens and
  the cost opencode reported. `rates.json` snapshots the model catalog's rates at
  completion. Both are written before the run is closed.

**`analyticsPath` moves the numbers out of the notes vault.** Set
`HOKO_ANALYTICS_PATH` (or `"analyticsPath"` in `hoko.json`) and the run's
`sessions.json`, `invoice.json`, `invoice.md` and `events-<NN>.jsonl` copies live in
`<analyticsPath>/<project>/<entry>/`, where `<project>` and `<entry>` are the journal
entry's own folder names. That folder also gets `entry.json`, the link back: the journal
entry's absolute path, the run ids that completed against it and its registered session
ids. With `analyticsPath` empty everything stays in the journal entry; with it set,
`usage.json` and `rates.json` are the two files that stay behind, beside the report they
priced.

The invoice lists, per model, the input, output, reasoning, cache-read and cache-write
tokens and their cost; per round, role and agent type (a registered session's own loop is
`main`), billing each response to the row registered latest at or before its timestamp;
and the rates behind them. Cost is opencode's own reported per-message cost
(`cost_source: reported`) — a notional cost for the work done, not your subscription bill.
A response with no reported cost is priced from `rates.json`, then `scripts/pricing.json`
with the `pricing` setting laid over it. The rates a round and model were first priced at
are stored, so a later price change never reprices a past round; a model with no rate at
all is named in the footer, as is a registered session that reported no responses.

Entry titles and filenames come from the plan's own `#` heading, or failing that the
first line of its `## Goal` — never from the plan's auto-generated filename. The project
is the git root, or the nearest ancestor with a `.git`, `.ai`, `.opencode` or `.claude`;
the home directory never counts, and an unresolvable project lands in
`<journal>/unsorted/`.

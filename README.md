# hoko — a plan-and-execute workflow for opencode

Plan mode grills you, writes the plan to a file, and hands it to a build run that
implements it one gated, committed step at a time. Every step gets a fast gate; once the
whole run passes the full quality gate, one deep code review covers the branch, and only
a clean verdict opens a pull request. Nothing merges.

Everything lives under the **`hoko`** namespace — commands are `/hoko/…`, agents and
skills are `hoko-…` — except `grill-me`, which keeps its bare name, and `plan`, which
deliberately replaces opencode's own plan agent.

It is stack-agnostic: the gates are expressed as *lint → static analysis → tests with
coverage* and each agent finds the project's own commands rather than assuming tool
names. Optional skills carry stack conventions — PHP, TypeScript/React, and Go — and
trigger only on a diff in that stack.

## Install

### What it needs

| | |
| --- | --- |
| opencode | 2.0 or newer — `opencode --version`. On V1 see [Migration from V1](#migration-from-v1) |
| python3 | only for the journal and its token invoice, and only if you enable it — `python3 --version` |
| git | plan runs commit each step |
| node modules | **none.** `plugin/hoko.ts` uses node's standard library only |

There is nothing to build and no dependency to install. The plugin has no dependencies on
purpose — that is why its tool takes no arguments, since declaring arguments would mean
importing zod, and importing zod would mean an install step.

One thing V2 changed: a plugin can no longer register agents, and there is no TUI API. So
this repo's `agents/*.md` are installed as files (step 3) and the toast and the jump to
the run's session are gone. Everything else — commands, skills, the standing instructions
— is registered by the plugin as before.

### 1. Put the repo somewhere stable

opencode loads the plugin from an absolute path, so pick a home for this checkout and
leave it there:

```sh
git clone https://github.com/<you>/hoko-opencode-plugin.git
cd hoko-opencode-plugin && pwd
```

Keep that path — step 2 needs it.

### 2. Point opencode at the plugin

opencode has no plugin marketplace, and agents and commands are only discovered inside
`~/.config/opencode/` or a project's `.opencode/`. So the repo registers itself: one
line in `~/.config/opencode/opencode.json` and the plugin injects its commands, skills
and standing instructions into the live config at startup. `opencode.json.example` is
that file:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "plugins": ["file:///ABSOLUTE/PATH/TO/hoko-opencode-plugin/plugin"]
}
```

Replace the placeholder with the path from step 1. It must be a `file://` URL with an
absolute path, and it must point at the **`plugin` directory**, not at `plugin/hoko.ts`:
V2 loads a path entry as a directory and imports its `index.ts`, and a path to a file is
rejected with `configured plugin path must be a directory`. If
`~/.config/opencode/opencode.json` already exists, add the entry to the `plugins` array
you have rather than replacing the file.

```sh
cp opencode.json.example ~/.config/opencode/opencode.json   # only if you have none
```

The `plugin` entry names the checkout opencode loads everything from — not just
`plugin/hoko.ts`, but the commands, skills and instructions it injects. An edit made in a
different clone, or a copy installed elsewhere, has no effect until this path points at
that checkout and opencode reloads.

### 3. Install the agents

V2 fixed the plugin API against adding agents, so the plugin cannot register the ones
this repo ships. They are discovered from `~/.config/opencode/agents/` instead:

```sh
scripts/install-agents.sh
```

That symlinks every `agents/*.md` into `~/.config/opencode/agents/`, so editing one here
stays live. Re-running is safe, and a real file already sitting at a target path is left
alone and reported rather than overwritten. To undo, delete the symlinks.

### 4. Configure it (optional)

```sh
cp hoko.env.example ~/.config/opencode/hoko.env
```

Uncomment what you want — the table under [Configuration](#configuration) says what each
variable does. Everything has a working default: leave the file untouched and every
agent runs on the session's model, plans go to `.ai/plans/`, the coverage floor is 85%, a
PR targets `develop` where the repository has one, and nothing is journaled.

Keeping the file at `~/.config/opencode/hoko.env` rather than in the repo means a
`git pull` never touches your settings.

### 5. Reload opencode

V2 watches its config directories and reloads them, so a change to `opencode.json`, to
`hoko.env`, or to a file that was already mounted usually lands on its own; `opencode
reload` forces it. A change to the *set* of plugins, or to the plugin's own source, may
need `opencode service restart`.

### 6. Check it took

```sh
opencode debug agents        # the hoko- agents and the patched plan agent
opencode debug config        # every configuration source, and the plugin entry
```

`opencode debug agents` is where the workflow lives or dies. Find `plan` in the list and
check three things:

- its **system** prompt is the planning protocol (it mentions `grill-me` and
  `hoko_execute`), not opencode's stock plan prompt;
- the **permission** list denies `edit` on `*` and allows it on `.ai/plans/*.md` — that
  one exception is how a plan becomes a file;
- it may call `hoko_execute`.

The `hoko-` subagents should be listed too. If they are not, step 3 did not run.

### 7. Smoke-test it

In any git repo:

```
Tab → Plan
"add a --verbose flag to the CLI entrypoint"
```

You should get grilled one question at a time, then a plan path under `.ai/plans/`, then
a request to approve. Say **approved** and watch for the run starting at step 1 with a
`hoko-plan-executor` subagent. Two things V2 took away: no toast names the plan, and the
TUI does not follow the run into its fresh session — the run still starts there, the
screen just stays on the planning session.

To undo all of this, delete the plugin entry from `opencode.json`, delete the symlinks
step 3 made, and reload.

### Updating

Pull (or edit) and reload opencode. That is the whole procedure: nothing is copied,
compiled or installed, so the files in this repo *are* the live workflow — the plugin is
loaded from `plugin/`, and the agents are symlinks into `agents/`. Editing any of them
changes it everywhere on the next reload. A syntax error in `plugin/hoko.ts` takes the
whole thing down, so run the tests after touching it.

### When something is off

| Symptom | What it means |
| --- | --- |
| Log says `configured plugin path must be a directory` | The `plugins` entry points at `plugin/hoko.ts`. V2 a path entry loads as a directory — point it at `.../hoko-opencode-plugin/plugin`. |
| No `/hoko` commands, no `hoko-` agents | The plugin never loaded. Check the entry in `opencode.json` is an absolute `file://` URL to the `plugin` directory, then `opencode service restart`. |
| Plan mode answers like stock opencode | The `plan` agent is not installed — run `scripts/install-agents.sh` and reload. |
| The plan arrives in the chat, not as a file | The edit exception is not reaching the plans directory — check the permission list in `opencode debug agents`. The agent says so itself rather than losing the plan. |
| "approved" produces a reply but no run | The plan agent did not call `hoko_execute`, or the tool is not permitted. Check the permission list in `opencode debug agents`; if there is no plan *file* in the session, the tool refuses by design. |
| The handoff produces a session with no run | Run `/hoko/execute-plan <path>` yourself and check the opencode log — V2 has no toast, so a failed handoff is written there. |
| The screen stays on Plan after approval | Expected. V2 exposes no TUI API, so the plugin cannot move the TUI to the run's session. The run is on build either way. |
| No journal entry | Expected unless `HOKO_JOURNAL_PATH` is set — journaling is off by default. With it set: `python3` missing, or the root is not writable. `hoko_execute` reports the reason in its output instead of failing silently. |
| Entry has no `report-NN.md` | The run never set `Status: complete` — a blocker or a `not ready` gate — or the closing report was not the last thing posted. |
| Plans land in `.claude/plans/` | Stale Claude Code skills are being picked up — see [Claude Code interference](#claude-code-interference). |
| A gate subagent says it could not run a check | Its bash allowlist does not cover your project's command. Add the pattern to `agents/hoko-step-gate.md`, or `agents/hoko-code-reviewer-deep.md` for the end-of-run review. |

## Migration from V1

V2 has three intentional breaking changes, and one of them is the plugin API: **a V1
plugin does not run in V2.** The plugin here has been ported; the file paths, the agent
and command frontmatter and the skills are unchanged. What you have to do by hand:

1. **Re-point the plugin.** The `plugin` key becomes `plugins`, and the value becomes the
   `plugin` *directory* rather than `plugin/hoko.ts`. See [step 2](#2-point-opencode-at-the-plugin).
2. **Install the agents.** A V2 plugin cannot add agents, so `agents/*.md` are discovered
   from `~/.config/opencode/agents/`. Run `scripts/install-agents.sh`. This is the step
   V1 did not have.
3. **Reload**, then check `opencode debug agents`.

Behavior that changed, all of it forced by the V2 API:

| V1 | V2 |
| --- | --- |
| The plugin registered the agents | Agents are files under `~/.config/opencode/agents/`, installed by `scripts/install-agents.sh` |
| The plugin appended `instructions/*.md` to the config | The plugin adds them to every model request from the `context` hook — same effect, they are in context on every turn of every agent |
| `tui.showToast` announced the handoff, the journaled report and the invoice | No TUI API. The handoff and journaling lines go to the opencode server log; the git guard's warning arrives as a synthetic notice in the session |
| Approving switched the TUI to the run's fresh session | No TUI API. The run's session is still created and the run still starts there; the screen does not follow it |
| `HOKO_PROMPT_FILE` was exported into every shell | The V2 shell hook carries no session id, so it is gone. Nothing read it |
| The plugin detected a hand-written `plan` block and left its prompt alone | V2 exposes no way to tell a hand-written agent from a generated one, so the exception is always layered on, and a model override only applies to an agent with no model of its own |
| `/hoko/research` ran as a subtask because a command could name a subagent | A command cannot name an agent, and a session cannot run on a subagent-only agent, so the command asks the current agent to delegate to `hoko-researcher` |
| The plan agent's `tools` map was switched on | V2 agents have no `tools` map; tool availability follows permissions |

`plugin/hoko.ts` was rewritten for the V2 API: `setup(ctx)` with `ctx.tool.transform`,
`ctx.tool.hook`, `ctx.shell.hook`, `ctx.session.hook`, `ctx.event.subscribe`,
`ctx.agent.transform`, `ctx.command.transform` and `ctx.skill.transform`. The journaling
scripts, the git guard, the settings loader and the frontmatter parser are unchanged. It
still imports nothing beyond node's standard library.

## Configuration

Copy `hoko.env.example` to `~/.config/opencode/hoko.env` and uncomment what you want.
The plugin reads, in increasing order of precedence: `hoko.env` in this repo,
`~/.config/opencode/hoko.env`, then any `HOKO_*` variable in the real environment.

| Variable | Sets | Default |
| --- | --- | --- |
| `HOKO_PLAN_MODEL` | model for the `plan` agent | the session's model |
| `HOKO_BUILD_MODEL` | model for the `build` agent — the conductor of a plan run | the session's model |
| `HOKO_EXECUTOR_MODEL` | model for `hoko-plan-executor` | the session's model |
| `HOKO_REVIEWER_MODEL` | model for `hoko-code-reviewer` | the session's model |
| `HOKO_REVIEWER_DEEP_MODEL` | model for `hoko-code-reviewer-deep`, the reviewer that runs once at the end of a plan run | the session's model |
| `HOKO_QA_MODEL` | model for `hoko-quality-assurance` | the session's model |
| `HOKO_RESEARCH_MODEL` | model for `hoko-researcher` | the session's model |
| `HOKO_JOURNAL_PATH` | journal root | **unset — journaling is off** |
| `HOKO_PLANS_DIR` | where plans are written, relative to the repo root | `.ai/plans` |
| `HOKO_FRESH_SESSION` | approval starts the run in a fresh session; V2 has no TUI API, so nothing follows it there. `0`, `false`, `no` or `off` hand off in the approval session | on |
| `HOKO_COVERAGE_MIN` | the full gate's coverage floor, in percent | `85` |
| `HOKO_COMMIT_AUTO` | `1` = `hoko-commit` commits without confirming the message | off |
| `HOKO_BASE_BRANCH` | branch playing the `develop` role — what features branch from and target | `develop`, else the remote's default branch |
| `HOKO_PR_AUTO` | `1` = `hoko-pull-request` pushes and opens the PR without confirming | off |

Models are `provider/model-id`; `opencode models` lists them.

The plugin exports all of these, plus `HOKO_ROOT`, into every shell the agent runs —
which is how the skills read the settings that apply to them. V1 also exported
`HOKO_PROMPT_FILE` (this session's captured prompt); V2's shell hook carries no session
id, so it is gone. Nothing else read it.

A model variable only takes effect on an agent that has no model of its own: a `model`
you set yourself in `opencode.json` wins. In V1 the plugin could tell a hand-written agent
block apart from a generated one; in V2 it cannot, so an unset model is the only signal.

### Claude Code interference

V1 shipped around two opencode behaviours that V2 dropped: V2 does not read
`~/.claude/CLAUDE.md`, and it does not read `~/.claude/skills/`. So a leftover Claude Code
copy of a workflow like this one can no longer fight `HOKO_PLANS_DIR` over where plans
live, and the `OPENCODE_DISABLE_CLAUDE_CODE_*` workaround V1 documented is unnecessary.

## The workflow

One cycle, one Tab press:

```
Tab → plan                    grill → plan file → "approve?"
you: approved                 hoko_execute: opens a fresh session, journals, runs execute-plan on build
build (fresh session)         delegate → verify → step-gate → commit, one step per cycle
                              → full gate → deep review → PR or follow-up plan
                              → Status: complete → report + token invoice journaled
```

Commands, all optional entry points:

```
/hoko/plan <request>          the planning protocol, from a command instead of a message
/hoko/execute-plan <path>     run a plan by hand — a fresh session, or an older plan
/hoko/commit                  commit the working tree to the message conventions
/hoko/pr                      open the PR for the current branch
/hoko/research <question>     research an external question, file it under .ai/research/
/grill-me <topic>             get interrogated on anything, no plan required
```

### 1. Planning is what plan mode is

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
against.
A change with no observable behaviour, a rename or a pure refactor, states no
requirements and says so.

The plan agent writes that file through one permission exception the plugin adds: `edit`
is denied except the plans directory (spelled relative, `*/`-prefixed and `**/`-prefixed,
since opencode does not document which form the matcher sees), and `date`, `mkdir -p`,
`git rev-parse`, `ls` and `test -f` are pre-allowed so resolving the path never stalls on
a prompt. The prompt comes from `agents/plan.md`, installed into
`~/.config/opencode/agents/`; the plugin only layers the permissions on.

### 2. Approval hands off by itself

Say "approved" — or "go ahead", or anything that means yes — and the plan agent calls
the `hoko_execute` tool. That tool, not the model, does the switching:

1. creates a new opencode session for the run, titled from the plan's `#` heading (or the
   plan's filename when it has none), on the `build` agent — the planning session keeps
   its transcript and is left untouched;
2. files the plan and this cycle's original prompt in the journal, if journaling is
   configured, then moves the entry it opened and the cycle's other state onto the run's
   session, so the closing report is still filed into the entry opened at approval;
3. queues the plan on the approval session, and when that turn ends runs
   `/hoko/execute-plan <path>` in the fresh session on the `build` agent.

The run's context is the plan file and nothing else — none of the planning transcript
rides along. So there is no Tab-to-build step and no command to remember, and build never
starts from a blank slate: it starts inside the execute-plan protocol with the plan path
in hand. In V1 the prompt box followed the run; V2 exposes no TUI API, so the screen
stays where it was. The run is on the build agent either way — that V1 step was cosmetic.

`HOKO_FRESH_SESSION=0` — or `false`, `no`, `off` — skips the new session and queues the
handoff on the approval session, so the plan runs there as before. When creating the
session fails, the tool refuses before anything is journaled or queued, and the failure
comes back in the tool result for the plan agent to report, naming
`HOKO_FRESH_SESSION=0` and the manual `/hoko/execute-plan <path>` as the ways out.

In fresh mode the run starts in a session the plugin created, not the planning session, so
it no longer inherits the planning session's model. `HOKO_BUILD_MODEL` is what pins the
conductor, which is worth doing either way — the model a run otherwise lands on is not
always the one you want reading every diff. It sets the `build` agent's model like the
other variables set theirs, so it applies to plain build-mode chat too — the conductor and
build mode are the same agent.

Ask for changes instead of approving and the plan file is edited in place at the same
path — nothing is journaled until you approve.

If you run opencode with `OPENCODE_EXPERIMENTAL_PLAN_MODE=1`, ignore its `plan_exit`
tool: that approves opencode's own plan workflow, which implements inline. The prompt
says so too.

### 3. Execution delegates every step

`/hoko/execute-plan` runs on `build` and works the plan one step per cycle: delegate the
step to `hoko-plan-executor` (cheaper model, its own context), read the diff yourself,
run the `hoko-step-gate` subagent over it — every step, unconditionally — then commit
via the `hoko-commit` skill. A red fast gate goes back to the executor and nothing commits
until it is green. One commit per step. With `HOKO_COMMIT_AUTO=1` each of those
commits lands without stopping to confirm the message — the protected-branch check and
the gate still hold. The plan's `## Progress` checklist tracks how far the run got, so it
survives a compaction or a restart.

The gate is split so the loop stays cheap. Per step, `hoko-step-gate` runs the **fast
gate** — the project's static analyser and its unit tests, nothing else — and reports each
command and result; the conductor re-runs nothing. Once every box is ticked, the
`hoko-quality-assurance` subagent runs the **full gate** once over the whole run — lint,
static analysis, the full suite with coverage — fixes what it can, commits those fixes,
and reports each gate and each fix. A `not ready` verdict means the plan file does not
turn `Status: complete`. With the full gate green, `hoko-code-reviewer-deep` reviews the
whole branch once, against the plan's Requirements; only a `clean` verdict opens the pull
request.

The gate subagents assume no toolchain. Each reads the project's manifest scripts,
analyser and test config, and CI workflow to find the commands it actually enforces, and
says which command it settled on so a wrong one is visible. Each runs under its own bash
allowlist covering the common runners across PHP, JS/TS, Python, Go, Rust, JVM, Ruby and
.NET; if yours is missing it says so rather than substituting something else, and each
list is one file to edit.

A green gate is not an integration. Only a `clean` deep review reaches the PR: on any
finding the run writes a follow-up plan instead — the findings restated as Requirements,
with a `## Progress` box per step — sets the plan complete, and stops, so the PR is
deferred to that plan's own run, which repeats the whole flow. When the review is clean,
before the plan file turns complete, the run invokes
`hoko-pull-request`: if `origin` is GitHub it pushes the branch and opens a pull request
against the base the branch prefix calls for — `develop` for `feature/` and `bugfix/`,
the release branch plus a back-merge PR for `hotfix/` and `release/` — with the run's
closing report as the PR body, so the PR and the journal entry say the same thing. On any other remote, or none, the branch is simply left for you to integrate.
Nothing in the workflow merges: no `git merge` into the base branch, no `gh pr merge`, no
auto-merge. Without `HOKO_PR_AUTO=1` the push waits for you to confirm the base, branch
and title; `/hoko/pr` runs the same skill on its own for a branch outside a plan run.

Both protocols delegate outward rather than guessing: when a decision turns on something
outside the repo — what a pinned library version actually does, an API's semantics — they
launch `hoko-researcher` and cite its findings file instead of assuming or asking you to
go looking.

### 4. The journal is written by the tools, not by a reminder

**Off unless you set `HOKO_JOURNAL_PATH`.** With a root configured, each cycle is a folder
`<journal>/<project>/<stamp>-<slug>/` holding `prompt.md`, `plan-01.md`, `report-NN.md`,
`sessions.json`, `usage.json`, `rates.json`, `invoice.json` and `invoice.md`.

- The plugin captures the first prompt of each cycle verbatim, before any model sees it,
  and retires it once filed so the next cycle captures its own.
- `hoko_execute` files the entry at approval. No model composes it — the tool runs
  `scripts/plan-file.py file`, which writes the prompt and the plan, records `Project:`
  and `Journal:` in the plan's header, and registers the approving session in
  `sessions.json` as round 1, role `plan`. When the run starts in a fresh session, the
  run's session is registered as round 1, role `execute`. Each `(session, round, role)`
  appears once, stamped with its registration time, so a restart loses nothing.
- The plan turning `Status: complete` closes it: the plugin takes the last message the
  run posted — by protocol the closing report — and writes it to `report-NN.md` beside
  the entry's `plan-NN.md`, and logs that it did. A run that stopped short never
  sets `Status: complete`, so nothing is filed and the entry stays open. It then
  collects every registered session's assistant responses and those of its descendant
  sessions into `usage.json`, snapshots the model catalog's rates into `rates.json`, and
  renders the token invoice. V2 exposes no way to list sessions, so descendants are
  tracked from the `session.created` events the plugin observes while it is loaded.
- `invoice.json` and `invoice.md` list, per model, the input, output, reasoning,
  cache-read and cache-write tokens and their cost; per round, role and agent type (a
  registered session's own loop is `main`), billing each response to the row registered
  latest at or before its timestamp; and the catalog rates behind them. A registered
  session whose usage cannot be fetched is named in the notes, and the invoice is still
  written.

The invoice's cost is opencode's own reported per-message cost — the catalog rate applied
to the tokens — a notional cost for the work done, not your subscription bill.

Entry titles and filenames come from the plan's own `#` heading, or failing that the
first line of its `## Goal` — never from the plan's auto-generated filename. The project
is the git root, or the nearest ancestor with a `.git`, `.opencode` or `.claude`; the
home directory never counts, and an unresolvable project lands in `<journal>/unsorted/`.

The journal root can also come from `~/.config/opencode/hoko.json`
(`{ "journalPath": "…" }`). Precedence: `HOKO_JOURNAL_PATH` → `hoko.json` → off. The
Python scripts read a `hoko.json` in this repo too, layered under the machine-local one,
and share it for `plansDir`, `coverageMin`, `commitAuto` and the rest.

## Layout

```
plugin/
  index.ts            the entry point V2 imports: re-exports hoko.ts's default
  hoko.ts             registers everything; settings from hoko.env; the hoko_execute
                      tool; prompt capture, the fresh-session handoff to build, and
                      journaling
  test_hoko.ts        tests for the plugin's hooks and tool
Dockerfile            bun + python3, for the test suite only
docker-compose.yml    the `test` service: `docker compose run --rm test`
agents/
  plan.md                 primary; replaces opencode's plan agent with the protocol:
                          grill → plan file → approve → hoko_execute. Installed to
                          ~/.config/opencode/agents/, since a plugin cannot register agents
  hoko-plan-executor.md   subagent; implements one step, never commits
  hoko-researcher.md      subagent; external research, writes .ai/research/<stamp>-<slug>.md
  hoko-step-gate.md       subagent; a step's fast gate — static analysis + unit tests
  hoko-code-reviewer.md   subagent; reviews a diff via hoko-code-review on request
  hoko-code-reviewer-deep.md subagent; the single end-of-run review over the whole
                          branch, on HOKO_REVIEWER_DEEP_MODEL
  hoko-quality-assurance.md subagent; the end-of-run full gate, fixes and commits
  hoko-go-code-reviewer.md subagent; reviews a Go diff against hoko-senior-go-developer,
                          findings tagged official/community/contested, read-only
  hoko-go-test-writer.md  subagent; writes table-driven Go tests, edits only _test.go
                          files and testdata/ fixtures
  hoko-go-architect.md    subagent; decides where a Go library, CLI or service belongs,
                          read-only
commands/
  grill-me.md
  hoko/{plan,execute-plan,commit,research,pr}.md
skills/
  grill-me/               the grilling protocol
  hoko-commit/            commit message conventions
  hoko-pull-request/      end of a run: push and open a PR on GitHub
  hoko-code-review/       review standards + per-language reference guides
  hoko-quality-assurance/ lint → static analysis → tests, any stack
  hoko-feature-specs/     specs/<capability>.md — EARS requirements, selective
                          Gherkin criteria, design notes; written from intent or
                          derived from existing code
  hoko-api-developer/     PHP only: JSON Schema + swagger.yml + versioned routes
  hoko-senior-php-developer/ PHP only: no-comment self-explanatory code, objects over
                          arrays, typed collections, mirrored test tree
  hoko-senior-frontend-developer/ TS/React only: feature-first structure, schemas +
                          endpoints + queries API layer, composition over prop flags
  hoko-senior-go-developer/ Go only: top-level packages and internal/ with no pkg/,
                          errors wrapped only where the API exposes the chain, stdlib
                          net/http, hand-written fakes, log/slog; a reference per topic
                          plus check/test/scaffold scripts
instructions/
  hoko.md                 git stops at the commit: never merge, never push, PR instead;
                          and plan-run delegation is pre-approved by the plan approval
  communication.md        how to answer: lead with the answer, short by default, no
                          preamble before a tool call, comments are the exception
  docker-first.md         docker first: never install or run a language runtime on the
                          host — use docker and docker compose, newest version, and stop
                          when docker does not work
scripts/
  install-agents.sh       symlink agents/*.md into ~/.config/opencode/agents/
  settings.py             the hoko.json/env config the scripts share
  journal.py              write | report | register — the journal entry
  plan-file.py            file an approved plan, record Project:/Journal:, register the session
  invoice.py              render invoice.json + invoice.md from a finished entry's usage
  test_settings.py
  test_journal.py         tests, against a throwaway journal root
  test_plan_file.py
  test_invoice.py
hoko.env.example          every setting, commented, with its default
opencode.json.example     the one line that registers the plugin
```

Agents, commands and skills are plain opencode files — the plugin only reads their
frontmatter and body. The commands and the skills are registered into the live registry;
the agents are installed as files, because V2 gives a plugin no way to add one.
`instructions/` is different again: the plugin adds **every** `.md` in it to every model
request, so it is in context on every agent whether or not a skill is invoked. That is
where rules live that must hold in plain build-mode chat too — a skill only binds once a
model decides to load it, which is exactly when "just commit this" turned into a local
merge into the integration branch.

Dropping a file into `instructions/` is all it takes to add a set, and deleting one is
all it takes to remove it — which is how `communication.md` gets there. Unlike V1, the
plugin does not know what is in `opencode.json`: if you also list an instructions file
there you will get it twice, so let the plugin carry it. Two caveats: instructions cost
context on every turn of every agent, cheap subagents included, so a long file is not
free; and a general rule can collide with the workflow. `communication.md` says not to
spawn subagents without asking, which a plan run does constantly — `hoko.md` carves that
out explicitly, and any other collision belongs there too, not in an edit to the file it
collides with.

The frontmatter parser covers scalars, nested maps (`permission:`, `tools:`) and the
`>`/`|` block scalars the skill descriptions use. It is not a full YAML parser.

Two details worth knowing if you edit the agents: within a permission list opencode
evaluates the **last** matching rule, so broad patterns go first and narrow ones last;
and skill names are flat, which is why they are prefixed `hoko-` rather than namespaced
like the commands.

## Making it yours

The parts most likely to want changing:

- **Commit and PR conventions** — `skills/hoko-commit/SKILL.md` carries the message
  format (why-focused summary, one bullet per change, a trailing Jira-style key when the
  branch name has one). `skills/hoko-pull-request/SKILL.md` carries the PR title and body
  rules.
- **The branching rules** — `instructions/hoko.md` states them (protected branches, which
  base each prefix is cut from, the `<type>/<TICKET-><slug>` naming); `gitVerdict` in
  `plugin/hoko.ts` enforces them, refusing the bash tool a commit on a protected branch, a
  name off the convention, or a branch cut from an explicitly wrong base. A branch created
  without a start point is only toasted, so stacking one branch on another still works.
  Change both together, or the guard contradicts the prose.
- **The gates** — `skills/hoko-quality-assurance/SKILL.md` is the whole gate in one
  file, tool-agnostic. Its hard rules (no suppression entries, no inline ignore
  comments, coverage only goes up) are the opinionated part.
- **The gate's allowlist** — `agents/hoko-step-gate.md`, or
  `agents/hoko-code-reviewer-deep.md` for the end-of-run review, if one cannot run your
  project's check command.
- **Standing rules** — anything in `instructions/`, in context on every agent, every
  turn. `hoko.md` is the git and delegation policy; `communication.md` is response style
  and code-comment policy, and is the most personal file here — replace it with your own
  or delete it.
- **Language conventions** — the `*-php-*` and `*-frontend-*` skills are examples of the
  shape: a narrowly-scoped skill whose description names the stack, so a model only loads
  it on a diff in that stack. Copy one for your own stack, or delete them.
  `hoko-senior-go-developer` is the fullest example: a reference per topic, the
  `go_check.py` / `go_test.py` / `go_scaffold.py` scripts, and the `hoko-go-code-reviewer`,
  `hoko-go-test-writer` and `hoko-go-architect` subagents.

### Stack-specific skills

Six skills trigger on their own descriptions rather than through a command. Two are
stack-neutral — the quality gate and the spec writer; the other four carry stack
conventions and stay out of the way on a diff that is not theirs.

- **`hoko-quality-assurance`** — the gate: lint, then the project's static analyser with
  no suppressions and no inline ignore comments, then tests with coverage above
  `HOKO_COVERAGE_MIN` and rising — with the floor graded in one of three modes:
  `strict` when the project meets it or has met it before, `legacy` when it never has
  (held to its own gitignored `.ai/coverage-baseline` instead), or `absent` when there
  is no suite or no coverage tooling. It comes in two shapes — the fast gate (analyser + unit tests)
  that `hoko-step-gate` runs per step, and the full gate that runs once at the end of a
  run or before a standalone commit.
- **`hoko-feature-specs`** — writes `specs/<capability>.md`: numbered EARS requirements,
  selective Gherkin acceptance criteria and short design notes, from intent before the
  code exists or derived from code that already runs.
- **`hoko-api-developer`** (PHP) — every JSON payload gets a JSON Schema under
  `res/schema/json/<project>/`, with shared shapes extracted into `components/` and
  reused by `$ref`; a `swagger.yml` at the project root references those files instead of
  inlining shapes; routes are versioned from `v1`, grouped by shared path, named, and
  carry their middleware on the group rather than per route.
- **`hoko-senior-php-developer`** (PHP) — self-explanatory code with comments only for a
  non-obvious *why*, fully typed signatures that take and return objects instead of
  arrays, PSR naming (`Interface` suffix), collections built per element type that
  reject foreign types, and a `tests/Unit` tree that mirrors the application tree path
  for path with feature tests grouped by feature.
- **`hoko-senior-frontend-developer`** (TypeScript/React) — feature-first structure with
  imports flowing `shared → features → app` and no cross-feature imports; an API layer
  split by role into `*.schemas.ts`, `*.endpoints.ts` and `*.queries.ts` so one endpoint
  has one obvious home and no URL is written twice; components built by composition and
  slots instead of boolean prop flags; server state left in the query cache; and a named
  list of hacks — `setTimeout` to wait for a render, `any` to silence a type, `!important`
  — that are never the fix.
- **`hoko-senior-go-developer`** (Go) — top-level packages and `internal/` with no `pkg/`,
  errors wrapped only where the API exposes the chain (`%w` exposes it, `%v` hides it) and
  read with `errors.Is`/`errors.As`, the standard library `net/http` `ServeMux` by
  default, hand-written fakes over generated mocks, and structured `log/slog`.

The four stack skills are framework-agnostic within their stack: they detect the
framework and test tooling from the project and express the rules in its idioms.
`hoko-commit` invokes the quality gate before drafting a message, and `hoko-code-review`
points the reviewer at the PHP pair on a PHP diff, at the frontend skill on a
TypeScript/React one and at the Go skill on a Go one, so a plan run picks them up at the
commit step and at the end-of-run review.
Inside a plan run `hoko-commit` holds to the fast gate `hoko-step-gate` already ran
instead of starting the full one; every other commit runs all three.

## Research

`hoko-researcher` answers one question from sources *outside* the repo — pinned-version
documentation, changelogs, specs — and writes `.ai/research/<YmdHis>-<slug>.md` with an
answer, evidence (claim, URL, what the page says), anything it inferred rather than
verified, and what remains open. It reports the path and at most five lines, so the
findings cost the caller almost no context and outlive the session.

Three ways it runs:

- `/hoko/research <question>` — in V1 the command named the subagent as its agent, so
  opencode ran the whole invocation as a subtask. V2 commands cannot name an agent, so the
  command asks the current agent to delegate to `hoko-researcher`; the research still runs
  in a subagent, on its own context.
- plan mode launches it during grilling instead of guessing at external behaviour, and
  cites the findings file in the plan's *Decisions*.
- `/hoko/execute-plan` launches it when a step's blocker is an external unknown.

It may write exactly one path (`.ai/research/*.md`), has `webfetch` and `websearch`
allowed, `bash` restricted to `date`, `mkdir -p` and `git rev-parse`, and cannot ask you
questions. Codebase-only questions belong to opencode's `explore` subagent, and the
agent says so rather than answering them.

Two limits worth knowing. `websearch` needs a search provider configured in your
install — check with `opencode debug agent hoko-researcher` and look for it in the tool
map; `webfetch` always works, so give it URLs when it has no search. And subagents
cannot launch subagents at opencode's default `subagent_depth: 1`, so `hoko-plan-executor`
and `hoko-code-reviewer` cannot research on their own — only the primary agent can, which
is why the blocker path routes back through the conductor.

## Tests

The suite needs bun and python3 together, so it runs in the container this repo ships:

```sh
docker compose run --rm test    # the whole suite, in the order below
```

The `test` service is `bun run test`, which is:

```sh
bun plugin/test_hoko.ts         # plugin: capture, the tool, the handoff, journaling, invoice
python3 scripts/test_settings.py  # config: precedence, coercion, dict parsing
python3 scripts/test_journal.py # journal: entries, titles, projects, reports, config
python3 scripts/test_plan_file.py # filing: header lines, sessions.json, idempotence
python3 scripts/test_invoice.py # invoice: per-model sums, round/role attribution, rates
python3 skills/hoko-senior-go-developer/scripts/test_go_scripts.py
                                # Go scripts: check order, skips, coverage, scaffold
```

Run a single one with `docker compose run --rm test bun plugin/test_hoko.ts`.

Every one runs against throwaway directories and never touches a real journal.

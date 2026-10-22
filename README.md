# hoko — a plan-and-execute workflow for opencode

Plan mode grills you, writes the plan to a file, and hands it to a build run that
implements it one gated, committed step at a time. The loop is deterministic: a Python
engine owns the plan's checklist, the fast gate, the commit and the run's event log, so
"gate before commit, tick after commit" is enforced in code instead of in a model's
memory. Once every step is committed the full quality gate runs once, the specs are
updated, one strict review covers the whole branch, and only a clean verdict opens a pull
request. Nothing merges.

There is a second front door: `/hoko/task` runs a whole task through the pipeline —
refine, spec, plan, implement, QA, review — with automatic fix cycles, stopping only for
product decisions. It shares the same engine, the same commits and the same review.

While a run is under way the terminal shows what it is doing: a status line under the
prompt and a pane in the sidebar, both read from the run's own `progress.json`. A loop
guard keeps the conductor out of the repository, so the implementation stays in the
subagents it launched.

Everything lives under the **`hoko`** namespace — commands are `/hoko/…`, agents and
skills are `hoko-…` — except `grill-me`, which keeps its bare name, and `plan`, which
deliberately replaces opencode's own plan agent.

It is stack-agnostic: the gates are expressed as *lint → static analysis → tests with
coverage* and each project's own commands are resolved from its manifests, CI and build
files rather than assumed. Optional skills carry stack conventions — PHP, TypeScript/React
and Go — and trigger only on a diff in that stack.

## Install

### What it needs

| | |
| --- | --- |
| opencode | 2.0 or newer — `opencode --version`. On V1 see [Migration from V1](#migration-from-v1) |
| python3 | 3.9 or newer — the engine every run calls: the plan lint and filing, the checklist, the gates, the task pipeline, the invoice |
| git | runs commit each step, and the gates diff against a base |
| node modules | **none.** `plugin/hoko.ts` uses node's standard library only |

There is nothing to build and no dependency to install. The plugin has no dependencies on
purpose — that is why its tool takes no arguments, since declaring arguments would mean
importing zod, and importing zod would mean an install step. `bun` is needed only to run
the plugin's own tests, never at runtime.

One thing V2 changed: a plugin can no longer register agents, so this repo's
`agents/*.md` are installed as files (step 3). The server plugin also has no TUI API, so
the run display and the jump to the run's session live in `plugin/tui.ts`, the terminal
entrypoint V2 loads beside the server one. Everything else — commands, skills, the
standing instructions — is registered by the plugin as before.

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
`~/.config/opencode/` or a project's `.opencode/`. So the repo registers itself: one line
in `~/.config/opencode/opencode.json` and the plugin injects its commands, skills and
standing instructions into the live config at startup. `opencode.json.example` is that
file:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "plugins": ["file:///ABSOLUTE/PATH/TO/hoko-opencode-plugin/plugin"]
}
```

Replace the placeholder with the path from step 1. It must be a `file://` URL with an
absolute path, and it must point at the **`plugin` directory**, not at `plugin/hoko.ts`:
V2 loads a path entry as a directory, imports its `index.ts`, and loads its `tui.ts` as
the terminal entrypoint. A path to a file is rejected with
`configured plugin path must be a directory`. If
`~/.config/opencode/opencode.json` already exists, add the entry to the `plugins` array
you have rather than replacing the file.

```sh
cp opencode.json.example ~/.config/opencode/opencode.json   # only if you have none
```

The `plugin` entry names the checkout opencode loads everything from — not just
`plugin/hoko.ts`, but the commands, skills and instructions it injects, and the scripts
the run calls. An edit made in a different clone, or a copy installed elsewhere, has no
effect until this path points at that checkout and opencode reloads.

### 3. Install the agents

V2 fixed the plugin API against adding agents, so the plugin cannot register the ones
this repo ships. They are discovered from `~/.config/opencode/agents/` instead:

```sh
scripts/install-agents.sh
```

That symlinks every `agents/*.md` into `~/.config/opencode/agents/`, so editing one here
stays live. Re-running is safe, and a real file already sitting at a target path is left
alone and reported rather than overwritten. To undo, delete the symlinks. V2's built-in
`plan` agent shadows the `plan.md` symlink, so the plugin applies that same file's prompt
to the built-in agent itself; the hoko subagents still need the symlinks.

### 4. Configure it (optional)

```sh
cp hoko.env.example ~/.config/opencode/hoko.env
```

Uncomment what you want — the table under [Configuration](#configuration) says what each
variable does. Everything has a working default: leave the file untouched and every agent
runs on the session's model, plans go to `.ai/plans/`, runs write their events under
`.ai/runs/`, the coverage floor is 85%, three fix cycles is the task pipeline's limit, a
PR targets `develop` where the repository has one, and nothing is journaled.

Keeping the file at `~/.config/opencode/hoko.env` rather than in the repo means a
`git pull` never touches your settings. Engine settings can also live in
`~/.config/opencode/hoko.json`; see [Configuration](#configuration).

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
a request to approve. Say **approved**: the plan is linted and filed, the TUI moves to a
fresh session, and the run starts at step 1 with a `hoko-plan-executor` subagent. The
status line under the prompt reads `hoko · <project>@<branch> · Implement 1/<n> · cycle 1`
once the first step starts.

The display's slot names — `prompt.footer.status` and `home.footer.status` for the status
line, `sidebar.content` for the pane — are what a live opencode 2.1.2 run accepted. The
host publishes no slot contract this repository can read, so `bun plugin/test_hoko.ts`
pins `plugin/status.tsx` to that observation rather than to a specification.

To undo all of this, delete the plugin entry from `opencode.json`, delete the symlinks
step 3 made, and reload.

### Updating

Pull (or edit) and reload opencode. That is the whole procedure: nothing is copied,
compiled or installed, so the files in this repo *are* the live workflow — the plugin is
loaded from `plugin/`, the agents are symlinks into `agents/`, and every run calls
`scripts/` in place. Editing any of them changes it everywhere on the next reload. A
syntax error in `plugin/hoko.ts` takes the whole thing down, so run the tests after
touching it.

### Upgrading from the conversational loop

This branch replaces the per-step review agents with the deterministic engine. Five things
change in an existing install:

1. **The plans layout grew a second shape.** A plan run still keeps one flat
   `<YYYYmmddHHMMSS>-<slug>.md` with its `<stem>.progress.json` sidecar beside it, so
   existing plans keep working and a half-finished run resumes from its `## Progress`
   checklist. A `/hoko/task` run now owns a folder, `.ai/plans/<YYYYmmdd-HHMM>-<slug>/`,
   holding its `progress.json`, `prompt.md`, stage hand-offs, `plan-NN.md` files and
   `report.md`. Run events go to `.ai/runs/<run_id>/events.jsonl`; both top folders are
   gitignored for you.
2. **Two agents retired.** The per-step gate agent and the end-of-run deep reviewer are
   gone: `step-commit.py` runs the fast gate inside the commit, and `hoko-final-reviewer`
   is the single review of the whole branch. Their symlinks now point at deleted files, so
   prune them and re-install the rest:

   ```sh
   for link in ~/.config/opencode/agents/hoko-*.md; do [ -e "$link" ] || rm "$link"; done
   scripts/install-agents.sh
   ```

3. **`python3` is now required by the run.** Before, it was only the journal's token
   invoice; now the plan lint, the filing, the checklist, the fast gate, the task pipeline
   and the closing report all run through `scripts/`. A missing `python3` refuses the
   handoff with its own message instead of failing halfway through a step.
4. **One model variable was replaced.** `HOKO_REVIEWER_DEEP_MODEL` is gone;
   `HOKO_FINAL_REVIEW` names the model for `hoko-final-reviewer` and is a model reference
   like the others, so `provider/model` or `provider/model#variant`.
5. **New settings.** `analyticsPath`, `events`, `eventsDir`, `loopLimit`, `planGate`,
   `crap`, `mutation`, `crapMax`, `mutationMin`, `pricing` and `efforts` are read from
   `hoko.json` and from `HOKO_*` variables; existing files need no edit, because every one
   has a working default. See [Configuration](#configuration).

The checkout this repo lives in and the checkout opencode loads are not always the same
one: the live install is a separate clone at
`/Users/hossein.koozehgar/ai/plugins/hoko-opencode-plugin`, on branch `main`. Changes made
here reach it only after a `git pull` in that directory, and then only after opencode
reloads. Pull there before deciding an upgrade did not work.

### When something is off

| Symptom | What it means |
| --- | --- |
| Log says `configured plugin path must be a directory` | The `plugins` entry points at `plugin/hoko.ts`. V2 a path entry loads as a directory — point it at `.../hoko-opencode-plugin/plugin`. |
| No `/hoko` commands, no `hoko-` agents | The plugin never loaded. Check the entry in `opencode.json` is an absolute `file://` URL to the `plugin` directory, then `opencode service restart`. |
| Plan mode answers like stock opencode | The plugin's `plan` prompt is not reaching the built-in agent. Reload and check `opencode debug agents`: `plan` must carry a system prompt and the hoko permissions. |
| The plan arrives in the chat, not as a file | The edit exception is not reaching the plans directory — check the permission list in `opencode debug agents`. The agent says so itself rather than losing the plan. |
| "approved" is refused and names a finding | `plan-lint.py` found a blocking problem: an unclaimed or undeclared requirement id, a step-number gap, a requirement without ` shall `. Fix the plan and approve again; no run session was made. |
| "approved" produces a reply but no run | The plan agent did not call `hoko_execute`, or the tool is not permitted. Check the permission list in `opencode debug agents`; if there is no plan *file* in the session, the tool refuses by design. |
| The handoff produces a session with no run | Run `/hoko/execute-plan <path>` yourself and check the opencode log — a failed handoff is written there and announced as a synthetic notice. |
| The screen stays on Plan after approval | `plugin/tui.ts` did not load, or the run session was created without its `hoko: run` marker. Check the plugin list and the server log. |
| No status line, no pane | The terminal entrypoint did not load, or its slots are unavailable in this opencode build. The run is unaffected; the plan file and its `progress.json` still carry the state. |
| `python3: command not found`, or `python3` older than 3.9 | The engine cannot run. Install python3 (and make sure `python3` is what resolves, not only `python3.11`), then approve the plan again. |
| A step refuses to commit | `step-commit.py` names the reason: exit 1 a red fast gate, 3 a protected branch, 4 a dirty or unchanged tree, 5 a malformed message, 6 a failed `git commit`. The step stays unticked in every one. |
| A command is denied mid-run | The loop guard is armed and the conductor tried to read or edit the repository itself. Launch the subagent instead; `HOKO_LOOP_GUARD=0` disables the guard if you really mean to work in the main session. |
| No journal entry | Expected unless `HOKO_JOURNAL_PATH` is set — journaling is off by default. With it set: `python3` missing, or the root is not writable. `hoko_execute` reports the reason in its output instead of failing silently. |
| No events | `HOKO_EVENTS=0`, or the write failed once and the run disabled events for itself. The reason is printed once on stderr; commands keep their exit status either way. |
| Entry has no `report-NN.md` | The run never set `Status: complete` — a blocker or a `not ready` gate — or the closing report was not the last thing posted. |
| A gate says it could not run a check | `scripts/commands.py --root <repo>` names what it resolved per gate; a `null` means the project names no command for it. Add the target or script it looks for, or install the tool. |

## Migration from V1

V2 has three intentional breaking changes, and one of them is the plugin API: **a V1
plugin does not run in V2.** The plugin here has been ported, and its own workflow is the
one documented in this file. What you have to do by hand:

1. **Re-point the plugin.** The `plugin` key becomes `plugins`, and the value becomes the
   `plugin` *directory* rather than `plugin/hoko.ts`. See [step 2](#2-point-opencode-at-the-plugin).
2. **Install the agents.** A V2 plugin cannot add agents, so `agents/*.md` are discovered
   from `~/.config/opencode/agents/`. Run `scripts/install-agents.sh`. This is the step
   V1 did not have.
3. **Reload**, then check `opencode debug agents`.

Behavior the V2 API forced to change:

| V1 | V2 |
| --- | --- |
| The plugin registered the agents | Agents are files under `~/.config/opencode/agents/`, installed by `scripts/install-agents.sh` |
| The plugin appended `instructions/*.md` to the config | The plugin adds them to every model request from the `context` hook — same effect, they are in context on every turn of every agent |
| `tui.showToast` announced the handoff, the journaled report and the invoice | The server plugin has no TUI API; `plugin/tui.ts` announces the run, and the git guard's warning still arrives as a synthetic notice in the session |
| Approving switched the TUI to the run's fresh session | `plugin/tui.ts` listens for the run session's `hoko: run` marker, syncs it and navigates to it |
| `HOKO_PROMPT_FILE` was exported into every shell | The V2 shell hook carries no session id, so it is gone. Nothing read it |
| The plugin detected a hand-written `plan` block and left its prompt alone | A plan agent that already carries a system prompt is the user's own and is left alone; an empty one receives this repo's protocol. `HOKO_*_MODEL` is now authoritative when set |
| `/hoko/research` ran as a subtask because a command could name a subagent | A command cannot name an agent, and a session cannot run on a subagent-only agent, so the command asks the current agent to delegate to `hoko-researcher` |
| The plan agent's `tools` map was switched on | V2 agents have no `tools` map; tool availability follows permissions |

`plugin/hoko.ts` was rewritten for the V2 API: `setup(ctx)` with `ctx.tool.transform`,
`ctx.tool.hook`, `ctx.shell.hook`, `ctx.session.hook`, `ctx.event.subscribe`,
`ctx.agent.transform`, `ctx.command.transform` and `ctx.skill.transform`. It still imports
nothing beyond node's standard library and its own sibling modules. The journaling
scripts, the settings loader and the frontmatter parser are the V2 versions in
`scripts/`, and `scripts/` as a whole is now the deterministic engine described under
[the workflow](#the-workflow). `MIGRATION-V2.md` carries the same list with the details.

## Configuration

Settings come from two files, because the plugin and the engine read them at different
times.

- **`hoko.env`** — `hoko.env` in this repo, then `~/.config/opencode/hoko.env`, then the
  real environment. The plugin reads it at startup for models, journaling, the handoff and
  the loop guard, and exports every value into each shell an agent runs.
- **`hoko.json`** — this repo's `hoko.json`, then `~/.config/opencode/hoko.json`. The
  Python scripts read it for their own keys, then let a `HOKO_*` variable override them.

Put together, lowest precedence first: the repo's `hoko.json`, the machine's `hoko.json`,
the repo's `hoko.env`, the machine's `hoko.env`, the real environment. Copy
`hoko.env.example` for the first, and write the second by hand — it is a JSON object with
one key per setting:

```json
{ "journalPath": "~/notes/journal", "analyticsPath": "~/ai/analytics/opencode", "loopLimit": 5 }
```

| Variable | Sets | Default |
| --- | --- | --- |
| `HOKO_PLAN_MODEL` | model for the `plan` agent | the session's model |
| `HOKO_BUILD_MODEL` | model for the `build` agent — the conductor of a run | the session's model |
| `HOKO_EXECUTOR_MODEL` | model for `hoko-plan-executor` | the session's model |
| `HOKO_REVIEWER_MODEL` | model for `hoko-code-reviewer`, on request | the session's model |
| `HOKO_FINAL_REVIEW` | model for `hoko-final-reviewer`, the run's one review | the session's model |
| `HOKO_QA_MODEL` | model for `hoko-quality-assurance` | the session's model |
| `HOKO_RESEARCH_MODEL` | model for `hoko-researcher` | the session's model |
| `HOKO_JOURNAL_PATH` (`journalPath`) | journal root | **unset — journaling is off** |
| `HOKO_ANALYTICS_PATH` (`analyticsPath`) | where a run's sessions, invoice and event copies go | **unset — they stay in the journal entry** |
| `HOKO_PLANS_DIR` (`plansDir`) | plans and task folders, relative to the repo root | `.ai/plans` |
| `HOKO_EVENTS` (`events`) | append the run's events | on |
| `HOKO_EVENTS_DIR` (`eventsDir`) | run event folders, relative to the repo root | `.ai/runs` |
| `HOKO_LOOP_LIMIT` (`loopLimit`) | fix cycles a `/hoko/task` run may take, 0 to 10; 0 accepts the open findings unasked | `3` |
| `HOKO_PLAN_GATE` (`planGate`) | ask Approve / Revise / Stop before a task's steps start | on |
| `HOKO_EFFORTS` (`efforts`) | per-stage effort as a JSON object over refine, spec, plan, implement, qa and review; a task stage's model ref carries it as its `#variant` | `high`, `qa` at `medium` |
| `HOKO_SPECS` (`specs`) | the plan run's spec pass, and the task pipeline writing `specs/` instead of a local `spec.md` | off |
| `HOKO_CRAP` (`crap`) | the CRAP index in the full gate | on |
| `HOKO_CRAP_MAX` (`crapMax`) | the CRAP index's ceiling | `30` |
| `HOKO_MUTATION` (`mutation`) | mutation testing in the full gate | on |
| `HOKO_MUTATION_MIN` (`mutationMin`) | the mutation score floor | `70` |
| `HOKO_PRICING` (`pricing`) | rate overrides for the invoice, laid over `scripts/pricing.json` | `{}` |
| `HOKO_COVERAGE_MIN` (`coverageMin`) | the full gate's coverage floor, in percent | `85` |
| `HOKO_FRESH_SESSION` | approval starts the run in a fresh session and `tui.ts` moves the screen to it. `0`, `false`, `no` or `off` hand off in the approval session | on |
| `HOKO_LOOP_GUARD` | deny the conductor its own reads and edits while a run is in progress | on |
| `HOKO_COMMIT_AUTO` (`commitAuto`) | `1` = `hoko-commit` commits without confirming the message | off |
| `HOKO_BASE_BRANCH` | branch playing the `develop` role — what features branch from and target | `develop`, else the remote's default branch |
| `HOKO_PR_AUTO` | `1` = `hoko-pull-request` pushes and opens the PR without confirming | off |

Models are `provider/model-id`, and a model variable may carry an opencode variant as
`provider/model-id#variant`. `opencode models` lists them.

The plugin exports all of these, plus `HOKO_ROOT`, into every shell the agent runs —
which is how the skills and the engine read the settings that apply to them. V1 also
exported `HOKO_PROMPT_FILE` (this session's captured prompt); V2's shell hook carries no
session id, so it is gone. Nothing else read it.

A model variable overrides whatever model the agent would otherwise use, including a model
you set yourself in `opencode.json` or in the agent file; an unset variable leaves the
agent alone. Every other setting is read by the scripts and never touches an agent's
frontmatter.

`efforts` is applied as the `#variant` of the stage's model, by whichever side resolves that
model. The plugin resolves each agent's model from its `HOKO_*_MODEL` and appends the
stage's effort — `plan` for `plan`, `implement` for `build` and `hoko-plan-executor`, `qa`
for `hoko-quality-assurance`, `review` for the two reviewers — unless the ref already names
a variant, which wins. That is what puts `efforts.implement` on a plan run's executor,
whose command passes no model. The task pipeline embeds the same suffix in the model ref on
a spawn or step action; that explicit ref wins over the agent's because the conductor
passes it, so the effort lands once. A stage whose agent has no model variable (the
specifier, spec writer and planner) or no stage (`hoko-researcher`) gets no suffix; the
run's `run.started` event still records every stage's effort.

## The workflow

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

### 2. Approval is linted, filed, and handed off

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
in hand. The server plugin cannot move the screen itself, so `plugin/tui.ts` follows the
new session's marker and brings the prompt box with the run.

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

### 3. Execution is one deterministic loop

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

### 4. `/hoko/task` runs a whole task

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

### 5. The run is visible while it runs

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

### 6. The journal, the analytics folder and the invoice

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

## Layout

```
plugin/
  index.ts            the server entry point V2 imports: re-exports hoko.ts's default
  hoko.ts             registers everything; settings from hoko.env; the hoko_execute
                      tool — lint, file, fresh session, handoff; prompt capture; usage
                      collection and the run's close
  guard.ts            the loop guard: the newest progress.json, and whether a call may
                      read or edit the repository
  status.ts           reads the run into the status line and the pane's view
  status.tsx          the Solid half: footer and sidebar slot contributions
  tui.ts              the terminal entrypoint: the jump to the run session and the slots
  test_hoko.ts        tests for the entrypoints, the guard and the display
Dockerfile            bun + python3, for the test suite only
docker-compose.yml    the `test` service: `docker compose run --rm test`
Makefile              `test` (parallel) and `test-serial`
agents/
  plan.md                 primary; replaces opencode's plan agent with the protocol:
                          grill → plan file → approve → hoko_execute. Installed to
                          ~/.config/opencode/agents/, since a plugin cannot register agents
  hoko-plan-executor.md   subagent; implements one step, never commits
  hoko-specifier.md       subagent; refines a task prompt, writes scope.json
  hoko-spec-writer.md     subagent; writes or reconciles the spec
  hoko-planner.md         subagent; writes a task's plan and its hand-off
  hoko-quality-assurance.md subagent; the full gate, fixes and commits
  hoko-final-reviewer.md  subagent; the one review of a finished run
  hoko-code-reviewer.md   subagent; reviews a diff via hoko-code-review on request
  hoko-researcher.md      subagent; external research, writes .ai/research/<stamp>-<slug>.md
  hoko-security-auditor.md subagent; a security audit of a path or a codebase
  hoko-journal-writer.md  subagent; files one journal report on request
  hoko-go-code-reviewer.md subagent; reviews a Go diff against hoko-senior-go-developer,
                          findings tagged official/community/contested, read-only
  hoko-go-test-writer.md  subagent; writes table-driven Go tests, edits only _test.go
                          files and testdata/ fixtures
  hoko-go-architect.md    subagent; decides where a Go library, CLI or service belongs,
                          read-only
commands/
  grill-me.md
  hoko/{plan,execute-plan,task,commit,research,pr}.md
skills/
  grill-me/               the grilling protocol
  hoko-task/              the /hoko/task conductor: the loop around task.py
  hoko-commit/            commit message conventions
  hoko-pull-request/      end of a run: push and open a PR on GitHub
  hoko-code-review/       review standards + per-language reference guides
  hoko-security-review/   the security guide as a front door
  hoko-quality-assurance/ lint → static analysis → tests, any stack
  hoko-feature-specs/     specs/<capability>.md — EARS requirements, selective
                          Gherkin criteria, design notes
  hoko-research/          answer an external question, file the findings
  hoko-log-plan/          the manual fallback for filing a prompt and a plan
  hoko-log-report/        the manual fallback for filing a run's report
  hoko-api-developer/     PHP only: JSON Schema + swagger.yml + versioned routes
  hoko-senior-php-developer/ PHP only: no-comment self-explanatory code, objects over
                          arrays, typed collections, mirrored test tree
  hoko-senior-frontend-developer/ TS/React only: feature-first structure, schemas +
                          endpoints + queries API layer, composition over prop flags
  hoko-senior-go-developer/ Go only: top-level packages and internal/ with no pkg/,
                          errors wrapped only where the API exposes the chain, stdlib
                          net/http, hand-written fakes, log/slog
instructions/
  hoko.md                 git stops at the commit: never merge, never push, PR instead;
                          and run delegation is pre-approved by the plan approval
  communication.md        how to answer: lead with the answer, short by default, no
                          preamble before a tool call, comments are the exception
  docker-first.md         docker first: never install or run a language runtime on the
                          host — use docker and docker compose, and stop when docker
                          does not work
scripts/
  settings.py             the hoko.json/env config the scripts share
  plan_format.py          the plan's own format: steps, requirements, sections
  plan-lint.py            the machine checks on a plan: block approval or note
  plan-find.py            find the newest unfinished plan, this repo first
  plan-slice.py           cut one step out of a plan for its executor
  plan-flow.py            the grill subcommand the planning protocol calls
  plan-file.py            file an approved plan: header, copy, Progress, registry
  plan-progress.py        init | start | tick | complete | abort — the checklist and
                          the run's events
  progress.py             the one reader/writer of ## Progress and progress.json
  followup.py             render the next round's plan from findings
  review-findings.py      turn the strict review's JSON into a follow-up plan
  commands.py             resolve a project's lint/analyse/unit/suite/coverage/mutation
  gate.py                 run one gate command and keep its exit status
  fast-gate.py            the analyser + unit tests a step commit runs
  in-service.py           wrap a PHP command in the project's container
  crap.py                 the CRAP index for the changed methods
  step-commit.py          gate, commit and tick one step in one enforced call
  events.py               the only writer of .ai/runs/<run_id>/events.jsonl
  analytics.py            where a journal entry's numbers live
  journal.py              write | report | register — the journal entry
  invoice.py              render invoice.json + invoice.md from reported usage
  task.py                 the /hoko/task state machine
  pricing.json            the bundled rates the invoice falls back to
  install-agents.sh       symlink agents/*.md into ~/.config/opencode/agents/
  run_tests.py            the parallel runner for the suites below
hoko.env.example          every setting, commented, with its default
opencode.json.example     the one line that registers the plugin
MIGRATION-V2.md           the V1 → V2 plugin-API migration
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
all it takes to remove it. Unlike V1, the plugin does not know what is in
`opencode.json`: if you also list an instructions file there you will get it twice, so let
the plugin carry it. Two caveats: instructions cost context on every turn of every agent,
cheap subagents included, so a long file is not free; and a general rule can collide with
the workflow. `communication.md` says not to spawn subagents without asking, which a run
does constantly — `hoko.md` carves that out explicitly, and any other collision belongs
there too, not in an edit to the file it collides with.

The frontmatter parser covers scalars, nested maps (`permission:`, `tools:`) and the
`>`/`|` block scalars the skill descriptions use. It is not a full YAML parser.

Two details worth knowing if you edit the agents: within a permission list opencode
evaluates the **last** matching rule, so broad patterns go first and narrow ones last;
and skill names are flat, which is why they are prefixed `hoko-` rather than namespaced
like the commands.

## Making it yours

The parts most likely to want changing:

- **Commit and PR conventions** — `skills/hoko-commit/SKILL.md` carries the message
  format (why-focused summary, one bullet per change, a trailing ticket key when the
  branch name has one). `skills/hoko-pull-request/SKILL.md` carries the PR title and body
  rules.
- **The branching rules** — `instructions/hoko.md` states them (protected branches, which
  base each prefix is cut from, the `<type>/<TICKET-><slug>` naming); `gitVerdict` in
  `plugin/hoko.ts` enforces them, refusing the shell tool a commit on a protected branch, a
  name off the convention, or a branch cut from an explicitly wrong base. A branch created
  without a start point is only warned about, so stacking one branch on another still
  works. Change both together, or the guard contradicts the prose.
- **The gates** — `skills/hoko-quality-assurance/SKILL.md` is the whole gate in one file,
  tool-agnostic. Its hard rules (no suppression entries, no inline ignore comments,
  coverage only goes up) are the opinionated part. The commands themselves come from
  `scripts/commands.py`, so a project that names its gate in a `Makefile`, a manifest or
  CI is already covered; extend that resolver when your project names it somewhere else.
- **The engine's checks** — `scripts/plan-lint.py` decides what blocks a plan's approval,
  `scripts/fast-gate.py` what a step must pass, and `scripts/step-commit.py` how a commit
  is validated. All three are plain Python with their own suites.
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

The stack-neutral skills — the quality gate, the spec writer, the reviewer, the task
pipeline — trigger on their own descriptions; the stack skills carry conventions and stay
out of the way on a diff that is not theirs.

- **`hoko-quality-assurance`** — the gate: lint, then the project's static analyser with
  no suppressions and no inline ignore comments, then tests with coverage above
  `HOKO_COVERAGE_MIN` and rising — with the floor graded in one of three modes:
  `strict` when the project meets it or has met it before, `legacy` when it never has
  (held to its own gitignored `.ai/coverage-baseline` instead), or `absent` when there
  is no suite or no coverage tooling. After coverage it scores the changed methods for
  CRAP against `crapMax` and measures mutation against `mutationMin`; both are reported,
  and a surviving mutant is closed by an assertion rather than by suppressing the mutant.
  It comes in two shapes — the fast gate (`scripts/fast-gate.py`, analyser + unit tests)
  that every step commit runs, and the full gate that runs once at the end of a run or
  before a standalone commit.
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
commit step and at the end-of-run review. `hoko-security-review` is the front door to the
review's security guide when you want only that pass.
Inside a plan run `hoko-commit` holds to the fast gate the step commit already ran
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
- a run launches it when a step's blocker is an external unknown: the `/hoko/task`
  pipeline routes an `external` blocker to it and puts the findings into the implementer's
  prompt, and the plan conductor does the same by hand.

It may write exactly one path (`.ai/research/*.md`), has `webfetch` and `websearch`
allowed, `bash` restricted to `date`, `mkdir -p` and `git rev-parse`, and cannot ask you
questions. Codebase-only questions belong to opencode's `explore` subagent, and the
agent says so rather than answering them.

Two limits worth knowing. `websearch` needs a search provider configured in your
install — check with `opencode debug agent hoko-researcher` and look for it in the tool
map; `webfetch` always works, so give it URLs when it has no search. And subagents
cannot launch subagents at opencode's default `subagent_depth: 1`, so `hoko-plan-executor`
and `hoko-code-reviewer` cannot research on their own — only the primary agent can, which
is why both the blocker path and the task pipeline route back through the conductor.

## Tests

The suite needs bun and python3 together, so it runs in the container this repo ships:

```sh
docker compose run --rm test    # the whole suite
```

The `test` service is `bun run test`, which is:

```sh
bun plugin/test_hoko.ts && python3 scripts/run_tests.py
```

`bun plugin/test_hoko.ts` covers the server entrypoint, the guard and the display;
`python3 scripts/run_tests.py` runs every `scripts/test_*.py` suite in parallel, one per
engine script — settings, the plan format and lint, progress, the gates, the step commit,
events and analytics, journaling, the invoice, the task pipeline, the follow-up renderer,
the docs and the manifests. `make test` is the same runner and `make test-serial` runs the
suites one after another when a failure needs readable output.

Run a single Python suite by path — `python3 scripts/test_settings.py` — one suite through
the runner with `python3 scripts/run_tests.py --pattern test_settings.py`, and the
TypeScript file with `bun plugin/test_hoko.ts`.

Every one runs against throwaway directories and never touches a real journal.

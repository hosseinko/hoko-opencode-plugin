# my-opencode-plugins

The plan-and-execute workflow, ported from my Claude Code plugins
(`giata-claude-plugins` + `my-claude-plugins`) to opencode.

Everything lives under the **`hoko`** namespace — commands are `/hoko/…`, agents and
skills are `hoko-…` — except `grill-me`, which keeps its bare name, and `plan`, which
deliberately replaces opencode's own plan agent.

## Install

### What it needs

| | |
| --- | --- |
| opencode | 1.18 or newer — `opencode --version` |
| python3 | for the journal script — `python3 --version` (macOS ships it) |
| git | plan runs commit each step |
| node modules | **none.** `plugin/hoko.ts` uses node's standard library only |

There is nothing to build and nothing to install. The plugin has no dependencies on
purpose — that is why its tool takes no arguments, since declaring arguments would mean
importing zod, and importing zod would mean an install step.

### 1. Put the repo somewhere stable

opencode loads the plugin from an absolute path, so pick a home for this checkout and
leave it there. Mine:

```sh
cd /Users/hossein.koozehgar/Sandbox/my-opencode-plugings && pwd
```

Keep that path — step 2 needs it.

### 2. Point opencode at the plugin

opencode has no plugin marketplace, and agents and commands are only discovered inside
`~/.config/opencode/` or a project's `.opencode/`. So the repo registers itself: one
line in `~/.config/opencode/opencode.json` and the plugin injects its agents, commands
and skills into the live config at startup.

```json
{
  "$schema": "https://opencode.ai/config.json",
  "plugin": ["file:///Users/hossein.koozehgar/Sandbox/my-opencode-plugings/plugin/hoko.ts"]
}
```

It must be a `file://` URL with the absolute path, pointing at `plugin/hoko.ts` itself.
If that file already exists, add the entry to the `plugin` array you have rather than
replacing the file.

### 3. Configure the models and the journal (optional)

```sh
cp hoko.env.example ~/.config/opencode/hoko.env
```

Uncomment what you want — the table under [Configuration](#configuration) says what each
variable does. Everything has a working default: leave the file untouched and every
agent runs on the session's model, with the journal at
`~/Obsidian Vaults/Personal/Journal`. The journal directory is created on first use.

Keeping the file at `~/.config/opencode/hoko.env` rather than in the repo means a
`git pull` never touches your settings.

### 4. Restart opencode

Config is read once at startup and never hot-reloaded. Every change here — this repo's
files, `hoko.env`, `opencode.json` — needs a restart, not a new session.

### 5. Check it took

```sh
opencode agent list          # plan, hoko-plan-executor, hoko-code-reviewer,
                             #   hoko-quality-assurance, hoko-researcher
opencode debug skill         # grill-me, hoko-commit, hoko-pull-request, hoko-code-review,
                             #   hoko-api-developer, hoko-quality-assurance,
                             #   hoko-senior-php-developer
opencode debug config        # the /hoko commands, and the model each agent resolved to
opencode debug agent plan    # the important one — see below
```

`opencode debug agent plan` is where the workflow lives or dies. Three things to find in
it:

- the **prompt** is the planning protocol (it mentions `grill-me` and `hoko_execute`),
  not opencode's stock plan prompt;
- **edit** is `"*": "deny"` with `.ai/plans/*.md` allowed — that one exception is how a
  plan becomes a file;
- the **tool map** has `write`, `edit`, `bash` and `hoko_execute` enabled.

### 6. Smoke-test it

In any git repo:

```
Tab → Plan
"add a --verbose flag to the CLI entrypoint"
```

You should get grilled one question at a time, then a plan path under `.ai/plans/`, then
a request to approve. Say **approved** and watch for three things: a toast naming the
plan, the prompt box flipping from Plan to Build, and the run starting at step 1 with a
`hoko-plan-executor` subagent. A journal entry appears under
`<journal>/<project>/` the moment you approve, and gains its `## Final report`
section when the run finishes.

To undo all of this, delete the plugin line from `opencode.json` and restart.

### Updating

Pull (or edit) and restart opencode. That is the whole procedure: nothing is copied,
symlinked, compiled or installed, so the files in this repo *are* the live workflow.
Editing an agent, a command or a skill here changes it everywhere on the next start —
which also means a syntax error in `plugin/hoko.ts` takes the whole thing down, so run
the tests after touching it.

### When something is off

| Symptom | What it means |
| --- | --- |
| No `/hoko` commands, no `hoko-` agents | The plugin never loaded: check the path in `opencode.json` is absolute, `file://`, and ends in `plugin/hoko.ts`. Then restart. |
| Plan mode answers like stock opencode | You have a `plan` block in `opencode.json`; the plugin leaves a hand-written agent's prompt alone. Remove the `prompt` from it. |
| The plan arrives in the chat, not as a file | The edit exception is not reaching `.ai/plans/*.md` — check the permission map in `opencode debug agent plan`. The agent says so itself rather than losing the plan. |
| "approved" produces a reply but no run | The plan agent did not call `hoko_execute`. Check it is in the tool map; if there is no plan *file* in the session, the tool refuses by design. |
| Toast says the handoff failed | Run `/hoko/execute-plan <path>` yourself — the path is in the toast — and check `opencode debug config` for the command. |
| The prompt box stays on Plan | Cosmetic only; the run is on build. The plugin walks the TUI round with `agent_cycle` and gives up quietly if it cannot work out the distance. |
| No journal entry | `python3` missing, or the journal root is not writable. `hoko_execute` reports the reason in its output instead of failing silently. |
| Entry has no `## Final report` | The run never set `Status: complete` — a blocker or a `not ready` gate — or the closing report was not the last thing posted. |
| Plans land in `.claude/plans/` | Stale Claude Code skills are being picked up: `OPENCODE_DISABLE_CLAUDE_CODE_SKILLS=1`. |

## Configuration

Copy `hoko.env.example` to `~/.config/opencode/hoko.env` and uncomment what you want.
The plugin reads, in increasing order of precedence: `hoko.env` in this repo,
`~/.config/opencode/hoko.env`, then any `HOKO_*` variable in the real environment.

| Variable | Sets |
| --- | --- |
| `HOKO_PLAN_MODEL` | model for the `plan` agent |
| `HOKO_BUILD_MODEL` | model for the `build` agent — the conductor of a plan run |
| `HOKO_EXECUTOR_MODEL` | model for `hoko-plan-executor` |
| `HOKO_REVIEWER_MODEL` | model for `hoko-code-reviewer` |
| `HOKO_QA_MODEL` | model for `hoko-quality-assurance` |
| `HOKO_RESEARCH_MODEL` | model for `hoko-researcher` |
| `HOKO_JOURNAL_PATH` | journal root (default: `~/Obsidian Vaults/Personal/Journal`) |
| `HOKO_COMMIT_AUTO` | `1` = `hoko-commit` commits without confirming the message |
| `HOKO_BASE_BRANCH` | branch a pull request targets (default: `develop`) |
| `HOKO_PR_AUTO` | `1` = `hoko-pull-request` pushes and opens the PR without confirming |

A model left unset means that agent runs on the session's model. Models are
`provider/model-id`; `opencode models` lists them.

The journal root can also come from `~/.config/opencode/hoko.json`
(`{ "journalPath": "…" }`), which is what the Claude Code plugin used. Precedence:
`HOKO_JOURNAL_PATH` → `hoko.json` → the built-in default.

The plugin also exports `HOKO_ROOT`, `HOKO_JOURNAL_PATH` and `HOKO_PROMPT_FILE` (this
session's captured prompt) into every shell the agent runs.

## The workflow

One cycle, one Tab press:

```
Tab → plan                    grill → plan file → "approve?"
you: approved                 hoko_execute: journals, then runs execute-plan on build
build (automatic)             delegate → verify → review → commit, one step per cycle
                              → full gate → Status: complete → report journaled
```

Commands, all optional entry points:

```
/hoko/plan <request>          the planning protocol, from a command instead of a message
/hoko/execute-plan <path>     run a plan by hand — a fresh session, or an older plan
/hoko/commit                  commit the working tree to the message conventions
/hoko/research <question>     research an external question, file it under .ai/research/
/grill-me <topic>             get interrogated on anything, no plan required
```

### 1. Planning is what plan mode is

The protocol is the `plan` agent's own prompt (`agents/plan.md`), not something a
command bolts on: Tab into plan mode, type the request, and it grills you one question
at a time (the `grill-me` skill), reads the code, then writes
`<project>/.ai/plans/<YmdHis>-<slug>.md`, posts the step breakdown and asks you to
approve. Questions and exploration still get plain answers — the protocol starts when
you ask for work. A task too small to plan gets handed back instead of a plan file.

The plan agent writes that file through one permission exception the plugin adds, applied
even if you keep a `plan` block of your own in `opencode.json`: `edit` is denied except
`.ai/plans/*.md` (spelled relative, `*/`-prefixed and `**/`-prefixed, since opencode does
not document which form the matcher sees), the writing tools are switched back on so the
exception has something to act on, and `date`, `mkdir -p`, `git rev-parse`, `ls` and
`test -f` are pre-allowed so resolving the path never stalls on a prompt. Configure a
`plan` agent yourself and your prompt is kept — only the permissions and the plan-file
exception are layered on.

### 2. Approval hands off by itself

Say "approved" — or "go ahead", or anything that means yes — and the plan agent calls
the `hoko_execute` tool. That tool, not the model, does the switching:

1. files the plan and this cycle's original prompt in the journal, and remembers the
   entry it opened;
2. queues the plan, and when the turn ends runs `/hoko/execute-plan <path>` in the same
   session **on the `build` agent** (opencode's `session.command` API takes the agent to
   run as), with a toast so you can see it start.

So there is no Tab-to-build step and no command to remember, and build never starts from
a blank slate: it starts inside the execute-plan protocol with the plan path in hand. The
prompt box follows: the TUI keeps its own idea of the active agent and the API has no
setter for it, so the plugin walks it round with `agent_cycle` (it reads the primary
agents from `app.agents()` to know how far), leaving the indicator on Build where the run
is. That step is cosmetic — the run is on the build agent either way.

The conductor runs on whatever model the session was on when you approved, which is not
always the one you want reading every diff. `HOKO_BUILD_MODEL` pins it. It sets the
`build` agent's model like the other variables set theirs, so it applies to plain
build-mode chat too — the conductor and build mode are the same agent.
Ask for changes instead of approving and the plan file is edited in place at the same
path — nothing is journaled until you approve.

If you run opencode with `OPENCODE_EXPERIMENTAL_PLAN_MODE=1`, ignore its `plan_exit`
tool: that approves opencode's own plan workflow, which implements inline. The prompt
says so too.

### 3. Execution delegates every step

`/hoko/execute-plan` runs on `build` and works the plan one step per cycle: delegate the
step to `hoko-plan-executor` (cheaper model, its own context), read the diff yourself,
send it to the `hoko-code-reviewer` subagent — every step, unconditionally — then commit
via the `hoko-commit` skill. One commit per step. With `HOKO_COMMIT_AUTO=1` each of those
commits lands without stopping to confirm the message — the protected-branch check and
the gate still hold. The plan's `## Progress` checklist tracks how far the run got, so it
survives a compaction or a restart.

The gate is split so the loop stays cheap. Per step, `hoko-code-reviewer` runs the **fast
gate** — PHPStan and the unit tests only — behind the same call as the review; the
conductor re-runs nothing. Once every box is ticked, the `hoko-quality-assurance`
subagent runs the **full gate** once over the whole run — lint, PHPStan, the full suite
with coverage — fixes what it can, commits those fixes, and reports each gate and each
fix. A `not ready` verdict means the plan file does not turn `Status: complete`, and the
journal entry stays open.

A green gate is not an integration. Before the plan file turns complete, the run invokes
`hoko-pull-request`: if `origin` is GitHub it pushes the branch and opens a pull request
against `HOKO_BASE_BRANCH` (`develop` unless you say otherwise), with the run's closing
report as the PR body, so the PR and the journal entry say the same thing. On any other
remote — or none — the branch is simply left for you to integrate. Nothing in the
workflow merges: no `git merge` into the base branch, no `gh pr merge`, no auto-merge.
Without `HOKO_PR_AUTO=1` the push waits for you to confirm the base, branch and title;
`/hoko/pr` runs the same skill on its own for a branch outside a plan run.

Both protocols delegate outward rather than guessing: when a decision turns on something
outside the repo — what a pinned library version actually does, an API's semantics — they
launch `hoko-researcher` and cite its findings file instead of assuming or asking you to
go looking.

### 4. The journal is written by the tools, not by a reminder

Each cycle is one file under `<journal>/<project>/<timestamp>-<slug>.md`: the initial
prompt byte for byte, a full copy of the plan, and the run's final report.

- The plugin captures the first prompt of each cycle verbatim, before any model sees it,
  and retires it once filed so the next cycle captures its own.
- `hoko_execute` files the entry at approval. No model composes it — the tool runs
  `scripts/journal.py write` itself.
- The plan turning `Status: complete` closes it: the plugin takes the last message the
  run posted — by protocol the closing report — and appends it to the entry it opened for
  that plan, announcing it with a toast. A run that stopped short never sets
  `Status: complete`, so nothing is filed and the entry stays open.

Entry titles and filenames come from the plan's own `#` heading, or failing that the
first line of its `## Goal` — never from the plan's auto-generated filename. The project
is the git root, or the nearest ancestor with a `.git`, `.opencode` or `.claude`; the
home directory never counts, and an unresolvable project lands in `<journal>/unsorted/`.

### Two things opencode does on its own

Both of these are stock opencode 1.18 behaviour, not this plugin's:

- **A project `.opencode/` directory gets npm scaffolding.** For every config directory
  it finds, opencode writes a `.gitignore` (`node_modules`, `package.json`,
  `package-lock.json`, `bun.lock`, `.gitignore`) and background-installs
  `@opencode-ai/plugin` into it — roughly 60 MB of `node_modules`. There is no setting
  to switch it off, which is why plans live in `.ai/plans/` rather than
  `.opencode/plans/`: a project that never needs a `.opencode/` directory never gets
  one.
- **Claude Code files are picked up.** `~/.claude/CLAUDE.md` is loaded as instructions
  and `~/.claude/skills/*/SKILL.md` are loaded as skills. Left over Claude Code copies
  of this workflow will tell the model plans live in `.claude/plans/`, which fights the
  `.ai/plans/` convention. `OPENCODE_DISABLE_CLAUDE_CODE_PROMPT=1` and
  `OPENCODE_DISABLE_CLAUDE_CODE_SKILLS=1` turn the two pickups off.

## Layout

```
plugin/
  hoko.ts             registers everything; models from .env; the hoko_execute tool;
                      prompt capture, the handoff to build, and journaling
  test_hoko.ts        tests for the plugin's hooks and tool
agents/
  plan.md                 primary; replaces opencode's plan agent with the protocol:
                          grill → plan file → approve → hoko_execute
  hoko-plan-executor.md   subagent; implements one step, never commits
  hoko-researcher.md      subagent; external research, writes .ai/research/<stamp>-<slug>.md
  hoko-code-reviewer.md   subagent; reviews a step's diff via hoko-code-review,
                          plus the fast gate: PHPStan + unit tests
  hoko-quality-assurance.md subagent; the end-of-run full gate, fixes and commits
commands/
  grill-me.md
  hoko/{plan,execute-plan,commit,research,pr}.md
skills/
  grill-me/               the grilling protocol
  hoko-commit/            commit message conventions
  hoko-pull-request/      end of a run: push and open a PR against develop on GitHub
  hoko-code-review/       review standards + per-language reference guides
  hoko-api-developer/     JSON Schema + swagger.yml + versioned, grouped, named routes
  hoko-quality-assurance/ lint, PHPStan with no exceptions, coverage above 85%
  hoko-senior-php-developer/ no-comment self-explanatory PHP, objects over arrays,
                          typed collections, mirrored test tree
instructions/
  hoko.md                 standing rules the plugin adds to config.instructions —
                          git stops at the commit: never merge, never push, PR instead
scripts/
  journal.py              write | report
  test_journal.py         tests, against a throwaway journal root
```

Agents, commands and skills are plain opencode files — the plugin only reads their
frontmatter and body. `instructions/hoko.md` is different: it is appended to
`config.instructions`, so it is in context on every agent whether or not a skill is
invoked. That is where rules live that must hold in plain build-mode chat too — a skill
only binds once a model decides to load it, which is exactly when "just commit this"
turned into a local merge into `develop`.

The frontmatter parser covers scalars and nested maps (`permission:`, `tools:`), which is
all these files use; it is not a full YAML parser.

Two details worth knowing if you edit the agents: within a `permission` map opencode
evaluates the **last** matching rule, so broad patterns go first and narrow ones last;
and skill names are flat, which is why they are prefixed `hoko-` rather than namespaced
like the commands.

### PHP standards

Three skills carry the PHP conventions, and they trigger on their own descriptions
rather than through a command:

- **`hoko-api-developer`** — every JSON payload gets a JSON Schema under
  `res/schema/json/<project>/`, with shared shapes extracted into `components/` and
  reused by `$ref`; a `swagger.yml` at the project root references those files instead of
  inlining shapes; routes are versioned from `v1`, grouped by shared path, named, and
  carry their middleware on the group rather than per route.
- **`hoko-quality-assurance`** — the gate: lint, then PHPStan with an empty
  `ignoreErrors` and no inline ignore tags, then tests with coverage above 85% and
  rising. It finds the project's own commands rather than assuming tool names. It comes
  in two shapes — the fast gate (PHPStan + unit tests) that the reviewer runs per step,
  and the full gate that runs once at the end of a run or before a standalone commit.
- **`hoko-senior-php-developer`** — self-explanatory code with comments only for a
  non-obvious *why*, fully typed signatures that take and return objects instead of
  arrays, PSR naming (`Interface` suffix), collections built per element type that
  reject foreign types, and a `tests/Unit` tree that mirrors the application tree path
  for path with feature tests grouped by feature.

All three are framework-agnostic: they detect the stack and test tooling from the
project and express the rules in its idioms. `hoko-commit` invokes the quality gate
before drafting a message, and `hoko-code-review` points the reviewer at the other two,
so a plan run picks them up at both the review and the commit step. Inside a plan run
`hoko-commit` holds to the fast gate the reviewer already ran instead of starting the
full one; every other commit runs all three.

### Research

`hoko-researcher` answers one question from sources *outside* the repo — pinned-version
documentation, changelogs, specs — and writes `.ai/research/<YmdHis>-<slug>.md` with an
answer, evidence (claim, URL, what the page says), anything it inferred rather than
verified, and what remains open. It reports the path and at most five lines, so the
findings cost the caller almost no context and outlive the session.

Three ways it runs:

- `/hoko/research <question>` — the command names the subagent as its agent, so opencode
  turns the whole invocation into a subtask. Nothing runs in your main context.
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

## What changed from the Claude Code version

- Claude Code hooks (`UserPromptSubmit`, `PostToolUse`, `Stop`) become opencode plugin
  hooks (`chat.message`, `command.execute.before`, `tool.execute.after`, `shell.env`,
  `event`) plus the `hoko_execute` tool. Journaling used to be nudged by appending a
  reminder to a tool result and hoping the model acted on it; the plugin now writes both
  halves itself. opencode's `session.idle` event turns out to be the `Stop` equivalent
  the port was missing.
- The grilling protocol was injected by a hook on entering plan mode; it is now the
  `plan` agent's prompt, so plan mode grills whether you came in by Tab or by
  `/hoko/plan`.
- Approving a plan used to mean running the execute command yourself. `hoko_execute` now
  runs it for you, on the build agent, in the same session.
- Plans moved from `.claude/plans/` to `.ai/plans/`, and `execute-plan` gitignores
  `/.ai/` unless the repo already tracks it. Plans under the older `.opencode/plans/`
  and `.claude/plans/` layouts still resolve to their project when journaled.
- Skills are invoked by name through opencode's `skill` tool rather than as
  `/giata:<skill>` slash commands; the slash commands that remain are the workflow
  entry points.
- Code review is unconditional. The Claude Code version reviewed "proportional to the
  step", which meant the conductor decided — and a conductor on a cheap model skips it.
  Every step now goes to `hoko-code-reviewer`, which answers in one line on a trivial
  diff.
- `add-dynamic-pipelines` was GIATA-specific and did not come along.

## Tests

```sh
bun plugin/test_hoko.ts         # plugin: capture, the tool, the handoff, journaling
#   or: node --experimental-strip-types plugin/test_hoko.ts
python3 scripts/test_journal.py # journal: entries, titles, projects, reports, config
```

Both run against throwaway directories and never touch the real journal.

# Migrating hoko from opencode V1 to V2

The plugin code is already ported in this branch. Three things are left for you, because
V2's plugin API cannot express them on its own.

## Do these

### 1. Point the config entry at the plugin directory

`plugin` became `plugins`, and the value must be the **directory**, not `hoko.ts`:

```jsonc
// before
{ "plugin": ["file:///abs/path/to/hoko-opencode-plugin/plugin/hoko.ts"] }

// after
{ "plugins": ["file:///abs/path/to/hoko-opencode-plugin/plugin"] }
```

A path entry is loaded as a directory and V2 imports its `index.ts`. A path to a file is
rejected with `configured plugin path must be a directory`, and the plugin silently does
not load.

### 2. Install the agents

A V2 plugin has no `add` on the agent registry, so it cannot register agents at all. This
repo's `agents/*.md` are discovered from `~/.config/opencode/agents/` instead:

```sh
scripts/install-agents.sh
```

It symlinks each file, so editing one here stays live. Re-running is safe. Without this,
the `hoko-*` subagents do not exist. `plan` still works without the symlink because the
plugin applies this repo's `agents/plan.md` prompt to opencode's built-in plan agent.

### 3. Remove the V1 instructions entry, if you have one

If your `opencode.json` lists this repo's `instructions/*.md`, drop them: the plugin adds
them to every model request itself now, and listing them too would double them.

### 4. Reload and check

```sh
opencode service restart      # or `opencode reload` for a config-only change
opencode debug agents         # plan is patched; the hoko- agents are listed
```

Then smoke-test: Tab → Plan, ask for a change, approve it. Expect the plan to be filed
under `.ai/plans/`, a fresh session to open, and the run to start at step 1 with a
`hoko-plan-executor` subagent.

## What changed in behavior

V1 relied on four things V2 removed. Each has a replacement or is simply gone.

| V1 mechanism | V2 outcome |
| --- | --- |
| `config` hook registering agents | Agents are files; install step above |
| `config` hook appending to `instructions` | The plugin pushes them into every model request from the `context` hook — same effect |
| `tui.showToast` | The server plugin has no TUI API; `tui.ts` announces the run, and the git guard's "cut from the wrong base" warning arrives as a synthetic notice in the session |
| `tui.publish` moving the TUI to the run's fresh session, and `agent_cycle` moving the agent indicator | `tui.ts` listens for the run session's `hoko: run` marker, syncs it and navigates to it; the run still starts there |
| `shell.env` exporting `HOKO_PROMPT_FILE` | The V2 shell hook carries no session id. Nothing read it |
| A command naming an agent (`agent: hoko-researcher`) | Commands cannot name agents. `/hoko/research` now asks the current agent to delegate to `hoko-researcher`; `/hoko/plan`, `/hoko/task`, `/hoko/commit`, `/hoko/pr` and `/hoko/execute-plan` switch the session's agent explicitly |
| The plugin detecting a hand-written `plan` block | A `plan` agent with a system prompt is treated as the user's own; an empty one receives this repo's protocol. The permission exception is always layered on, and a `HOKO_*_MODEL` is authoritative when set |
| The plan agent's `tools:` map | V2 agents have no tool map; tool availability follows permissions |

## What the port changed beyond the API

The V2 port also replaced the conversational loop with a deterministic one. None of it is
required by the API; it is the workflow this branch ships, and the README carries the
detail.

- **The engine.** `scripts/` now owns what a run must not leave to memory: the plan lint
  at approval and before the loop, the plan's `## Progress` checklist and `progress.json`,
  the base commit, the step slice, the fast gate, the commit and the tick. One call,
  `step-commit.py`, runs the gate, commits and ticks, so a step cannot land half-done.
  A step gets no review of its own.
- **The task pipeline.** `/hoko/task` runs a task through Refine, Spec, Plan, Implement,
  QA and Review as a state machine (`scripts/task.py`), with automatic fix cycles and a
  loop limit, interrupting only for product decisions. It did not exist in V1.
- **The run display.** `plugin/status.ts` reads the newest `progress.json` and
  `plugin/tui.ts` appends the status line to both footers and the run pane to the sidebar.
  With no run in progress the line is the repository and branch alone.
- **The loop guard.** While a run is `in_progress`, the plugin denies the conductor any
  read or edit of a repository path outside the plans directory. The implementation work
  belongs to the subagents it launches; a denied call means a delegation was skipped.
- **Analytics and events.** Runs write gap-free JSON-line events under
  `.ai/runs/<run_id>/`. With `analyticsPath` set, a journal entry's sessions, invoice and
  event copies live in `<analyticsPath>/<project>/<entry>/` with an `entry.json` linking
  back to the journal entry. The invoice prices from opencode's reported per-response cost.

The settings loader (`scripts/settings.py`) now also reads `~/.config/opencode/hoko.json`
and carries the engine's keys — `analyticsPath`, `events`, `eventsDir`, `loopLimit`,
`planGate`, `efforts`, `crap`, `mutation`, `crapMax`, `mutationMin`, `pricing` and the
rest. `HOKO_*` in the environment still overrides every file, and the plugin exports all
of it into each shell, so the skills and the scripts read the same values.

`plugin/hoko.ts` now uses the V2 API: a plain default export with `setup(ctx)`, and
`ctx.tool.transform`, `ctx.tool.hook`, `ctx.shell.hook`, `ctx.session.hook`,
`ctx.event.subscribe`, `ctx.agent.transform`, `ctx.command.transform`,
`ctx.skill.transform`, `ctx.session.create/view/command/context/list`,
`ctx.session.switchAgent/prompt/synthetic/get`, and `ctx.model.list`. `index.ts` re-exports
it for the directory entrypoint, and `guard.ts` and `status.ts` are plain sibling modules.
It still imports nothing beyond node's standard library.

## Verified

- `docker compose run --rm test` — the whole suite: `bun plugin/test_hoko.ts` and every
  `scripts/test_*.py`.
- The plugin loads and patches the `plan` agent (`opencode debug agents` shows the edit
  exception, the shell pre-allows and `hoko_execute`), and the location emits
  `agent.updated` and `command.updated`.
- The run display registers its three slots where the build exposes them. The run itself
  does not depend on the display: the plan file and its `progress.json` carry the state
  the UI reads.

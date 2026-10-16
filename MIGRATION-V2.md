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
`plan` falls back to opencode's stock plan agent and the `hoko-*` subagents do not exist.

### 3. Remove the V1 instructions entry, if you have one

If your `opencode.json` lists this repo's `instructions/*.md`, drop them: the plugin adds
them to every model request itself now, and listing them too would double them.

### 4. Reload and check

```sh
opencode service restart      # or `opencode reload` for a config-only change
opencode debug agents         # plan is patched; the hoko- agents are listed
```

Then smoke-test: Tab → Plan, ask for a change, approve it. Expect the run to start at
step 1 with a `hoko-plan-executor` subagent in a fresh session.

## What changed in behavior

V1 relied on four things V2 removed. Each has a replacement or is simply gone.

| V1 mechanism | V2 outcome |
| --- | --- |
| `config` hook registering agents | Agents are files; install step above |
| `config` hook appending to `instructions` | The plugin pushes them into every model request from the `context` hook — same effect |
| `tui.showToast` | No TUI API. Handoff and journaling lines go to the opencode server log; the git guard's "cut from the wrong base" warning arrives as a synthetic notice in the session |
| `tui.publish` moving the TUI to the run's fresh session, and `agent_cycle` moving the agent indicator | No TUI API. The run's session is still created and the run still starts there; the screen does not follow it |
| `shell.env` exporting `HOKO_PROMPT_FILE` | The V2 shell hook carries no session id. Nothing read it |
| A command naming an agent (`agent: hoko-researcher`) | Commands cannot name agents. `/hoko/research` now asks the current agent to delegate to `hoko-researcher`; `/hoko/plan`, `/hoko/commit`, `/hoko/pr` and `/hoko/execute-plan` switch the session's agent explicitly |
| The plugin detecting a hand-written `plan` block | Not detectable in V2. The permission exception is always layered on, and a `HOKO_*_MODEL` only applies to an agent with no model of its own |
| The plan agent's `tools:` map | V2 agents have no tool map; tool availability follows permissions |

`plugin/hoko.ts` now uses the V2 API: a plain default export with `setup(ctx)`, and
`ctx.tool.transform`, `ctx.tool.hook`, `ctx.shell.hook`, `ctx.session.hook`,
`ctx.event.subscribe`, `ctx.agent.transform`, `ctx.command.transform`,
`ctx.skill.transform`, `ctx.session.create/view/command/context/list`,
`ctx.session.switchAgent/prompt/synthetic/get`, and `ctx.model.list`. It still imports
nothing beyond node's standard library.

The journaling scripts, the settings loader, the frontmatter parser and the git guard are
unchanged. `HOKO_*` settings all still apply.

## Verified

- `docker compose run --rm test` — the whole suite, 170 checks.
- The plugin loads in opencode 2.0.30 and patches the `plan` agent
  (`opencode debug agents` shows the edit exception, the shell pre-allows and
  `hoko_execute`), and the location emits `agent.updated` and `command.updated`.

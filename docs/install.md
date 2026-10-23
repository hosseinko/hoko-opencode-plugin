# Install

## What it needs

| | |
| --- | --- |
| opencode | 2.0 or newer — `opencode --version`. On V1 see [Upgrading](upgrading.md) |
| python3 | 3.9 or newer — the engine every run calls: the plan lint and filing, the checklist, the gates, the task pipeline, the invoice |
| git | runs commit each step, and the gates diff against a base |
| node modules | **none at runtime.** `plugin/hoko.ts` uses node's standard library only; the test suite needs `solid-js` |

There is nothing to build, and the plugin itself has no runtime dependencies: that is why
its tool takes no arguments, since declaring arguments would mean importing zod, and
importing zod would mean an install step. `bun` is needed only to run the plugin's own
tests, never at runtime, and that suite has one dependency — `solid-js`, pinned in
`package.json`, because `plugin/status.tsx` is the renderer half and needs a JSX runtime in
a plain process. Bun fetches the pinned version on the suite's first run, or `bun install`
does it up front.

One thing V2 changed: a plugin can no longer register agents, so this repo's
`agents/*.md` are installed as files (step 3). The server plugin also has no TUI API, so
the run display and the jump to the run's session live in `plugin/tui.ts`, the terminal
entrypoint V2 loads beside the server one. Everything else — commands, skills, the
standing instructions — is registered by the plugin as before.

## 1. Put the repo somewhere stable

opencode loads the plugin from an absolute path, so pick a home for this checkout and
leave it there:

```sh
git clone https://github.com/<you>/hoko-opencode-plugin.git
cd hoko-opencode-plugin && pwd
```

Keep that path — step 2 needs it.

## 2. Point opencode at the plugin

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

## 3. Install the agents

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

## 4. Configure it (optional)

```sh
cp hoko.json.example ~/.config/opencode/hoko.json
```

Every key is there with its default, and every default works: leave the file untouched and
every agent runs on the session's model, plans go to `.ai/plans/`, runs write their events
under `.ai/runs/`, the coverage floor is 85%, three fix cycles is the task pipeline's
limit, a PR targets `develop` where the repository has one, and nothing is journaled. The
table under [Configuration](configuration.md) says what each key does.

Keeping the file at `~/.config/opencode/hoko.json` rather than in the repo means a
`git pull` never touches your settings. `hoko.env` beside it is an optional override layer
and the place for the plugin-only switches; see [Configuration](configuration.md).

## 5. Reload opencode

V2 watches its config directories and reloads them, so a change to `opencode.json`, to
`hoko.json`, to `hoko.env`, or to a file that was already mounted usually lands on its
own; `opencode reload` forces it. A change to the *set* of plugins, or to the plugin's own
source, may need `opencode service restart`.

## 6. Check it took

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

## 7. Smoke-test it

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

## When something is off

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

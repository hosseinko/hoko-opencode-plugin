# Upgrading

## Updating

Pull (or edit) and reload opencode. That is the whole procedure: nothing is copied,
compiled or installed, so the files in this repo *are* the live workflow — the plugin is
loaded from `plugin/`, the agents are symlinks into `agents/`, and every run calls
`scripts/` in place. Editing any of them changes it everywhere on the next reload. A
syntax error in `plugin/hoko.ts` takes the whole thing down, so run the tests after
touching it.

## Upgrading from the conversational loop

This branch replaces the per-step review agents with the deterministic engine. Five things
change in an existing install:

1. **The plans layout grew a second shape.** A plan run still keeps one flat
   `<YYYYmmddHHMMSS>-<slug>.md` with its `<stem>.progress.json` sidecar beside it, so
   existing plans keep working and a half-finished run resumes from its `## Progress`
   checklist. A `/hoko/task` run now owns a folder, `.ai/plans/<YYYYmmdd-HHMM>-<slug>/`,
   holding its `progress.json`, `prompt.md`, stage hand-offs, `plan-NN.md` files and
   `report.md`. Run events go to `.ai/runs/<run_id>/events.jsonl`; both top folders are
   gitignored for you.
2. **Two agents retired.** The per-step gate agent and the second, stricter review at the
   end of a run are gone: `step-commit.py` runs the fast gate inside the commit, and
   `hoko-final-reviewer` is the single review of the whole branch. Those symlinks now point
   at deleted files, so prune them and re-install the rest:

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
   `crap`, `mutation`, `crapMax`, `mutationMin` and `pricing` are read from
   `hoko.json` and from `HOKO_*` variables; existing files need no edit, because every one
   has a working default. See [Configuration](configuration.md).

The checkout this repo lives in and the checkout opencode loads are not always the same
one: the live install is a separate clone at
`/Users/hossein.koozehgar/ai/plugins/hoko-opencode-plugin`, on branch `main`. Changes made
here reach it only after a `git pull` in that directory, and then only after opencode
reloads. Pull there before deciding an upgrade did not work.

## Migration from V1

V2 has three intentional breaking changes, and one of them is the plugin API: **a V1
plugin does not run in V2.** The plugin here has been ported, and its own workflow is the
one documented under `docs/`. What you have to do by hand:

1. **Re-point the plugin.** The `plugin` key becomes `plugins`, and the value becomes the
   `plugin` *directory* rather than `plugin/hoko.ts`. See [step 2](install.md#2-point-opencode-at-the-plugin).
2. **Install the agents.** A V2 plugin cannot add agents, so `agents/*.md` are discovered
   from `~/.config/opencode/agents/`. Run `scripts/install-agents.sh`. This is the step
   V1 did not have.
3. **Reload**, then check `opencode debug agents`.

The behaviour the V2 API forced to change is tabulated in
[MIGRATION-V2.md](../MIGRATION-V2.md).

`plugin/hoko.ts` was rewritten for the V2 API: `setup(ctx)` with `ctx.tool.transform`,
`ctx.tool.hook`, `ctx.shell.hook`, `ctx.session.hook`, `ctx.event.subscribe`,
`ctx.agent.transform`, `ctx.command.transform` and `ctx.skill.transform`. It still imports
nothing beyond node's standard library and its own sibling modules. The journaling
scripts, the settings loader and the frontmatter parser are the V2 versions in
`scripts/`, and `scripts/` as a whole is now the deterministic engine described under
[the workflow](workflow.md). `MIGRATION-V2.md` carries the same list with the details.


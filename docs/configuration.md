# Configuration

One file sets everything: `hoko.json`, a JSON object with one key per setting — the agent
models included. Copy [`hoko.json.example`](../hoko.json.example) to
`~/.config/opencode/hoko.json` and edit it. Every key sits in that file with its default,
so deleting a line is the same as leaving it at that default.

Settings resolve in five layers, each overriding the one before:

1. this repo's `hoko.json`
2. `~/.config/opencode/hoko.json`
3. this repo's `hoko.env`
4. `~/.config/opencode/hoko.env`
5. the real environment

The plugin and `scripts/settings.py` read those five in that order. Every `hoko.json` key
becomes the `HOKO_<UPPER_SNAKE>` variable of the same name — `planModel` →
`HOKO_PLAN_MODEL` — so one setting means one value on both sides. The plugin resolves them
at startup and exports them, plus `HOKO_ROOT`, into every shell an agent runs, which is how
the skills and the engine read the settings that apply to them. An empty string in a file
never overrides; only the real environment clears a value, so `HOKO_JOURNAL_PATH= opencode`
turns journaling off for one session.

The two `hoko.env` files remain a supported layer for machine-local overrides, and they are
where the plugin-only switches live — `HOKO_FRESH_SESSION`, `HOKO_BASE_BRANCH` and
`HOKO_PR_AUTO`, which `scripts/settings.py` does not read. `hoko.env.example` names those
with their defaults. V1 also exported `HOKO_PROMPT_FILE`; V2's shell hook carries no
session id, so it is gone, and nothing else read it.

| `hoko.json` key | Variable | Sets | Default |
| --- | --- | --- | --- |
| `planModel` | `HOKO_PLAN_MODEL` | model for the `plan` agent | the session's model |
| `buildModel` | `HOKO_BUILD_MODEL` | model for the `build` agent — the conductor of a run | the session's model |
| `executorModel` | `HOKO_EXECUTOR_MODEL` | model for `hoko-plan-executor` | the session's model |
| `reviewerModel` | `HOKO_REVIEWER_MODEL` | model for `hoko-code-reviewer`, on request | the session's model |
| `finalReview` | `HOKO_FINAL_REVIEW` | model for `hoko-final-reviewer`, the run's one review | the session's model |
| `qaModel` | `HOKO_QA_MODEL` | model for `hoko-quality-assurance` | the session's model |
| `researchModel` | `HOKO_RESEARCH_MODEL` | model for `hoko-researcher` | the session's model |
| `journalPath` | `HOKO_JOURNAL_PATH` | journal root | **unset — journaling is off** |
| `analyticsPath` | `HOKO_ANALYTICS_PATH` | where a run's sessions, invoice and event copies go | **unset — they stay in the journal entry** |
| `plansDir` | `HOKO_PLANS_DIR` | plans and task folders, relative to the repo root | `.ai/plans` |
| `events` | `HOKO_EVENTS` | append the run's events | on |
| `eventsDir` | `HOKO_EVENTS_DIR` | run event folders, relative to the repo root | `.ai/runs` |
| `loopLimit` | `HOKO_LOOP_LIMIT` | fix cycles a `/hoko/task` run may take, 0 to 10; 0 accepts the open findings unasked | `3` |
| `planGate` | `HOKO_PLAN_GATE` | ask Approve / Revise / Stop before a task's steps start | on |
| `specs` | `HOKO_SPECS` | the plan run's spec pass, and the task pipeline writing `specs/` instead of a local `spec.md` | off |
| `crap` | `HOKO_CRAP` | the CRAP index in the full gate | on |
| `crapMax` | `HOKO_CRAP_MAX` | the CRAP index's ceiling | `30` |
| `mutation` | `HOKO_MUTATION` | mutation testing in the full gate | on |
| `mutationMin` | `HOKO_MUTATION_MIN` | the mutation score floor | `70` |
| `pricing` | `HOKO_PRICING` | rate overrides for the invoice, laid over `scripts/pricing.json` | `{}` |
| `coverageMin` | `HOKO_COVERAGE_MIN` | the full gate's coverage floor, in percent | `85` |
| `commitAuto` | `HOKO_COMMIT_AUTO` | `true` = `hoko-commit` commits without confirming the message | off |
| `loopGuard` | `HOKO_LOOP_GUARD` | deny the conductor its own reads and edits while a run is in progress | on |

Three switches have no `hoko.json` key because only the plugin reads them, so they live in
`hoko.env` or the environment: `HOKO_FRESH_SESSION` (approval starts the run in a fresh
session and `tui.ts` moves the screen to it; `0`, `false`, `no` or `off` hand off in the
approval session, default on), `HOKO_BASE_BRANCH` (the branch playing the `develop` role,
default `develop`, else the remote's default branch) and `HOKO_PR_AUTO` (`1` = push and open
the PR without confirming, default off). The plugin maps any key it finds, so naming one of
them in `hoko.json` also reaches it.

Models are `provider/model-id`, and a model key may carry an opencode variant as
`provider/model-id#variant`. `opencode models` lists them. A model key overrides whatever
model the agent would otherwise use, including a model you set yourself in `opencode.json`
or in the agent file; an unset one leaves the agent alone. Every other key is read by the
scripts and never touches an agent's frontmatter.

The reference reaches its agent exactly as written. A `#variant` on it is your choice about
the ref, so it is passed through unchanged on both sides: the plugin resolves each agent's
model from its key, and the task pipeline names the stage's model on a spawn or step
action.

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

## Docs

| Page | What it covers |
| --- | --- |
| [Install](docs/install.md) | what it needs, the seven setup steps, the smoke test, troubleshooting |
| [Configuration](docs/configuration.md) | `hoko.json` and `hoko.env`, the five layers, every key with its default |
| [The workflow](docs/workflow.md) | planning, approval, execution, `/hoko/task`, the run display, the journal, analytics and the invoice |
| [Layout](docs/layout.md) | the repository tree, and the standing rules in `instructions/` |
| [Development](docs/development.md) | making it yours, the stack skills, research, tests |
| [Upgrading](docs/upgrading.md) | updating a checkout, upgrading from the conversational loop, migrating from V1 |
| [MIGRATION-V2.md](MIGRATION-V2.md) | the V1 → V2 plugin-API migration in full |

## What it needs

| | |
| --- | --- |
| opencode | 2.0 or newer — `opencode --version`. On V1 see [Upgrading](docs/upgrading.md) |
| python3 | 3.9 or newer — the engine every run calls: the plan lint and filing, the checklist, the gates, the task pipeline, the invoice |
| git | runs commit each step, and the gates diff against a base |
| node modules | **none at runtime.** `plugin/hoko.ts` uses node's standard library only; the test suite needs `solid-js` |

One file sets everything. Copy [`hoko.json.example`](hoko.json.example) to
`~/.config/opencode/hoko.json`; every key is there with its default, and every default
works. [Configuration](docs/configuration.md) says what each one does.

The standing rules the plugin adds to every model request are the files in
`instructions/` — `hoko.md`, `communication.md`, `docker-first.md` and
`read-exclusion.md`. [Layout](docs/layout.md) says what each one carries.

# Layout

```
plugin/
  index.ts            the server entry point V2 imports: re-exports hoko.ts's default
  hoko.ts             registers everything; settings from hoko.json / hoko.env; the
                      hoko_execute tool — lint, file, fresh session, handoff; prompt
                      capture; usage collection and the run's close
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
  read-exclusion.md       what search never walks into: the excluded folders named once,
                          reached only by a path the caller names, and the repository
                          read before the web
scripts/
  settings.py             the hoko.json / hoko.env config the plugin and the scripts share
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
  run_tests.py            the parallel runner: scripts/ plus the Go script suite
hoko.json.example         every hoko.json key with its default
hoko.env.example          the plugin-only switches and machine overrides, commented
opencode.json.example     the one line that registers the plugin
MIGRATION-V2.md           the V1 → V2 plugin-API migration
docs/                     the long-form documentation the README indexes
  install.md              setup steps, smoke test, troubleshooting
  configuration.md        hoko.json / hoko.env, the five layers, every key
  workflow.md             planning, approval, execution, /hoko/task, display, journal
  layout.md               this tree, and the standing rules in instructions/
  development.md          making it yours, the stack skills, research, tests
  upgrading.md            updating, the conversational-loop upgrade, the V1 migration
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

# Development

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

## Stack-specific skills

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
`python3 scripts/run_tests.py` discovers two roots and runs them in parallel: every
`scripts/test_*.py` suite, one per engine script — settings, the plan format and lint,
progress, the gates, the step commit, events and analytics, journaling, the invoice, the
task pipeline, the follow-up renderer, the docs and the manifests — and the Go script suite
under `skills/hoko-senior-go-developer/scripts/`, which `unittest discover` over `scripts/`
cannot see. `--start-dir <dir>` narrows discovery to that one folder and drops the other
root. `make test` is the same runner; `make test-serial` runs the same two roots one after
another (`--jobs 1`) when a failure needs readable output.

Run a single Python suite by path — `python3 scripts/test_settings.py` — one suite through
the runner with `python3 scripts/run_tests.py --pattern test_settings.py`, and the
TypeScript file with `bun plugin/test_hoko.ts`.

Every one runs against throwaway directories and never touches a real journal.

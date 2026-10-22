---
name: hoko-quality-assurance
description: >-
  The quality gate for any stack — lint before committing, static analysis clean with no suppression
  entries or inline ignore comments, and test coverage held above the configured floor and climbing,
  or, on a legacy project that has never met the floor, held against its own baseline.
  Use at the end of a plan run, before a standalone commit, when a lint/static-analysis/coverage
  failure needs handling, or when asked whether a change is ready to commit.
---

# Quality assurance

Three gates, run in this order: lint → static analysis → tests with coverage. Work does
not ship while any of them is red.

Two more checks, CRAP index and mutation testing, run after the coverage gate at
the end of a plan run (sections 4 and 5). They grade debt, not blockers: a finding there
never turns the gate red.

Nothing here names a tool. The gate is the same in every language; which binary runs it
is the project's business, and section 0 is how you find out.

## Fast gate, full gate

The three gates do not all have to run at the same moment, and running them all on
every commit of a long run is what makes the run drag. Two shapes:

- **Fast gate** — static analysis plus the unit tests alone, no coverage flag. This is
  what runs per step inside a plan run, via `step-commit.py`, with no review alongside
  it — the run's one review runs separately, once, in `hoko-final-reviewer` at the end. It is
  cheap enough to run on a two-line diff and catches the errors worth catching early.
  The analyser rules below apply in full: a diff that buys a green run with a
  suppression entry, a baseline, a lowered level or an inline ignore comment is red,
  not green.
- **Full gate** — all three, in order, including the whole suite with coverage. This
  runs once when the run is finished, in the `hoko-quality-assurance` subagent, and on
  any standalone commit outside a plan run.

Everything below describes the full gate. The fast gate is sections 2 and 3 of it, with
the suite narrowed to units and coverage deferred. Sections 4 and 5 belong to the full
gate of a plan run only.

## 0. Find the project's own commands first

Do not assume tool names. Start from `python3 "${HOKO_ROOT}/scripts/commands.py"
--root <repo>` — it resolves `lint`, `analyse`, `unit`, `suite`, `coverage` and `mutation` from the
project's own build-tool targets, manifest scripts, CI workflow and, failing those, an
ecosystem default gated on the tool actually being present, wrapping a PHP command
through whatever container the repo runs PHP-FPM in. A gate it returns `null` for has no
command it could find; only then fall back to reading the project's manifest and its
script block, the analyser's and test runner's config files, and any CI workflow
yourself — that last one is the most reliable manual answer, because it is what the
project actually enforces. Where to look, by ecosystem:

| | Manifest / scripts | Analyser | Tests | Lint / format |
| --- | --- | --- | --- | --- |
| PHP | `composer.json` | `phpstan.neon(.dist)`, `psalm.xml` | `phpunit.xml(.dist)`, `pest.php` | `.php-cs-fixer.php`, `pint.json` |
| JS / TS | `package.json` | `tsconfig.json` | `vitest`/`jest` config | `eslint` config, `biome.json` |
| Python | `pyproject.toml`, `tox.ini` | `mypy.ini`, `pyrightconfig.json` | `pytest.ini`, `[tool.pytest]` | `[tool.ruff]`, `setup.cfg` |
| Go | `go.mod`, `Makefile` | `go vet`, `.golangci.yml` | `go test ./...` | `gofmt`, `golangci-lint` |
| Rust | `Cargo.toml` | `cargo clippy` | `cargo test` | `cargo fmt` |
| Java / Kotlin | `pom.xml`, `build.gradle` | SpotBugs, Detekt | Surefire, `gradle test` | Checkstyle, `ktlint` |
| Ruby | `Gemfile`, `Rakefile` | Sorbet, Steep | `rspec`, `rake test` | `.rubocop.yml` |
| .NET | `*.csproj`, `*.sln` | analyzers, `.editorconfig` | `dotnet test` | `dotnet format` |

A `Makefile`, `justfile` or `Taskfile.yml` in the root usually wraps all three, and
those wrappers are the commands to prefer — they carry the flags the project wants.

State the three commands you settled on before running them, so a wrong one is visible
rather than silent. If a gate has no command at all, say so — an absent gate is a
finding, not a pass.

## 1. Lint

Run the project's formatter/linter in check mode and fix what it reports. Formatting is
never left for "a follow-up commit", and a formatting run is never mixed into a
behaviour commit — format first, commit that separately if it is noisy, then the change.

## 2. Static analysis

Run the project's type checker or static analyser at the level and strictness the
project configures. If the project has no level set, propose the highest level the code
passes and treat lowering it as a regression.

Two rules:

- **No exceptions in the configuration.** The suppression list stays empty — PHPStan's
  `ignoreErrors`, a Psalm `issueHandler` override, an ESLint `rules: off` for the
  changed files, a `golangci-lint` exclusion, a per-module `ignore_errors` in mypy — and
  the baseline file is not the place to hide a new error. Add no entry, regenerate no
  baseline and lower no level, `strict` setting or ruleset to make a run pass.
- **No inline ignore comments.** No `@phpstan-ignore`, `@psalm-suppress`, `@ts-ignore`,
  `@ts-expect-error`, `# type: ignore`, `# noqa`, `//nolint`, `#[allow(...)]`,
  `eslint-disable` or equivalent — unless the error is genuinely unfixable in code (a
  third-party stub that lies, a framework signature you do not control). When that is
  truly the case: use the narrowest possible form, on the single line it applies to,
  with one comment saying which external thing forces it. Anything else is a code
  problem wearing an annotation, and the fix is the code — better types, a value object
  instead of a bare map, a narrowed signature, a guard clause.

If you cannot make the analyser pass without an exception, stop and report it as a
blocker rather than silencing it.

## 3. Tests and coverage

Run the full suite. It must be green, and no test is deleted, skipped, marked incomplete
or weakened to get there. A test that fails is telling you something.

Coverage is graded against the configured floor, which the plugin carries:

```bash
python3 "${HOKO_ROOT}/scripts/settings.py" coverageMin
```

### Which coverage mode applies

Not every codebase can meet that floor, and a legacy project with 40% coverage and no
seams does not become testable because a gate says so. So the floor is graded in one of
three modes, and the mode is detected — never configured, never chosen by hand.

**A. No suite, or no coverage tooling.** The coverage gate is absent. Report it as an
absent gate and move on, with no number you did not measure. Lint and static analysis still run at full strength. If the project has
a test runner but no coverage configuration, say which is missing. New code added by
this change still gets a test wherever a runner exists at all.

**B. Legacy mode — the project has never met the floor.** The floor does not block. Two
checks replace it, both in section 3b.

**C. Strict mode — the project meets the floor, or has met it before.** The floor
blocks, and the configured threshold stays where it is. Code
you touched should come out at or near full coverage; a change that drags the number
down is not ready.

The distinction between B and C is *has never met the floor*, not *is below it right
now*. A project that once passed 85% and now measures 60% has regressed — that is red,
not legacy. The baseline file below is what remembers the difference.

### 3a. The baseline file

Legacy mode needs a number to measure against, so it keeps one in the project at
`.ai/coverage-baseline`:

```json
{
  "last": 62.4,
  "best": 64.1,
  "measured": "2026-09-15",
  "command": "composer test:coverage"
}
```

- `best` is the highest coverage ever measured here. **Legacy mode applies while
  `best` is below the floor** — once a run measures at or above it, `best` crosses over
  and the project is in strict mode permanently.
- `last` is the previous measurement, and what the no-regression check compares against.
- The file is machine-measured state, not source: `.ai/` is ignored, so it is never
  committed.

Create it the first time a full gate runs on a project below the floor, and say in the
report that you created it. Update `last` and `best` on every full gate. Never edit it
by hand to make a run pass — that is the same move as regenerating an analyser baseline.

### 3b. The two legacy-mode checks

**Do not make it worse.** Measured coverage must be at or above `last`. A drop is red,
and the fix is a test, not a new baseline. Report the gap to `best` too when the number
has drifted down over several runs without any single run failing.

**Cover what you touched.** Every line this change added or modified is covered. Take
the changed lines from `git diff <range>` and intersect them with the coverage report —
most tools emit one that carries line data (clover, cobertura, lcov, `coverage.json`).
Where the tool cannot produce line-level output, fall back to naming, for each function
or class the diff added, the test that exercises it. Either way, name what is uncovered
rather than reporting a percentage.

Untestable surroundings are a finding, not an excuse and not a blocker. When a change
cannot be covered because the code around it has no seam — a constructor doing I/O, a
static call to a live service, a 600-line method — say so, name the seam that is
missing, and let the commit proceed. Introducing that seam is its own piece of work,
worth a plan, not something to smuggle into an unrelated change.

### In every mode

Coverage percentage alone is not the gate. Lines executed by a test with no meaningful
assertion count for nothing — for what a real test looks like in a PHP project, see
`hoko-senior-php-developer`; elsewhere, match the assertion style of the suite you are
adding to. A legacy project earns no discount here: its thin coverage is precisely why
the tests that do exist have to assert something.

## 4. CRAP index

CRAP scores a method by its complexity against how little of it the tests run:
`comp² × (1 − cov)³ + comp`, with `cov` as a fraction. A complex method nobody tests
scores high. It runs on a plan run's full gate only, and only when the plan selected it
(see *Which checks run* below).

**Scope: the diff, not the project.** Only methods and functions overlapping a line
changed in `<Base>..HEAD` are scored. There is no project-wide CRAP pass.

**Threshold:**

```bash
python3 "${HOKO_ROOT}/scripts/settings.py" crapMax
```

A method scoring above it is a finding. Score from the coverage report section 3
already produced — a clover or cobertura XML, written with the project's own coverage
command if the run did not leave one:

```bash
python3 "${HOKO_ROOT}/scripts/crap.py" --report <clover.xml|cobertura.xml> --range <Base>..HEAD --max <crapMax> --root <repo>
```

It prints `{"status": "ok"|"absent", "findings": [...]}`. A per-method `crap` value in
the report is used as it stands; otherwise the formula above is computed from the
report's `complexity` and line coverage.

**Absent gate.** `status: absent`, a coverage report with no complexity data, or no
coverage report at all means CRAP was not measured. Report it as an absent gate and say
which of those it was. It is not a pass.

**Findings file.** When anything exceeds the threshold, write
`.ai/qa/crap/<YYYY-MM-DD>-<plan-slug>.md`, the plan slug being the plan file's
basename without `.md`. When nothing does, write no file. Header, then one entry per
finding, worst first:

```markdown
Status: open
Plan: <absolute plan path>
Range: <Base>..HEAD
Threshold: <crapMax>
Measured: <YYYY-MM-DD>

## <file>:<line> <method>
- Complexity: <n>
- Coverage: <n>%
- CRAP: <score>
- Fix: <the obvious one — the test that covers the uncovered branches, or the split that lowers complexity>
```

## 5. Mutation testing

Mutation testing changes the code in small ways and checks that some test fails. A
mutant that survives is behaviour no assertion pins down. It runs on a plan run's full
gate only, and only when the plan selected it.

**Scope: the files the run changed**, not the whole project. Take the command
`commands.py` resolved as `mutation` and narrow it to the run's diff with whatever the
tool offers: Infection `--git-diff-lines --git-diff-base=<Base>`, Stryker
`--mutate <changed files>`, mutmut the changed paths, `cargo mutants --in-diff <diff
file>`, and so on. Give it the timeout the tool supports, so a slow suite ends the check
rather than the run.

**Threshold:**

```bash
python3 "${HOKO_ROOT}/scripts/settings.py" mutationMin
```

The measure is the covered-code mutation score indicator (MSI) as a percentage — the
share of mutants in covered code that the tests killed. An MSI below `mutationMin` is
debt, and each surviving mutant in the changed files is a finding.

**Absent gate.** `commands.py` returning `null` for `mutation`, or a tool that cannot
run here, means mutation was not measured. Report an absent gate and name the cause.
Installing a mutation tool is out of scope here: plan mode offers the install and, on
the user's yes, the plan carries a step that adds it — into the project's dev or test
image when the project runs in Docker, never on the host.

**Never suppress to pass.** Do not exclude mutators, add ignore annotations, raise
timeouts to hide a survivor, narrow the scope past the run's diff, or lower
`mutationMin`. A surviving mutant is closed by an assertion, and that belongs to the
follow-up plan, not to this check.

**Findings file.** When the MSI is below the threshold, write
`.ai/qa/mutation/<YYYY-MM-DD>-<plan-slug>.md`. When it is not, write no file. Same
header as the CRAP file, `Threshold:` being `mutationMin` and `Measured:` the MSI:

```markdown
Status: open
Plan: <absolute plan path>
Range: <Base>..HEAD
Threshold: <mutationMin>
Measured: <MSI>%

## <file>:<line> <mutator>
- Diff: <the surviving mutation, as a one-line before/after>
- Missing assertion: <what a test would have to assert to kill it>
```

## Which checks run

Sections 4 and 5 are not both always on. The plan decides:

- The plan's `QA:` header line names the checks this run gets: `QA: crap, mutation`,
  `QA: crap`, `QA: mutation` or `QA: none`. Run exactly those.
- A check the line omits is reported as `off`. That is a decision, not an absent gate.
- A plan with no `QA:` line, an older plan, falls back to the settings: run each check
  whose setting prints `true`, and report the other as `off`.

```bash
python3 "${HOKO_ROOT}/scripts/settings.py" crap
python3 "${HOKO_ROOT}/scripts/settings.py" mutation
```

The `.ai/qa/` files are local, like the rest of `.ai/`. Never stage or commit them.

## Reporting

Report one compact block — the exact command run and its result for each of the three
gates, plus the coverage number, which mode it was graded in, and the direction it
moved. In legacy mode also report the baseline it was compared against, whether the
baseline file was created or updated, and anything in the diff that came out uncovered.
If anything is red, report the failure and what it would take to fix it; do not report
"ready to commit".

On a plan run's full gate, add one line each for CRAP and mutation: `off`, absent with the
cause, or the measure against its threshold with the findings file's path when one was
written. CRAP or mutation findings alone are debt, never red: the verdict is
`green with debt`, with the findings files named, and the work is still ready to commit.

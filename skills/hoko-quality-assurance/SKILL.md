---
name: hoko-quality-assurance
description: >-
  The quality gate for any stack — lint before committing, static analysis clean with no suppression
  entries or inline ignore comments, and test coverage held above the configured floor and climbing.
  Use at the end of a plan run, before a standalone commit, when a lint/static-analysis/coverage
  failure needs handling, or when asked whether a change is ready to commit.
---

# Quality assurance

Three gates, run in this order: **lint → static analysis → tests with coverage**. Work
does not ship while any of them is red.

Nothing here names a tool. The gate is the same in every language; which binary runs it
is the project's business, and section 0 is how you find out.

## Fast gate, full gate

The three gates do not all have to run at the same moment, and running them all on
every commit of a long run is what makes the run drag. Two shapes:

- **Fast gate** — static analysis plus the unit tests alone, no coverage flag. This is
  what runs per step inside a plan run, in `hoko-code-reviewer`, alongside the review of
  that step's diff. It is cheap enough to run on a two-line diff and catches the errors
  worth catching early. The analyser rules below apply in full: a diff that buys a green
  run with a suppression entry, a baseline, a lowered level or an inline ignore comment
  is red, not green.
- **Full gate** — all three, in order, including the whole suite with coverage. This
  runs once when the run is finished, in the `hoko-quality-assurance` subagent, and on
  any standalone commit outside a plan run.

Everything below describes the full gate. The fast gate is sections 2 and 3 of it, with
the suite narrowed to units and coverage deferred.

## 0. Find the project's own commands first

Do not assume tool names. Read the project's manifest and its script block, the
analyser's and test runner's config files, and any CI workflow — that last one is the
most reliable answer, because it is what the project actually enforces. Where to look,
by ecosystem:

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

Two hard rules:

- **No exceptions in the configuration.** The suppression list stays empty — PHPStan's
  `ignoreErrors`, a Psalm `issueHandler` override, an ESLint `rules: off` for the
  changed files, a `golangci-lint` exclusion, a per-module `ignore_errors` in mypy — and
  the baseline file is not the place to hide a new error. Never add an entry, never
  regenerate the baseline, and never lower the level, `strict` setting or ruleset to
  make a run pass.
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

Run the full suite plus coverage. **Coverage must be above the configured floor** —
`HOKO_COVERAGE_MIN`, 85% when unset (the plugin exports it into every shell, so
`printf '%s' "$HOKO_COVERAGE_MIN"` reads it). That is a floor, not a target, and the
direction is always up:

- Never lower the configured threshold to make a run pass.
- Code you touched in this change should come out at or near full coverage; a change
  that drags the number down is not ready.
- Never delete, skip, mark incomplete, or weaken an assertion to get green. A test
  that fails is telling you something.
- Coverage percentage alone is not the gate. Lines executed by a test with no
  meaningful assertion count for nothing — for what a real test looks like in a PHP
  project, see `hoko-senior-php-developer`; elsewhere, match the assertion style of the
  suite you are adding to.

If the project has no coverage tooling configured, report that and give the actual
number once it does; do not claim a percentage you did not measure.

## Reporting

Report one compact block — the exact command run and its result for each of the three
gates, plus the coverage number and the direction it moved. If anything is red, report
the failure and what it would take to fix it; do not report "ready to commit".

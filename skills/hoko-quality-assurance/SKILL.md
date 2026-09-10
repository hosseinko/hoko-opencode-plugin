---
name: hoko-quality-assurance
description: >-
  Quality gate for PHP projects — lint before committing, PHPStan clean with no ignoreErrors entries
  in the neon file and no inline ignore tags, and test coverage held above 85 percent and climbing.
  Use at the end of a plan run, before a standalone commit, when a lint/static-analysis/coverage
  failure needs handling, or when asked whether a change is ready to commit.
---

# Quality assurance

Three gates, run in this order: **lint → static analysis → tests with coverage**. Work
does not ship while any of them is red.

## Fast gate, full gate

The three gates do not all have to run at the same moment, and running them all on
every commit of a long run is what makes the run drag. Two shapes:

- **Fast gate** — PHPStan plus the unit tests alone, no coverage flag. This is what
  runs per step inside a plan run, in `hoko-code-reviewer`, alongside the review of
  that step's diff. It is cheap enough to run on a two-line diff and catches the errors
  worth catching early. The PHPStan rules below apply in full: a diff that buys a green
  run with an `ignoreErrors` entry, a baseline, a level drop or an inline ignore tag is
  red, not green.
- **Full gate** — all three, in order, including the whole suite with coverage. This
  runs once when the run is finished, in the `hoko-quality-assurance` subagent, and on
  any standalone commit outside a plan run.

Everything below describes the full gate. The fast gate is sections 2 and 3 of it, with
the suite narrowed to units and coverage deferred.

## Find the project's own commands first

Do not assume tool names. Read `composer.json` (its `scripts` block above all),
`phpstan.neon` / `phpstan.neon.dist`, `phpunit.xml` / `phpunit.xml.dist`, `pest.php`,
`.php-cs-fixer.php`, `pint.json`, and any CI workflow, and use exactly the commands the
project defines. State the three commands you settled on before running them, so a
wrong one is visible rather than silent. If a gate has no command at all, say so — an
absent gate is a finding, not a pass.

## 1. Lint

Run the project's formatter/linter in check mode and fix what it reports. Formatting is
never left for "a follow-up commit", and a formatting run is never mixed into a
behaviour commit — format first, commit that separately if it is noisy, then the change.

## 2. PHPStan

Run at the level the project configures; if the project has no level set, propose the
highest level the code passes and treat lowering it as a regression.

Two hard rules:

- **No exceptions in the neon file.** `ignoreErrors` stays empty, and the baseline file
  is not the place to hide a new error. Never add an entry, never regenerate the
  baseline, and never drop the level to make a run pass.
- **No inline ignore tags.** No `@phpstan-ignore`, `@phpstan-ignore-next-line`,
  `@psalm-suppress` or equivalent — unless the error is genuinely unfixable in code (a
  third-party stub that lies, a framework signature you do not control). When that is
  truly the case: use the narrowest possible tag, on the single line it applies to, with
  one comment saying which external thing forces it. Anything else is a code problem
  wearing an annotation, and the fix is the code — better types, a value object instead
  of an array, a narrowed signature, a guard clause.

If you cannot make PHPStan pass without an exception, stop and report it as a blocker
rather than silencing it.

## 3. Tests and coverage

Run the full suite plus coverage. **Coverage must be above 85%** — that is a floor, not
a target, and the direction is always up:

- Never lower the configured threshold to make a run pass.
- Code you touched in this change should come out at or near full coverage; a change
  that drags the number down is not ready.
- Never delete, skip, `markTestIncomplete`, or weaken an assertion to get green. A test
  that fails is telling you something.
- Coverage percentage alone is not the gate — see `hoko-senior-php-developer` for what
  a real test looks like. Lines executed by a test with no meaningful assertion count
  for nothing.

If the project has no coverage tooling configured, report that and give the actual
number once it does; do not claim a percentage you did not measure.

## Reporting

Report one compact block — the exact command run and its result for each of the three
gates, plus the coverage number and the direction it moved. If anything is red, report
the failure and what it would take to fix it; do not report "ready to commit".

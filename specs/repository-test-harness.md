---
id: SPEC-005
title: Repository test harness
covers:
  - scripts/run_tests.py
  - Makefile
  - Dockerfile
  - plugin/test-jsx/**
---

# Repository test harness

## Context

The repository's suites run from two entry points: `bun run test` runs the TypeScript
suite and then the Python runner, and `make test` / `make test-serial` run the Python
runner over all its roots in parallel or one unit at a time. A *unit* is the smallest
thing a worker runs whole. The harness's claim is that both entry points cover every
suite the repository ships, that the suite resolves its imports without a network fetch,
and that the summary's total is what the units actually ran.

## Requirements

- **REQ-1** `bun run test` shall complete with no network access, resolving every module the TypeScript suite imports from dependencies the repository declares and the test image installs.
- **REQ-2** The test image shall install the dependencies `package.json` declares from the committed lockfile.
- **REQ-3** The TypeScript suite shall compile the renderer through a JSX runtime the repository ships, so running the suite needs no React package.
- **REQ-4** The Python runner shall discover every file the test pattern matches under `scripts/` and under every `skills/*/scripts/` directory that holds a match.
- **REQ-5** If a skill's `scripts/` directory holds no matching file, then the runner shall discover nothing there and shall not fail.
- **REQ-6** The runner shall run a suite it discovers outside `scripts/` whole, in one interpreter call from that suite's own directory.
- **REQ-7** `make test-serial` shall run the same roots as `make test`, one unit at a time.
- **REQ-8** The runner shall count a whole-suite unit by the number its own output reports, in a `Ran N tests` line, else by the number of `ok`/`FAIL` check lines it printed, else as one.
- **REQ-9** The runner's summary shall report the total as the sum of the counts its units reported.
- **REQ-10** If a unit fails, then the runner shall print that unit's output and exit non-zero.
- **REQ-11** While `--pattern` names a glob, the runner shall apply it to every root; while `--start-dir` names a directory, the runner shall discover in that directory alone and drop the other roots.

## Acceptance criteria

```gherkin
Feature: Repository test harness

  Scenario: the serial target runs the skill suite the parallel run runs
    Given a Python suite under skills/hoko-senior-go-developer/scripts
    When make test-serial runs
    Then that suite runs and its own tests are counted

  Scenario: a skill suite contributes its own count, not one
    Given a skill suite whose output holds "Ran 120 tests in 1.2s"
    When the runner finishes
    Then the summary adds 120 for that suite

  Scenario: the suite resolves its imports with no network
    Given the test image built from the committed lockfile
    When the TypeScript suite runs in a container with no network
    Then every check passes
```

## Design notes

The default roots are `scripts/` plus each `skills/*/scripts` directory that holds a
pattern match, sorted; `test-serial` is the same runner with `--jobs 1`. A skill suite is
one unit whose reported count is read from its output (`Ran N tests`, else one `ok`/`FAIL`
line per check, else 1), which is why the size check that compares a unit's ran count to
its discovered size applies only to split units. The image copies `package.json` and
`bun.lock` to `/` and installs there, so the bind-mounted working tree does not hide
`node_modules` from `/work`. `plugin/test-jsx/jsx-runtime.ts` is the automatic runtime
bun compiles `status.tsx` through under the test runner; opencode still compiles the same
JSX through its Solid plugin.

## Open questions

- The test runtime emits plain `{type, props}` nodes and the suite walks them, treating solid-js's `For` and `Show` as values, so the assertions cover the renderer's element structure rather than Solid's compiled reactive output. Whether that catches every break a real render would — a reactive accessor read twice, for instance — is unverified.

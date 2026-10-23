---
id: SPEC-004
title: Quality gate command resolution
covers:
  - scripts/commands.py
---

# Quality gate command resolution

## Context

A run's quality gate runs the command the repository already uses, so it needs no
judgement about how this stack is tested. Six gates are resolved — `lint`, `analyse`,
`unit`, `suite`, `coverage`, `mutation` — from what the repository names, in a fixed
order, and a gate nothing names stays absent rather than being assembled from a guess. The
*ecosystem* is detected from the repository's manifest: php, node, python, rust, go or
java.

## Requirements

- **REQ-1** The resolver shall report the six gates as a JSON object, each the command the repository names for it or `null`.
- **REQ-2** The resolver shall take the first source that names a gate, in this order: a build-tool target, a manifest script block, a CI workflow `run` line, the ecosystem default.
- **REQ-3** If no source names a gate, then the resolver shall report `null` for it.
- **REQ-4** The resolver shall return an ecosystem default only when the tool the default names is present under that ecosystem's own check.
- **REQ-5** For a node repository, the resolver shall return `npx tsc --noEmit` for `analyse` only when the repository has a `tsconfig.json` and `typescript` is installed.
- **REQ-6** For a node repository, the resolver shall count `typescript` as installed when `node_modules/.bin/tsc` is a file or `package.json` lists it under `dependencies` or `devDependencies`.
- **REQ-7** When a PHP command is constructed by the resolver rather than copied out of the repository, the resolver shall wrap it to run in a container.
- **REQ-8** Go and Java gates shall be `null` except `mutation`, which shall use go-mutesting for Go and the pitest invocation when the build file names pitest for Java.
- **REQ-9** The resolver shall print the object and exit 0 without running any gate.

## Acceptance criteria

```gherkin
Feature: Quality gate command resolution

  Scenario: a tsconfig alone claims no typecheck gate
    Given a node repository with a tsconfig.json
    And no typescript in package.json and no node_modules/.bin/tsc
    When the repository's gates are resolved
    Then analyse is null

  Scenario: a declared typescript names the typecheck gate
    Given a node repository with a tsconfig.json and typescript in devDependencies
    When the repository's gates are resolved
    Then analyse is npx tsc --noEmit

  Scenario: a gate nothing names stays absent
    Given a python repository with no lint target, script block or CI line
    And no ruff section in pyproject.toml
    When the repository's gates are resolved
    Then lint is null
```

## Design notes

`resolve()` walks the four sources per gate and returns the first command; a PHP command
from the manifest or default tier is passed through the container wrapper, while a build
target or CI line is copied verbatim because the repository already wrote it for its own
environment. The node analyse condition was `tsconfig.json` alone, which made a repository
that carries a tsconfig for a transform claim a typecheck it cannot run: a `tsconfig.json`
added for a JSX transform is exactly the case that must resolve to `null`.

## Open questions

- The node analyse default reads only the repository's own `node_modules` and manifest, while the python and rust defaults also consult the path. Whether a globally installed `tsc` should name the gate is not settled.

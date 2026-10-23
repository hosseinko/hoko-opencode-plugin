---
id: SPEC-003
title: Plugin settings resolution
covers:
  - plugin/hoko.ts
  - plugin/status.ts
  - plugin/status.tsx
---

# Plugin settings resolution

## Context

The plugin reads its settings from files rather than from a model's memory: a pair of
`hoko.json` files and a pair of `hoko.env` files, one of each pair in the checkout and one
in the machine's opencode config directory, with the real environment above them all. The
*repo root* is `HOKO_REPO_ROOT` when it is set and the plugin's own checkout otherwise.
The *machine config directory* is `<home>/.config/opencode`, and *home* is the home the
process was given, not the one the machine was started with.

## Requirements

- **REQ-1** The plugin shall resolve the machine config directory as `<home>/.config/opencode`, where home is `HOME` when it is set and the operating system's home directory otherwise.
- **REQ-2** The plugin shall resolve the machine config directory each time it reads settings, so a `HOME` the process is given after the plugin loaded selects the machine files from that home.
- **REQ-3** The plugin shall read `hoko.json` from the repo root and then from the machine config directory, and a key both files name shall take the machine file's value.
- **REQ-4** The plugin shall read `hoko.env` from the repo root and then from the machine config directory, and a variable either file sets shall sit above every `hoko.json` value.
- **REQ-5** While a `HOKO_*` variable is set in the process environment, the plugin shall use its value ahead of all four files, and an empty one shall clear the value a file set.
- **REQ-6** If a settings file is missing or malformed, then the plugin shall take no value from it and shall keep the defaults in place.
- **REQ-7** The guard and the display shall take the plans directory from the same settings reader, so the run the display shows is the run the guard arms from.
- **REQ-8** When no hoko-plan agent is installed, the plugin shall warn with the agents directory under the same resolved machine config directory.
- **REQ-9** The plugin shall default the plans directory to `.ai/plans`, with a leading `./` removed and trailing slashes trimmed.

## Acceptance criteria

```gherkin
Feature: Plugin settings resolution

  Scenario: a HOME given to the process after the plugin loaded decides the machine file
    Given the plugin loaded while HOME named one directory
    When settings are read after HOME is changed to a directory whose .config/opencode/hoko.json names a plans directory
    Then the display and the guard use that plans directory

  Scenario: the machine's hoko.json outranks the checkout's
    Given both hoko.json files name a plans directory
    When settings are read
    Then the plans directory is the machine file's
```

## Design notes

`plugin/hoko.ts` holds the one reader, `settings()`, and the machine directory is a
function called per read rather than a constant evaluated at load, because `os.homedir()`
is cached at process start in some runtimes. The five layers are the checkout's
`hoko.json`, the machine's `hoko.json`, the checkout's `hoko.env`, the machine's
`hoko.env`, then the process environment. The display calls the reader at render time
(`plugin/status.tsx`) and passes `HOKO_PLANS_DIR` into `statusView`; the guard passes the
same value into `activeRun`, which is why one read serves both.

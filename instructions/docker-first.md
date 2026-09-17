# Docker first

This laptop has no language runtime installed on it and does not get one. Every
runtime, toolchain and package manager a task needs comes from a container.

## Never install

No `brew install`, `apt-get`, `dnf`, `pacman`, no `nvm`, `fnm`, `asdf`, `mise`,
`pyenv`, `sdkman`, `rustup`, no `curl … | sh` installer, no `npm install -g`, and no
version bump of a runtime that is already there. "It is only a small install" is not a
reason, and neither is an expired token of patience with a container.

## Never run project work on the host

Tests, lint, builds, generators, scaffolding and one-off scripts run in a container for
node, npm, npx, pnpm, yarn, bun, php, composer, go, gofmt, golangci-lint, govulncheck,
ruby, bundler, rust, cargo, java, maven, gradle, dotnet, elixir, mix, deno, terraform
and anything else of that shape.

## How

- `docker compose run --rm <service>` when the project has a compose file, and write a
  minimal compose file plus Dockerfile when it does not. Mount the working tree and run
  the command from inside it, so the artefacts are the ones in the repo.
- Otherwise `docker run --rm -v "$PWD":/work -w /work <image> <command>`.
- Take the newest version the project supports that also publishes a `linux/arm64`
  image, and check the registry at use time rather than assuming a tag exists. A compose
  file you write records the tag you verified; this rule pins nothing.

## When docker cannot do it

Daemon not running, image will not pull, no arm64 variant published: say what failed and
stop. Installing a runtime to get past it is not one of the options.

## Carve-outs

`python3` and `bun`, when they are already on the host, stay usable for this plugin's
own tooling: `plugin/test_hoko.ts`, `scripts/test_journal.py` and
`skills/hoko-senior-go-developer/scripts/test_go_scripts.py`. Nothing else. A Python
project is a project like any other — its dependencies, tests and scripts go in a
container too. If bun is absent, run the plugin's TypeScript test in a `bun` container
rather than installing it.

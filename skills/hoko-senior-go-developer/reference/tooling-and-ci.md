# Tooling and CI

Formatting, linting, static analysis, vulnerability scanning and the pipeline that gates a
Go change, with the commands and the versions of the tools that run them.

Versions verified on 2026-09-17: Go **1.27.1**, golangci-lint **v2.13.2**, staticcheck
**2026.2.1** (`v0.8.1`), govulncheck **`golang.org/x/vuln v1.8.0`**, gotestsum **v1.13.0**.
These move; re-check before pinning. `[community]` —
[golangci-lint releases](https://github.com/golangci/golangci-lint/releases/tag/v2.13.2),
[staticcheck releases](https://github.com/dominikh/go-tools/releases),
[govulncheck versions](https://pkg.go.dev/golang.org/x/vuln?tab=versions),
[gotestsum releases](https://github.com/gotestyourself/gotestsum/releases)

## `gofmt` is the floor

- `gofmt` is the canonical formatter distributed with Go and formats syntax only.
  `[official]` — [pkg.go.dev/cmd/gofmt](https://pkg.go.dev/cmd/gofmt)
- The golangci-lint v2 formatter settings are `simplify` (maps to `gofmt -s`) and
  `rewrite-rules` (maps to `-r` rules). `[community]` —
  [golangci-lint formatters configuration](https://golangci-lint.run/docs/formatters/configuration/)
- Run `gofmt -l .` in a check: it lists the files that are not formatted and prints nothing
  when they all are, so a non-empty list is the failure signal. `[official]` —
  [pkg.go.dev/cmd/gofmt](https://pkg.go.dev/cmd/gofmt)
- In golangci-lint v2, `gci`, `gofmt`, `gofumpt`, `goimports`, `golines` and `swaggo` are
  **formatters**, not linters: they moved to a top-level `formatters` section and the
  dedicated `golangci-lint fmt` command applies them. `formatters.enable` defaults to `[]`,
  which means standard Go formatting. `[community]` —
  [golangci-lint formatters](https://golangci-lint.run/docs/formatters),
  [configuration file](https://golangci-lint.run/docs/configuration/file/)
- The tools differ in scope: `goimports` is `gofmt` plus import add/remove/group,
  `gofumpt` is a strict backwards-compatible superset of `gofmt`, and `gci` orders imports
  by sections (`standard`, `default`, `prefix(...)`, `localmodule`, …). `[community]` —
  [golangci-lint formatters configuration](https://golangci-lint.run/docs/formatters/configuration/)
- Which to enable is a team style decision, not a Go-team or golangci-lint prescription.
  This skill takes `gofmt` as the floor, with `gofumpt` and `gci` as formatters. `gci`
  overlaps `goimports`, so enable one or the other; `gofumpt` subsumes `gofmt`. `[contested]` —
  [golangci-lint formatters](https://golangci-lint.run/docs/formatters)

## golangci-lint v2

- v2 requires `version: "2"` (the only accepted value) and does not parse a v1 config: it
  fails with "you are using configuration v1 with golangci-lint v2" because the v2 binary
  has no v1 parser. Convert with `golangci-lint migrate`. `[community]` —
  [migration guide](https://golangci-lint.run/docs/product/migration-guide),
  [issue #5610](https://github.com/golangci/golangci-lint/issues/5610),
  [discussion #5774](https://github.com/golangci/golangci-lint/discussions/5774)
- The structure is `linters.default` (`standard` | `all` | `none` | `fast`, default
  `standard`), `linters.enable`/`linters.disable`, `linters.settings` and
  `formatters.settings`. `gosimple` and `stylecheck` were merged into `staticcheck`.
  `[community]` — [configuration file](https://golangci-lint.run/docs/configuration/file/),
  [migration guide](https://golangci-lint.run/docs/product/migration-guide)
- The `standard` default set is exactly **`errcheck`, `govet`, `ineffassign`,
  `staticcheck`, `unused`** — the only linters tagged `groups: ["standard"]`. `[community]` —
  [linters_info.json](https://raw.githubusercontent.com/golangci/golangci-lint/main/docs/data/linters_info.json)
- Start a new project from `default: standard` and add correctness linters:
  `bodyclose`, `noctx`, `contextcheck`, `errorlint`, `copyloopvar` (autofix), and
  `modernize` (since v2.6.0) for Go-version modernizations. `gosec` for security and
  `revive` for style beyond `staticcheck` are optional. `copyloopvar`, `errorlint`,
  `bodyclose`, `noctx` and `contextcheck` are not part of `modernize`.
  `[community]` — [linters list](https://golangci-lint.run/docs/linters/)
- v2.13.2 bundles `honnef.co/go/tools v0.8.1`, the same release as standalone staticcheck
  2026.2.1. `[community]` —
  [v2.13.2 changelog](https://github.com/golangci/golangci-lint/releases/tag/v2.13.2)
- Pin a specific golangci-lint version in CI. `linters.default: all` or an upstream linter
  upgrade can break every build at once. `[community]` —
  [install in CI](https://golangci-lint.run/docs/welcome/install/ci/)

## The ordered check pipeline

A module check runs these four commands, in order, and stops treating the run as failed
only when none of them reports a problem. Formatting runs first so a formatting diff is
not buried under lint output.

1. `gofmt -l .` — a non-empty file list is a failure. `[official]` —
   [pkg.go.dev/cmd/gofmt](https://pkg.go.dev/cmd/gofmt)
2. `go vet ./...` — all vet analyzers; a non-zero exit is a failure. `[official]` —
   [pkg.go.dev/cmd/vet@go1.27.1](https://pkg.go.dev/cmd/vet@go1.27.1)
3. `golangci-lint run` — the configured linters; a non-zero exit is a failure.
   `[community]` — [golangci-lint](https://golangci-lint.run/docs/configuration/file/)
4. `govulncheck ./...` — reachable vulnerabilities; a non-zero exit is a failure. The
   JSON, SARIF and OpenVEX output modes always exit 0, so the text mode is the one to gate
   on. `[official]` —
   [pkg.go.dev/golang.org/x/vuln/cmd/govulncheck](https://pkg.go.dev/golang.org/x/vuln/cmd/govulncheck)

[`../scripts/go_check.py`](../scripts/go_check.py) runs exactly these four commands in this
order, skipping a tool that is not installed instead of failing the run.

## `go vet`

- `go vet ./...` runs all vet analyzers by default; it is normally invoked through `go` and
  the results are "guidance only" — a heuristic correctness gate, not a proof.
  `[official]` — [pkg.go.dev/cmd/vet@go1.27.1](https://pkg.go.dev/cmd/vet@go1.27.1)
- Go 1.27 added the `stdversion` analyzer to the subset `go test` runs by default. It
  reports uses of standard-library symbols that are too new for the Go version in force in
  the file, as determined by the `go` directive in `go.mod` and the file's build tags, so a
  test on `go 1.24` that calls the 1.27-only `httptest.NewTestServer` fails vet.
  `[official]` — [Go 1.27 release notes](https://go.dev/doc/go1.27),
  [pkg.go.dev/cmd/vet@go1.27.1](https://pkg.go.dev/cmd/vet@go1.27.1)

## staticcheck

- The tool's own guidance is to run `staticcheck ./...` in addition to `go vet ./...`.
  It provides 150+ checks with few false positives. `[community]` —
  [staticcheck.dev/docs](https://staticcheck.dev/docs/)
- golangci-lint embeds staticcheck, and in v2 `staticcheck` absorbs `gosimple` and
  `stylecheck`. Running it only inside golangci-lint is fine for most teams; running it
  standalone lets you pin staticcheck independently and use its own CI action.
  `[community]` — [migration guide](https://golangci-lint.run/docs/product/migration-guide),
  [staticcheck CI](https://staticcheck.dev/docs/running-staticcheck/ci/github-actions/)
- staticcheck 2026.2 added Go 1.27 support and disabled `SA5011` ("it is unclear whether it
  will be enabled again"), so a standalone run and the bundled copy can differ in check
  coverage. `[community]` — [staticcheck 2026.2 notes](https://staticcheck.dev/changes/2026.2/)

## govulncheck

- govulncheck does reachability analysis over source or a binary's symbol table against the
  Go vulnerability database, so it reports only vulnerabilities that can actually be called,
  unlike a plain CVE scan. `[official]` — [go.dev/security/vuln](https://go.dev/security/vuln/)
- Usage is `govulncheck ./...`, with `-mode binary`, `-show traces|verbose`, and JSON, SARIF
  or OpenVEX output. It exits 0 with no vulnerabilities and non-zero with them, except the
  JSON, SARIF and OpenVEX modes, which always exit 0. `[official]` —
  [pkg.go.dev/golang.org/x/vuln/cmd/govulncheck](https://pkg.go.dev/golang.org/x/vuln/cmd/govulncheck)
- Documented limits: conservative handling of function-pointer and interface calls produces
  false positives, `reflect` and `unsafe` calls are invisible (false negatives), binary mode
  omits the call graph and can report unreachable code, and there is no silencing mechanism.
  `[official]` — [pkg.go.dev/golang.org/x/vuln/cmd/govulncheck](https://pkg.go.dev/golang.org/x/vuln/cmd/govulncheck)
- In CI, `golang/govulncheck-action@v1` (the README calls it experimental) or
  `go run golang.org/x/vuln/cmd/govulncheck@latest ./...` both work. `[community]` —
  [govulncheck-action](https://github.com/golang/govulncheck-action)

## gotestsum

- gotestsum wraps `go test -json` and adds formatted output, a summary, `--junitfile`,
  `--jsonfile`, `--rerun-fails`, `--watch` and `gotestsum tool slowest`. `[community]` —
  [pkg.go.dev/gotest.tools/gotestsum](https://pkg.go.dev/gotest.tools/gotestsum)
- It earns its place only when you need JUnit XML or reruns of flaky tests. For plain CI
  logs, `go test -json` covers most of the parsing need; it gained build-error JSON in Go
  1.24 and an `OutputType` field in Go 1.27. `[community]` — the gotestsum docs above,
  `[official]` — [Go 1.27 release notes](https://go.dev/doc/go1.27)
- Its maintenance is quiet: v1.13.0, published 2025-09-11, was still the latest release on
  2026-09-17, about a year without a tag. No maintenance intent beyond the last release was
  verified. `[community]` —
  [gotestsum releases](https://github.com/gotestyourself/gotestsum/releases)

## Pin tool versions

- Since Go 1.24 a `tool` directive in `go.mod` tracks executable tools. Add one with
  `go get -tool golang.org/x/tools/cmd/stringer`, run it with `go tool stringer`, upgrade
  all with `go get tool`, install all with `go install tool`. Those requirements take part
  in minimal version selection and are covered by `go.sum`. `[official]` —
  [Go 1.24 release notes](https://go.dev/doc/go1.24),
  [managing dependencies](https://go.dev/doc/modules/managing-dependencies)
- `go run pkg@version` pins a version inline without adding it to `go.mod`; `go run` and
  `go tool` results are cached. `[official]` —
  [Go 1.24 release notes](https://go.dev/doc/go1.24)
- In GitHub Actions, pin the action major (`actions/setup-go@v7`,
  `golangci/golangci-lint-action@v9`) and pin the tool versions through `go.mod` tool
  directives or explicit `@version`/`version:` inputs. `setup-go` caches modules and build
  outputs by default, keyed on `go.mod` unless `cache-dependency-path` is set, and honors
  the `toolchain` directive. `[community]` — [actions/setup-go](https://github.com/actions/setup-go),
  [golangci-lint-action releases](https://github.com/golangci/golangci-lint-action/releases)

## CI pipeline shape

This ordering and split is a synthesis, not a single documented recipe. `[community]` —
[install in CI](https://golangci-lint.run/docs/welcome/install/ci/)

- One job: checkout, `setup-go` on a matrix of `stable` and `oldstable` (1.27.x and 1.26.x
  under the two-latest-majors support policy), then build, vet, lint, test, coverage and
  vulnerability scan as separate steps so a failure is attributable. `[community]` —
  [install in CI](https://golangci-lint.run/docs/welcome/install/ci/)
- Steps: `go build ./...` → `go vet ./...` → pinned golangci-lint → `go test -race -coverprofile=coverage.out -covermode=atomic ./...` → govulncheck → optional staticcheck or gotestsum for JUnit. `[community]` —
  [install in CI](https://golangci-lint.run/docs/welcome/install/ci/)
- `-race` in CI is a community convention, not a rule the Go team states. `[community]` —
  [Go race detector](https://go.dev/doc/articles/race_detector)
- Let `setup-go` and `golangci-lint-action` handle caching; do not cache by hand.
  `[community]` — [actions/setup-go](https://github.com/actions/setup-go),
  [golangci-lint-action releases](https://github.com/golangci/golangci-lint-action/releases)
- The supported toolchain set follows the two-major policy: 1.27 and 1.26 are supported,
  1.25 is not. `[official]` — [Go release history](https://go.dev/doc/devel/release)

## Pre-commit hooks

- golangci-lint publishes `.pre-commit-hooks.yaml` with `golangci-lint` (runs
  `--new-from-rev HEAD --fix` on modified files), `golangci-lint-full` (whole module, for
  CI), `golangci-lint-fmt` and `golangci-lint-config-verify`. `[community]` —
  [.pre-commit-hooks.yaml](https://raw.githubusercontent.com/golangci/golangci-lint/main/.pre-commit-hooks.yaml)
- The modified-files hook will not catch whole-program findings such as `unused`, so CI
  remains the source of truth. Hooks are client-side and skippable, so treat them as a
  convenience, not the gate. `[community]` —
  [.pre-commit-hooks.yaml](https://raw.githubusercontent.com/golangci/golangci-lint/main/.pre-commit-hooks.yaml)
- The Go tree also ships a simple `gofmt -l` hook under `misc/git/`. `[official]` —
  [go/misc/git](https://go.googlesource.com/go/+/refs/heads/master/misc/git/)

## Example `.golangci.yml` (v2)

```yaml
version: "2"

linters:
  default: standard
  enable:
    - bodyclose
    - contextcheck
    - copyloopvar
    - errorlint
    - modernize
    - noctx

formatters:
  enable:
    - gofmt
    - gofumpt
    - gci
```

`version: "2"` is mandatory and a v1 config will not load. `default: standard` keeps the
five default linters; the `enable` list adds the correctness linters from above. `gofmt`
is kept as the explicit floor even though `gofumpt` subsumes it, and `gci` is enabled
without `goimports` because they overlap. `[community]` —
[configuration file](https://golangci-lint.run/docs/configuration/file/)

## Scripts

- [`../scripts/go_check.py`](../scripts/go_check.py) — the ordered pipeline above; a
  missing tool prints `skipped:` and the rest still run.
- [`../scripts/go_test.py`](../scripts/go_test.py) — `go test ./... -coverprofile` plus
  `go tool cover -func` for the total, and the packages with Go files but no test file.
- [`../scripts/go_scaffold.py`](../scripts/go_scaffold.py) — create a library, CLI or
  service layout with the `.golangci.yml` above; `--dry-run` prints the paths.

## Sources

- [pkg.go.dev/cmd/gofmt](https://pkg.go.dev/cmd/gofmt)
- [pkg.go.dev/cmd/vet@go1.27.1](https://pkg.go.dev/cmd/vet@go1.27.1)
- [Go 1.24 release notes](https://go.dev/doc/go1.24)
- [Go 1.27 release notes](https://go.dev/doc/go1.27)
- [Go release history](https://go.dev/doc/devel/release)
- [Go Modules Reference — managing dependencies](https://go.dev/doc/modules/managing-dependencies)
- [Go vulnerability management](https://go.dev/security/vuln/)
- [govulncheck documentation](https://pkg.go.dev/golang.org/x/vuln/cmd/govulncheck)
- [govulncheck-action](https://github.com/golang/govulncheck-action)
- [gotestsum documentation](https://pkg.go.dev/gotest.tools/gotestsum)
- [gotestsum releases](https://github.com/gotestyourself/gotestsum/releases)
- [staticcheck documentation](https://staticcheck.dev/docs/)
- [staticcheck 2026.2 notes](https://staticcheck.dev/changes/2026.2/)
- [staticcheck releases](https://github.com/dominikh/go-tools/releases)
- [staticcheck GitHub Actions](https://staticcheck.dev/docs/running-staticcheck/ci/github-actions/)
- [golangci-lint formatters](https://golangci-lint.run/docs/formatters)
- [golangci-lint formatters configuration](https://golangci-lint.run/docs/formatters/configuration/)
- [golangci-lint configuration file](https://golangci-lint.run/docs/configuration/file/)
- [golangci-lint migration guide](https://golangci-lint.run/docs/product/migration-guide)
- [golangci-lint linters list](https://golangci-lint.run/docs/linters/)
- [golangci-lint install in CI](https://golangci-lint.run/docs/welcome/install/ci/)
- [golangci-lint v2.13.2 release](https://github.com/golangci/golangci-lint/releases/tag/v2.13.2)
- [golangci-lint issue #5610](https://github.com/golangci/golangci-lint/issues/5610)
- [golangci-lint discussion #5774](https://github.com/golangci/golangci-lint/discussions/5774)
- [golangci-lint pre-commit hooks](https://raw.githubusercontent.com/golangci/golangci-lint/main/.pre-commit-hooks.yaml)
- [linters_info.json](https://raw.githubusercontent.com/golangci/golangci-lint/main/docs/data/linters_info.json)
- [golangci-lint-action releases](https://github.com/golangci/golangci-lint-action/releases)
- [actions/setup-go](https://github.com/actions/setup-go)
- [Go race detector](https://go.dev/doc/articles/race_detector)
- [go/misc/git](https://go.googlesource.com/go/+/refs/heads/master/misc/git/)

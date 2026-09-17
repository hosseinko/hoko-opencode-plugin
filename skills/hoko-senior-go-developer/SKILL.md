---
name: hoko-senior-go-developer
description: >-
  Opinionated Go conventions — top-level packages and `internal/` with no `pkg/`, errors
  wrapped once with `%w` and read with `errors.Is`/`errors.As`, the stdlib `net/http`
  `ServeMux` by default, hand-written fakes over generated mocks, structured `log/slog`,
  `gofmt` as the floor, and generics only where they remove real duplication. Use when
  writing, refactoring or reviewing Go code: packages, modules, services, CLIs, tests,
  error handling, concurrency.
---

# Senior Go developer

Detect the module's `go` directive, the Go version CI runs, and the conventions already in
the project, and work in its idioms. Where the project's house style contradicts a rule
here, the project wins for consistency — say so in the review rather than following the
older pattern silently.

This file is the index. The baseline below holds for every Go task; the routing table
points at the topic file that carries the detail.

## Baseline

- `gofmt` is the floor, not a preference `[official]`; `gofumpt` and `gci` run as
  golangci-lint v2 `formatters`, never as hand edits `[community]`.
- Top-level packages, `internal/` for anything not exported, `cmd/` only with two or more
  binaries, and no `pkg/`. `internal` is compiler-enforced; `pkg/` is not. `[contested]`
- Wrap only what the API commits to exposing: `%w` exposes the chain, `%v` hides it
  `[official]`; "wrap once, at the layer that adds information" is a community heuristic
  `[community]`. Compare sentinels with `errors.Is` and extract types with `errors.As` or
  `errors.AsType` (1.26). `panic` is for programmer error or unrecoverable init only; never
  `log.Fatal` in a library. `[official]`
- `context.Context` is the first parameter and is never stored in a struct; every
  goroutine has an exit `[official]`; `-race` runs in CI as a community convention
  `[community]`.
- Stdlib `net/http` `ServeMux` by default. chi only when middleware or route grouping
  genuinely demand it; gin and echo are not the default guidance. `[contested]`
- Hand-written fakes by default. testify `assert`/`require` are accepted; `testify/mock`
  and mockery only where a wide generated surface makes hand-writing worse. `[contested]`
- Generics are not a default: a type parameter is earned by removing real duplication,
  not applied speculatively. `[official]`
- Structured logging comes from `log/slog`, from the stdlib. `[official]`
- Vendoring stays off unless a hermetic or offline build requires it. `[contested]`

## Routing

| Topic | Read |
| --- | --- |
| Supported releases, the `go` directive, the citation legend | [current-go.md](reference/current-go.md) |
| Library, CLI and service layouts; `internal/`, `cmd/`, `go.work` | [project-layout.md](reference/project-layout.md) |
| `go.mod`/`go.sum` hygiene, MVS, vendoring, semantic import versioning | [dependency-management.md](reference/dependency-management.md) |
| godoc comments, README, changelog, SemVer, `doc.go` | [documentation-hygiene.md](reference/documentation-hygiene.md) |
| Naming, receivers, interfaces, embedding, zero values, generics | [coding-conventions.md](reference/coding-conventions.md) |
| Wrapping, sentinels, `errors.Is`/`errors.As`, `errors.Join`, panic policy | [error-handling.md](reference/error-handling.md) |
| Goroutines, `context`, channels vs mutexes, `-race`, loop variables | [concurrency.md](reference/concurrency.md) |
| Aliasing, `defer` in loops, typed nil, allocations, the PHP-to-Go traps | [performance-and-pitfalls.md](reference/performance-and-pitfalls.md) |
| Table-driven tests, fakes, fuzzing, benchmarks, coverage, `synctest` | [testing.md](reference/testing.md) |
| `ServeMux`, middleware, timeouts, graceful shutdown, JSON errors | [http-and-api.md](reference/http-and-api.md) |
| gofmt/goimports/gofumpt, golangci-lint v2, govulncheck, CI | [tooling-and-ci.md](reference/tooling-and-ci.md) |

---
name: hoko-senior-go-developer
description: >-
  Opinionated Go conventions — top-level packages and `internal/` with no `pkg/`, errors
  wrapped only where the API commits to exposing the chain (`%w` exposes, `%v` hides), read
  with `errors.Is`/`errors.As`, the stdlib `net/http` `ServeMux` by default, hand-written
  fakes over generated mocks, structured `log/slog`, `gofmt` as the floor, and generics only
  where they remove real duplication — plus a Go-version-gated catalogue of modern idioms,
  profiling and diagnostics (pprof, `go tool trace`, benchstat), observability (slog, request
  IDs, metrics, tracing, health endpoints) and a list of anti-patterns that are never the
  fix. Use when writing, refactoring or reviewing Go code: packages, modules, services, CLIs,
  tests, error handling, concurrency, performance, production debugging.
---

# Senior Go developer

Detect the module's `go` directive, the Go version CI runs, and the conventions already in
the project, and work in its idioms. Where the project's documented house style contradicts
a rule here, the house style wins for consistency (see step 5 below).

This file is the index: the baseline holds for every Go task, and the routing table points
at the topic file that carries the detail.

## Baseline

- `gofmt` is the floor, not a preference `[official]`; `gofumpt` and `gci` run as
  golangci-lint v2 `formatters`, never as hand edits `[community]`.
- Top-level packages, `internal/` for anything not exported, `cmd/` only with two or more
  binaries — except a service or mixed repository carrying non-Go assets, which keeps its
  commands under `cmd/` even with one — and no `pkg/`. `internal` is compiler-enforced;
  `pkg/` is not. `[contested]`
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
- After raising the `go` directive, run `go fix ./...` so the modernizers apply the new
  idioms `[official]`; see [tooling-and-ci.md](reference/tooling-and-ci.md#go-fix-modernizers).
- Vendoring stays off unless a hermetic or offline build requires it. `[contested]`

## Before writing Go

1. Read the `go` directive in `go.mod` (and the toolchain CI runs). It decides which idioms
   are available; see [current-go.md](reference/current-go.md#version-gated-behaviour).
2. Open [modern-idioms.md](reference/modern-idioms.md). Every row carries the minimum
   version it needs; apply the rows at or below the directive and none above it.
3. In the code you write or change, use the modern idiom even where the surrounding code
   still uses the older pattern, which is what training data over-represents, not what the
   project asked for. `[community]`
4. Do not rewrite code you are not otherwise touching. List the other modernization
   opportunities you saw in the report, or point at `go fix ./...`, and leave them for a
   change of their own. `[community]`
5. If the project's documented house style (a style guide, a lint rule, a `CONTRIBUTING`
   note) forbids a modern idiom, follow the house style in the code you touch and say so in
   the review. Older nearby code alone is not a house style.
6. Check the result against the list below before handing it back.

## Never the fix

Each of these is a common wrong answer; write the replacement. Where the replacement needs
a newer Go than the directive allows, use the older form named in the linked file.

| Never | Instead |
| --- | --- |
| A goroutine per item with no limit `[community]` | Bound it: `errgroup.SetLimit`, `wg.Go` behind a semaphore, or a worker pool — [concurrency.md](reference/concurrency.md) |
| `wg.Add(1)` / `defer wg.Done()` written by hand (1.25+) `[official]` | `wg.Go(func() { ... })` — [concurrency.md](reference/concurrency.md) |
| `time.Sleep` to wait for a goroutine in a test `[community]` | `testing/synctest` (1.25+), or wait on a channel or `WaitGroup` — [testing.md](reference/testing.md#testingsynctest) |
| `interface{}` (1.18+) `[official]` | `any` — [modern-idioms.md](reference/modern-idioms.md) |
| `sort.Slice` / `sort.Ints` (1.21+) `[community]` | `slices.SortFunc` with `cmp.Compare`, or `slices.Sort` — [modern-idioms.md](reference/modern-idioms.md) |
| Ignoring the error from `Close`, `Flush` or `Commit` on a write path `[community]` | Check it and return it; `defer` is fine on a read-only `Close` — [error-handling.md](reference/error-handling.md) |
| A new `http.Client{}` or `http.Get` per request `[official]` | One shared client with timeouts and transport limits — [http-and-api.md](reference/http-and-api.md) |
| Matching an error by `err.Error()` text or `==` `[official]` | `errors.Is` / `errors.As` — [error-handling.md](reference/error-handling.md) |
| A goroutine with no exit, or `context.Background()` inside a request path `[official]` | Pass the caller's `ctx` and select on `ctx.Done()` — [concurrency.md](reference/concurrency.md) |
| `defer` inside a long loop `[official]` | Move the body into a function so the defer runs per iteration — [performance-and-pitfalls.md](reference/performance-and-pitfalls.md#defer-in-a-loop) |
| `log.Printf` or `fmt.Println` as service logging `[official]` | `log/slog` with attributes — [observability.md](reference/observability.md) |
| Guessing at a slowdown, or adding a cache or a `sync.Pool` first `[community]` | Measure with pprof and benchstat, then change one thing — [profiling-and-diagnostics.md](reference/profiling-and-diagnostics.md) |

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
| Modern idioms by Go version, `go fix` coverage, `json/v2`, iterators | [modern-idioms.md](reference/modern-idioms.md) |
| Aliasing, `defer` in loops, typed nil, allocations, the PHP-to-Go traps | [performance-and-pitfalls.md](reference/performance-and-pitfalls.md) |
| Table-driven tests, fakes, fuzzing, benchmarks, coverage, `synctest` | [testing.md](reference/testing.md) |
| `ServeMux`, middleware, timeouts, graceful shutdown, JSON errors | [http-and-api.md](reference/http-and-api.md) |
| pprof, `go tool trace`, escape analysis, benchstat, PGO, `GOGC`/`GOMEMLIMIT` | [profiling-and-diagnostics.md](reference/profiling-and-diagnostics.md) |
| `slog` handlers, request IDs, metrics, tracing, health and readiness endpoints | [observability.md](reference/observability.md) |
| gofmt/goimports/gofumpt, golangci-lint v2, govulncheck, CI | [tooling-and-ci.md](reference/tooling-and-ci.md) |

## Scripts

- `python3 scripts/go_check.py` — the ordered pipeline: `gofmt -l .`, `go vet ./...`,
  `golangci-lint run`, `govulncheck ./...`. A missing tool is skipped, not failed.
- `python3 scripts/go_test.py` — per-package and total coverage, and the packages with Go
  files but no `_test.go`.
- `python3 scripts/go_scaffold.py <library|cli|service> <module-path> <target-dir>` —
  create a layout; `--dry-run` prints the paths without writing.

All three run from the module root.

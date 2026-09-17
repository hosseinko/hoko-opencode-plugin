# Current Go

The version baseline for every Go task, what the `go` directive actually gates, and the
legend every claim in this skill carries.

## Supported releases

A major Go release is supported until two newer major releases exist, which makes the two
most recent majors the supported set.

| Release | Status | Notes |
| --- | --- | --- |
| 1.27 | supported | current stable is **1.27.1**; 1.27.0 released 2026-08-19 |
| 1.26 | supported | |
| 1.25 | end of support | support ended 2026-08-19 |

## Version-gated behaviour

A language change applies when the module's `go` directive is at least the version named,
not when the installed toolchain is. A module with `go 1.22` does not get 1.23 semantics,
so every version-gated rule in this skill is stated against the directive.

| Behaviour | Minimum `go` directive |
| --- | --- |
| Loop-variable semantics: each iteration gets its own variable `[official]` | 1.22 |
| `net/http` `ServeMux` method and wildcard patterns (`GET /items/{id}`) `[official]` | 1.22 |
| Range-over-func and the `iter` package `[official]` | 1.23 |
| `testing.B.Loop` `[official]` | 1.24 |
| `os.Root` `[official]` | 1.24 |
| `testing/synctest` (GA) `[official]` | 1.25 |
| Generic methods: a method may declare its own type parameters (e.g. `math/rand/v2` `(*Rand).N`); interface methods may not, and cannot be implemented by generic methods `[official]` | 1.27 |
| Struct literal keys may be any valid field selector for the struct type `[official]` | 1.27 |

From Go 1.26 the `go` command writes a new module one major below the toolchain: `go mod
init` on a 1.27 toolchain writes `go 1.26.0`, and raising the directive is a deliberate
step rather than a default.

## Citation legend

Every claim in this skill is tagged:

- `[official]` — go.dev, the Go blog, the language spec, Effective Go, Go Code Review
  Comments, Go team proposals, or the tool's own documentation.
- `[community]` — the Uber Go Style Guide, the Google Go Style Guide,
  `golang-standards/project-layout` and its criticisms, or a tooling organisation's
  documentation.
- `[contested]` — the community does not agree; the topic file where the call is made
  states both sides and which side this skill takes.

## Sources

- [Go release history](https://go.dev/doc/devel/release)
- [Go 1.27 announcement](https://go.dev/blog/go1.27)
- [Go 1.27 release notes](https://go.dev/doc/go1.27)
- [Go 1.26 release notes](https://go.dev/doc/go1.26)
- [Go support timeline](https://endoflife.date/go)

# Project layout

Where Go code lives in a module: the three shapes a repository takes, the directories the
toolchain gives special meaning to, and the one directory the community still argues about.

Three directory names change toolchain behaviour: `internal/` is the compiler-enforced import
boundary, `testdata/` and `vendor/` are excluded from `./...`, a `vendor/` directory also
switches builds to `-mod=vendor`, and names beginning with `_` or `.` are ignored by the build.
Everything else here is convention, so an existing project's shape wins when it disagrees with
this file. `[official]` — [pkg.go.dev/cmd/go](https://pkg.go.dev/cmd/go)

## The three shapes

A repository is a **library** (importable packages), a **command** (one or more `main`
packages), or a **service/API** (a long-running binary plus its supporting packages). Pick
the shape first; the directory tree follows. `[official]` —
[go.dev/doc/modules/layout](https://go.dev/doc/modules/layout)

### Library

```
example.com/greet         # module path, repository root
├── LICENSE
├── README.md
├── go.mod
├── go.sum
├── doc.go                # package comment, when it deserves its own file
├── greet.go
├── greet_test.go
└── testdata/
    └── cases.json
```

- The importable package sits at the module root. A repository that is only a library needs no
  wrapping directory; one would only lengthen every import path. `[official]` —
  [go.dev/doc/modules/layout](https://go.dev/doc/modules/layout)
- Tests live in the package directory as `_test.go` files. There is no official `tests/`
  directory. `[official]` — [pkg.go.dev/cmd/go](https://pkg.go.dev/cmd/go)
- `testdata/` holds fixtures. The go tool ignores it and `./...` skips it, so it never becomes
  part of the import graph. `[official]` — [pkg.go.dev/cmd/go](https://pkg.go.dev/cmd/go)
- `doc.go` is a convention for the package comment when it outgrows the main file. The
  requirement is that a package has exactly one package comment, not that it lives in
  `doc.go`. `[official]` — [go.dev/blog/godoc-documenting-go-code](https://go.dev/blog/godoc-documenting-go-code)

### Command (CLI)

One binary:

```
example.com/seedgen
├── LICENSE
├── README.md
├── go.mod
├── go.sum
├── main.go               # package main at the repository root
├── internal/
│   └── seed/
│       ├── seed.go
│       └── seed_test.go
└── testdata/
```

Two or more binaries:

```
example.com/toolbox
├── go.mod
├── go.sum
├── cmd/
│   ├── toola/
│   │   └── main.go
│   └── toolb/
│       └── main.go
└── internal/
    └── shared/
        └── shared.go
```

- A lone command is a single file with `func main` at the root, named `main.go` by convention
  only. `[official]` — [go.dev/doc/modules/layout](https://go.dev/doc/modules/layout)
- Multiple commands get separate directories; `cmd/` is not required for that either.
  `[official]` — [go.dev/doc/modules/layout](https://go.dev/doc/modules/layout)
- Support code goes under `internal/`, not beside the command. `[official]` —
  [pkg.go.dev/cmd/go#Internal_packages](https://pkg.go.dev/cmd/go#hdr-Internal_packages)

### Service / API

```
example.com/orders
├── .golangci.yml
├── LICENSE
├── README.md
├── go.mod
├── go.sum
├── cmd/
│   └── orders/
│       └── main.go
├── internal/
│   └── orders/
│       ├── config/
│       │   └── config.go
│       ├── http/
│       │   ├── handler.go
│       │   └── handler_test.go
│       └── service/
│           └── service.go
└── testdata/
```

- Keep server logic in `internal/` and commands together in `cmd/`, because a server
  repository usually carries non-Go assets as well. `[official]` —
  [go.dev/doc/modules/layout](https://go.dev/doc/modules/layout)
- A server is a self-contained binary, so nothing it exposes needs to be importable; keep it
  internal. `[official]` — [go.dev/doc/modules/layout](https://go.dev/doc/modules/layout)

## `cmd/` is for mixed repositories

- The default for one binary is a root `main.go`; reach for `cmd/` once there are two or more
  binaries. `[official]` — [go.dev/doc/modules/layout](https://go.dev/doc/modules/layout)
- The guide documents an exception: a repository that mixes commands with importable packages,
  or a service repository with many non-Go files, keeps all commands under `cmd/` even when
  there is only one. `[official]` — [go.dev/doc/modules/layout](https://go.dev/doc/modules/layout)
- It is a convention the guide endorses, not a rule the tool enforces: placing commands in
  `cmd/` is called unnecessary in a repository that consists only of commands. `[official]` —
  [go.dev/doc/modules/layout](https://go.dev/doc/modules/layout)

## `internal/` is the enforced boundary

- Code in or below a directory named `internal` is importable only by code sharing the import
  path above it. `example.com/m/foo/internal/baz` is importable by `example.com/m/foo` and
  `example.com/m/foo/bar`, but not by `example.com/m/crash/bang`. `[official]` —
  [pkg.go.dev/cmd/go#Internal_packages](https://pkg.go.dev/cmd/go#hdr-Internal_packages)
- The rule is enforced by the toolchain, applies across modules, and is not gated by the `go`
  directive. `[official]` —
  [pkg.go.dev/cmd/go#Internal_packages](https://pkg.go.dev/cmd/go#hdr-Internal_packages)
- Keep supporting packages in `internal/` as much as possible: it prevents other modules
  depending on API you do not want to support, and frees you to refactor. `[official]` —
  [go.dev/doc/modules/layout](https://go.dev/doc/modules/layout)

## `pkg/` — contested

The official layout guide never mentions `pkg/`, and there is no go.dev page recommending it.
`[official]` — [go.dev/doc/modules/layout](https://go.dev/doc/modules/layout) Most of the
ecosystem does not use it; some repositories do. `[contested]` —
[Russ Cox, project-layout#117](https://github.com/golang-standards/project-layout/issues/117)

Against:

- A `pkg/` directory adds an import-path element without adding a guarantee. `internal/` is the
  only enforced boundary, and anything outside `internal` is already importable.
  `[contested]` — [theckman, project-layout#10](https://github.com/golang-standards/project-layout/issues/10)
- It "adds a superfluous path component to every import" and is outdated advice.
  `[contested]` — [eliben, project-layout#41](https://github.com/golang-standards/project-layout/issues/41)
- "`pkg` is not a canonical practice ... internal package is not just a convention, it is
  supported by the Go tool." `[contested]` —
  [rakyll, project-layout#10](https://github.com/golang-standards/project-layout/issues/10)
- Russ Cox, opening project-layout#117: "the vast majority of packages in the Go ecosystem do
  not put the importable packages in a `pkg` subdirectory"; the described layout is complex,
  and presenting it as a standard is "unfortunate". `[contested]` —
  [project-layout#117](https://github.com/golang-standards/project-layout/issues/117)
- Russ Cox, follow-up comment on project-layout#117: the minimal standard is a LICENSE, a
  `go.mod`, and Go code in the root or "organized into a directory tree as you see fit", with
  `cmd/`, `pkg/` and `examples/` all not required. `[contested]` —
  [follow-up comment](https://api.github.com/repos/golang-standards/project-layout/issues/comments/828503689)

For:

- It sequesters all Go source into well-known locations, which is "especially useful in
  repositories that have lots of other types of files", and lets `go test
  ./{cmd,pkg,internal}/...` skip a large non-Go tree.
  `[contested]` — [peterbourgon, project-layout#10](https://github.com/golang-standards/project-layout/issues/10)
- It is used by "a number of high profile and popular projects", and the maintainer accepts
  that the disagreement is legitimate. `[contested]` —
  [kcq, project-layout#41](https://github.com/golang-standards/project-layout/issues/41)
- The project-layout README frames it as a visible intent marker for reuse, not an enforcement
  mechanism, and itself calls the directory "not universally accepted".
  `[contested]` —
  [project-layout README](https://raw.githubusercontent.com/golang-standards/project-layout/master/README.md)

**This skill takes the first side: no `pkg/`.** Put importable packages at the top level and
non-exported code under `internal/`; `internal` is compiler-enforced and `pkg/` is not.
`[contested]` — [pkg.go.dev/cmd/go#Internal_packages](https://pkg.go.dev/cmd/go#hdr-Internal_packages)

## Tests, fixtures, examples

- `_test.go` files live in the package directory. A file that declares `package foo_test` is
  compiled as a separate external test package and linked into the same test binary.
  `[official]` — [pkg.go.dev/cmd/go](https://pkg.go.dev/cmd/go) (Test packages)
- `testdata/` is the fixture directory: the go tool ignores it, `./...` excludes it, and
  `go mod tidy` does not consider packages inside it. `[official]` —
  [pkg.go.dev/cmd/go](https://pkg.go.dev/cmd/go) (Package lists and patterns)
- `testdata/` is included in module zips. If it holds large files consumers should not
  download, add an empty `go.mod` inside it to exclude it. `[official]` —
  [go.dev/ref/mod](https://go.dev/ref/mod) (Module zip files)
- Runnable examples are `Example` functions in `_test.go` files, compiled and run by `go test`
  and rendered on pkg.go.dev. `[official]` —
  [go.dev/blog/examples](https://go.dev/blog/examples)
- A top-level `examples/` directory of programs is community convention, is not required, and
  is not Go-team guidance. `[community]` —
  [Russ Cox, project-layout#117](https://github.com/golang-standards/project-layout/issues/117)

## One module or a workspace

- A workspace is a set of modules on disk used as the main modules for minimal version
  selection, listed in a `go.work` file with `use` directives. It was added in Go 1.18 to work
  on interdependent modules without editing `replace` directives. `[official]` —
  [go.dev/ref/mod#workspaces](https://go.dev/ref/mod#workspaces)
- A `use` directive does not recurse into subdirectories; `go work use -r .` adds nested
  modules. `[official]` — [go.dev/ref/mod#workspaces](https://go.dev/ref/mod#workspaces)
- It is generally inadvisable to commit `go.work`: it can override a developer's own file and
  can make CI select the wrong dependency versions. Committing can make sense when the modules
  in a repository are developed exclusively with each other. `[official]` —
  [go.dev/ref/mod#go-work-files](https://go.dev/ref/mod#go-work-files)
- `go mod init`, `go mod tidy`, `go mod vendor`, `go mod why`, `go mod edit` and `go get`
  always operate on a single main module, even in workspace mode; `go work sync` pushes the
  workspace build list back into each module's `go.mod`. `[official]` —
  [go.dev/ref/mod#workspaces](https://go.dev/ref/mod#workspaces)
- A subdirectory with its own `go.mod` is a nested module: excluded from the parent's zip,
  unreachable through the parent's module path, and skipped by `./...` patterns. When packages
  become useful to other projects, split them into real modules. `[official]` —
  [go.dev/doc/modules/layout](https://go.dev/doc/modules/layout)
- Use a workspace for local, unpublished edits across modules co-developed in one checkout.
  Do not use one as committed configuration for a published library or an ordinary
  single-module repo, or to make `go mod tidy` see several modules: it never does.
  `[official]` — [go.dev/blog/get-familiar-with-workspaces](https://go.dev/blog/get-familiar-with-workspaces)

## Sources

- [Organizing a Go module](https://go.dev/doc/modules/layout)
- [Go Modules Reference](https://go.dev/ref/mod)
- [cmd/go documentation](https://pkg.go.dev/cmd/go)
- [Get familiar with workspaces](https://go.dev/blog/get-familiar-with-workspaces)
- [Testable Examples in Go](https://go.dev/blog/examples)
- [Godoc: documenting Go code](https://go.dev/blog/godoc-documenting-go-code)
- [golang-standards/project-layout](https://github.com/golang-standards/project-layout) issues
  [#10](https://github.com/golang-standards/project-layout/issues/10),
  [#41](https://github.com/golang-standards/project-layout/issues/41),
  [#117](https://github.com/golang-standards/project-layout/issues/117)

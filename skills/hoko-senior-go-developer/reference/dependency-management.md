# Dependency management

How `go.mod` and `go.sum` are kept honest: the `go` and `toolchain` directives and what they
gate, minimal version selection, the commands that edit the module graph, semantic import
versioning from v2, and the vendoring call this skill makes.

## `go` and `toolchain` directives

- `go <version>` declares the module's language and tooling semantics. Since Go 1.21 it is a
  mandatory minimum: a toolchain refuses to load a module whose `go` line is newer than
  itself, and the line must be at least that of every dependency. `[official]` —
  [go.dev/ref/mod#go-mod-file-go](https://go.dev/ref/mod#go-mod-file-go)
- The line gates language features and go-command behaviour (auto-vendoring at 1.14+, `all`
  semantics at 1.16+, graph pruning and the indirect block at 1.17+). A missing `go` line
  means `go 1.16`. `[official]` — [go.dev/ref/mod#go-mod-file-go](https://go.dev/ref/mod#go-mod-file-go)
- `toolchain <name>` is a suggested toolchain, not a floor. It cannot be lower than the `go`
  line, and it only takes effect when the module is the main module and the default toolchain
  is older. `[official]` —
  [go.dev/ref/mod#go-mod-file-toolchain](https://go.dev/ref/mod#go-mod-file-toolchain)
- `GOTOOLCHAIN=auto` (the default) makes the go command find, or download and checksum-verify,
  the named toolchain, then switch to it. `[official]` —
  [go.dev/doc/toolchain](https://go.dev/doc/toolchain)
- Any command that updates the `go` line writes its own name into the `toolchain` line, so a
  build is repeatable. `[official]` — [go.dev/doc/toolchain](https://go.dev/doc/toolchain)
- From Go 1.26, `go mod init` writes a new module one major below the toolchain: on a 1.27
  toolchain it writes `go 1.26.0`. Raise it deliberately with `go get go@1.27`. `[official]` —
  [go.dev/doc/go1.26](https://go.dev/doc/go1.26)

## `go.mod` and `go.sum`

- `go.mod` records the module path, the `go` line and the minimum versions of the module's
  dependencies. `go.sum` records content hashes. Neither is a lock file. `[official]` —
  [go.dev/ref/mod#go-sum-files](https://go.dev/ref/mod#go-sum-files)
- Since Go 1.17 the module graph is pruned and loaded lazily, and direct and indirect
  requirements appear in separate blocks. `[official]` —
  [go.dev/ref/mod#graph-pruning](https://go.dev/ref/mod#graph-pruning)
- `go.sum` is a hash log: it may hold hashes for versions no longer needed, and `go mod tidy`
  prunes them. `[official]` — [go.dev/ref/mod#go-sum-files](https://go.dev/ref/mod#go-sum-files)
- Go 1.27 `go mod tidy` merges duplicate `require` blocks into at most one direct and one
  indirect block, for modules that declare `go 1.27` or later. `[official]` —
  [go.dev/doc/go1.27](https://go.dev/doc/go1.27)
- The checksum database (`sum.golang.org`) fills in missing hashes; `go.sum` is the main
  module's trust root. Commit both files. `[official]` —
  [go.dev/ref/mod#checksum-database](https://go.dev/ref/mod#checksum-database)
- `go mod verify` checks modules in the local module cache against the hashes recorded when
  they were downloaded. It does not read `go.sum` and does not download anything.
  `[official]` — [go.dev/ref/mod#go-mod-verify](https://go.dev/ref/mod#go-mod-verify)

## Minimal version selection

- MVS builds the build list by graph traversal, tracking the highest minimum version any
  requirement demands. The result is the minimum set that satisfies every requirement, not the
  newest available version. `[official]` —
  [go.dev/ref/mod#minimal-version-selection](https://go.dev/ref/mod#minimal-version-selection)
- The build list is not saved in a lock file. MVS is deterministic, so the list does not change
  when new dependency versions are released; it is recomputed at the start of every
  module-aware command. `[official]` —
  [go.dev/ref/mod#minimal-version-selection](https://go.dev/ref/mod#minimal-version-selection)

## Command roles

- `go get` edits requirements in `go.mod`: it adds, changes and removes `require` entries,
  accepts version queries (`@v1.2.3`, `@latest`, `@patch`, `@none`), manages the toolchain
  (`go get go@1.22`), and adds `// indirect` requirements to preserve upgrades. `[official]` —
  [go.dev/ref/mod#go-get](https://go.dev/ref/mod#go-get)
- `go install pkg@version` installs a binary; `go get`'s build/install behaviour is effectively
  `-d`. `[official]` — [go.dev/ref/mod#go-get](https://go.dev/ref/mod#go-get)
- `go mod tidy` makes `go.mod` match the source: it adds missing requirements, removes unused
  ones, and updates `go.sum`. It loads all packages, including tests and tools. `[official]` —
  [go.dev/ref/mod#go-mod-tidy](https://go.dev/ref/mod#go-mod-tidy)
- `go mod download` pre-fills the module cache. Normal builds already download on demand, so
  this is for caching, proxying and CI. `[official]` —
  [go.dev/ref/mod#go-mod-download](https://go.dev/ref/mod#go-mod-download)
- `go mod why` prints the shortest import path from the main module to a package, or to any
  package in a module with `-m`, which explains why a dependency is present. `[official]` —
  [go.dev/ref/mod#go-mod-why](https://go.dev/ref/mod#go-mod-why)

## Semantic import versioning

- The import compatibility rule says the same import path must stay backwards compatible, so a
  v2+ module needs a distinct path: `/vN` on the module path and on every import path. A
  module `example.com/mod` at v1 must become `example.com/mod/v2` at v2.0.0. Suffixes are not
  allowed at v0/v1. `[official]` —
  [go.dev/ref/mod#major-version-suffixes](https://go.dev/ref/mod#major-version-suffixes)
- Because the suffix is part of the path, a requirement must match: `require example.com/m
  v2.0.0` is invalid; it must be `example.com/m/v2 v2.0.0`. `[official]` —
  [go.dev/ref/mod#go-mod-file-require](https://go.dev/ref/mod#go-mod-file-require)
- `gopkg.in/...` is the exception: it uses a `.vN` suffix at any major version.
  `[official]` —
  [go.dev/ref/mod#major-version-suffixes](https://go.dev/ref/mod#major-version-suffixes)
- New major versions are separate modules and can coexist in one build, which resolves diamond
  dependencies. `[official]` —
  [go.dev/ref/mod#major-version-suffixes](https://go.dev/ref/mod#major-version-suffixes)
- A `+incompatible` version is synthesised by the go command for a v2+ tag in a repository that
  has no `go.mod`. It treats the module as an extension of v1, so MVS may auto-upgrade to a
  version that breaks the build. The suffix never appears on a git tag and may appear on
  pseudo-versions. `[official]` —
  [go.dev/ref/mod#incompatible-versions](https://go.dev/ref/mod#incompatible-versions)
- When adopting modules after v2+, release the next major with a suffix: latest `v4.1.2`
  becomes module `example.com/m/v5`, tag `v5.0.0`. `[official]` —
  [go.dev/ref/mod#incompatible-versions](https://go.dev/ref/mod#incompatible-versions)

## Vendoring — contested

The official docs are neutral: a `vendor/` directory may be used to interoperate with older Go
versions or to keep every build input in one file tree, and `go mod vendor` is first-class.
`[official]` — [go.dev/ref/mod#vendoring](https://go.dev/ref/mod#vendoring)

- With a `vendor/` directory and `go >= 1.14`, build commands use it automatically
  (`-mod=vendor`); otherwise `-mod=readonly` is the default. `[official]` —
  [go.dev/ref/mod#vendoring](https://go.dev/ref/mod#vendoring)
- `go work vendor` builds a workspace-level vendor tree (Go 1.22+). `[official]` —
  [go.dev/doc/go1.22](https://go.dev/doc/go1.22)
- The original vgo design proposed dropping vendoring entirely; community feedback is why it
  was retained, which is the documented origin of the split. `[community]` —
  [go.dev/wiki/Modules](https://go.dev/wiki/Modules)
- For: hermetic, offline builds that need neither a proxy nor the network, and reproducible CI.
  `[contested]` — [Go issue #78533](https://go.dev/issue/78533)
- For: supply-chain review of dependency changes inside the pull request, and Linux
  distribution packaging, both of which want `go mod vendor` + `go build -mod=vendor`. Large
  projects including Kubernetes, Moby, Delve and VictoriaMetrics vendor. `[contested]` —
  [victoriametrics.com/blog](https://victoriametrics.com/blog/vendoring-go-mod-vendor/)
- Against: `go.mod` plus `go.sum` plus the checksum database already give integrity and
  repeatable resolution, so vendoring is not strictly required. `[contested]` —
  [go.dev/wiki/Modules](https://go.dev/wiki/Modules)
- Against: `vendor/` duplicates dependency code across repositories, bloats diffs and
  checkouts, and drifts out of sync, producing `inconsistent vendoring` errors that force a
  re-run of `go mod vendor`. `[contested]` —
  [victoriametrics.com/blog](https://victoriametrics.com/blog/vendoring-go-mod-vendor/)

**This skill takes the second side: vendoring off by default.** Turn it on only for a hermetic
or offline build, distribution packaging, or PR-time dependency review. `[contested]` —
[go.dev/ref/mod#vendoring](https://go.dev/ref/mod#vendoring)

## Sources

- [Go Modules Reference](https://go.dev/ref/mod)
- [Go toolchains](https://go.dev/doc/toolchain)
- [Go 1.26 release notes](https://go.dev/doc/go1.26)
- [Go 1.27 release notes](https://go.dev/doc/go1.27)
- [Go 1.22 release notes](https://go.dev/doc/go1.22)
- [Modules wiki](https://go.dev/wiki/Modules)
- [Go issue #78533](https://go.dev/issue/78533)
- [Vendoring Go dependencies](https://victoriametrics.com/blog/vendoring-go-mod-vendor/)

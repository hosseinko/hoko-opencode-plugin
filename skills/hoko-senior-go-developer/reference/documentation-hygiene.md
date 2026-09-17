# Documentation and release hygiene

What a Go module's comments, repository files and versions look like when someone else is
meant to depend on them: the godoc comment rules, the release workflow, and the files that are
convention rather than requirement.

## Doc comments

- A doc comment is a comment immediately before a top-level package, const, func, type or var
  declaration with no intervening newline. Every exported name should have one; comments not
  adjacent to a top-level declaration are omitted from `go doc` and pkg.go.dev, except
  top-level `BUG(who):` comments. `[official]` — [go.dev/doc/comment](https://go.dev/doc/comment)
- Doc comments are complete sentences. A package comment's first sentence begins with
  `Package `; a command's begins with the program name, capitalized; a type comment names the
  declared symbol; a func comment says what the function returns or does. `[official]` —
  [go.dev/doc/comment](https://go.dev/doc/comment)
- The blanket rule "comments should begin with the name of the thing being described and end
  in a period" comes from Go Code Review Comments. Use "reports whether", not "or not", for
  boolean results. `[official]` — [go.dev/wiki/CodeReviewComments](https://go.dev/wiki/CodeReviewComments)
- A package has exactly one package comment. A multi-file package keeps it in one source file;
  if several files carry one they are concatenated. `[official]` —
  [go.dev/doc/comment](https://go.dev/doc/comment)
- Do not document the current implementation or algorithm in a doc comment; that belongs in
  comments inside the function body. Mention asymptotic bounds only when callers need them.
  `[official]` — [go.dev/doc/comment](https://go.dev/doc/comment)

## `doc.go` and comment syntax

- `doc.go` is where a package comment goes when it deserves a file of its own: only the comment
  and the package clause. It is convention, not a tool requirement. `[official]` —
  [go.dev/blog/godoc-documenting-go-code](https://go.dev/blog/godoc-documenting-go-code)
- gofmt canonicalises doc comments from Go 1.19. The supported subset: paragraphs of
  unindented lines; `# ` headings set off by blank lines; `-`/`N.` lists (no nesting);
  indented code blocks; doc links such as `[Name]` and `[pkg.Name]`; `[Text]: URL` link
  definitions; and `MARKER(uid):` notes. `[official]` —
  [go.dev/doc/comment](https://go.dev/doc/comment)
- Directive comments such as `//go:generate` are not part of the doc comment; gofmt moves them
  to the end, after a blank line. `[official]` — [go.dev/doc/comment](https://go.dev/doc/comment)

## Deprecation

- A paragraph beginning `Deprecated:` is a deprecation notice. Tools may warn, pkg.go.dev
  hides the docs by default, and the notice should say what to use instead. It need not be the
  last paragraph. `[official]` — [go.dev/doc/comment](https://go.dev/doc/comment)
- A `// Deprecated:` comment before, or on the same line as, the `module` directive in
  `go.mod` deprecates the whole module; `go get` and `go list -m -u` surface it, and it
  applies to all minor versions of that major. `[official]` — [go.dev/ref/mod](https://go.dev/ref/mod)

## Module versions and release workflow

- Versions are `vMAJOR.MINOR.PATCH`, optionally with pre-release and build metadata. Major is
  for a backwards-incompatible change to the public API, minor for compatible additions, patch
  for changes that do not affect the public API. `v0` and pre-releases carry no compatibility
  guarantee; `v1+` commits to compatibility within the major. `[official]` —
  [go.dev/doc/modules/version-numbers](https://go.dev/doc/modules/version-numbers)
- A major bump is required when backward compatibility cannot be guaranteed, for example when
  removing, renaming or changing the signature of exported API; the docs advise treating it as
  a last resort. `[official]` —
  [go.dev/doc/modules/major-version](https://go.dev/doc/modules/major-version)
- From major version 2 the module path carries the `/vN` suffix and every import changes; the
  mechanics are in [dependency-management.md](dependency-management.md). `[official]` —
  [go.dev/ref/mod](https://go.dev/ref/mod)
- Release steps: `go mod tidy`, `go test ./...`, `git tag vX.Y.Z`, `git push origin vX.Y.Z`,
  and optionally `GOPROXY=proxy.golang.org go list -m example.com/mod@vX.Y.Z` to prime the
  proxy. `[official]` —
  [go.dev/doc/modules/publishing](https://go.dev/doc/modules/publishing)
- A module in a subdirectory is tagged with the subdirectory prefix: module
  `example.com/mymodules/module1` at v1.2.3 is tagged `module1/v1.2.3`. `[official]` —
  [go.dev/doc/modules/managing-source](https://go.dev/doc/modules/managing-source)
- Never change or delete a published tag: the checksum database and the module mirror pin the
  first copy, and tools report a security error on a mismatch. To withdraw a bad version,
  publish a `retract` directive in a new higher version. `[official]` —
  [go.dev/ref/mod](https://go.dev/ref/mod)
- Pre-release versions must be requested explicitly, for example `go get m@v1.2.3-alpha`.
  `[official]` — [go.dev/blog/publishing-go-modules](https://go.dev/blog/publishing-go-modules)
- Bumping the `go` directive raises the minimum toolchain every consumer needs. Manage the
  line with `go get go@<version>`. `[official]` — [go.dev/doc/toolchain](https://go.dev/doc/toolchain)
- Go 1.27 adds `go doc package@version` and `go doc -ex`, which lists executable examples.
  `[official]` — [go.dev/doc/go1.27](https://go.dev/doc/go1.27)

## README, CONTRIBUTING, CHANGELOG

- The Go team's "initial commit" list is LICENSE, `go.mod`, `go.sum`, and the package
  directories with their `.go` sources. README, CONTRIBUTING and CHANGELOG are not required by
  anything in the module docs. `[official]` —
  [go.dev/doc/modules/managing-source](https://go.dev/doc/modules/managing-source)
- pkg.go.dev surfaces a module that has a `go.mod`, a redistributable license, a tagged
  version and a stable version. `[official]` — [pkg.go.dev/about](https://pkg.go.dev/about)
- A README is expected anyway as community convention: what the project does, why it is
  useful, how to get started, where to get help, and who maintains it. GitHub pairs it with
  CONTRIBUTING and a code of conduct as healthy-contribution files. `[community]` —
  [GitHub: About READMEs](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-readmes)
- The Standard Readme spec orders sections: title, short description, install, usage,
  contributing, and license last. `[community]` —
  [standard-readme spec](https://github.com/RichardLitt/standard-readme/blob/main/spec.md)
- CONTRIBUTING is not a Go-team requirement, but it is an expected community and GitHub
  convention. `[community]` —
  [GitHub: About READMEs](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-readmes)
- A CHANGELOG is not read by any Go tooling. The git tag is the source of truth and is
  immutable; a changelog is a human-facing mirror that should stay consistent with the tags.
  Keep a Changelog is the dominant convention: `CHANGELOG.md`, an entry for every version,
  newest first, ISO 8601 dates, an `Unreleased` section, and
  Added/Changed/Deprecated/Removed/Fixed/Security categories. `[community]` —
  [keepachangelog.com](https://keepachangelog.com/en/1.1.0/)
- GitHub Releases attach notes to tags but are not portable; they are an alternative to, not a
  substitute for, correct tagging. `[community]` —
  [keepachangelog.com](https://keepachangelog.com/en/1.1.0/)

## Sources

- [Go Doc Comments](https://go.dev/doc/comment)
- [Go Code Review Comments](https://go.dev/wiki/CodeReviewComments)
- [Godoc: documenting Go code](https://go.dev/blog/godoc-documenting-go-code)
- [Module version numbering](https://go.dev/doc/modules/version-numbers)
- [Go Modules Reference](https://go.dev/ref/mod)
- [Publishing a module](https://go.dev/doc/modules/publishing)
- [Managing a module's files](https://go.dev/doc/modules/managing-source)
- [Publishing Go Modules](https://go.dev/blog/publishing-go-modules)
- [About READMEs](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-readmes)
- [Standard Readme spec](https://github.com/RichardLitt/standard-readme/blob/main/spec.md)
- [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)

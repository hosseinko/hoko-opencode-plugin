# Reading the repository

## The read-exclusion list

No search walks into these folders. The list is the same for every agent, skill and
stage:

- `node_modules`, `.next`, `dist`, `build`, `coverage` — Node's dependencies, and the
  output of Node, TypeScript/React and Java builds
- `vendor` — PHP's Composer and Ruby's Bundler
- `target` — Rust's and Maven's build output
- `bin`, `obj` — .NET and Go build output
- `_build`, `deps` — Elixir's Mix
- `.gradle` — Gradle's cache
- `.bundle` — Bundler's install
- `.terraform` — Terraform's providers and state
- `__pycache__`, `.venv` — Python's compiled modules and virtualenv
- `.git` — git's object store
- `.ai/plans`, `.ai/analytics` — this workflow's plans and its analytics copies
- the journal tree `journalPath` (`HOKO_JOURNAL_PATH`) resolves to — journal entries,
  their reports and their invoices

## Reaching a file inside one

A file in an excluded folder is reached only by a path the caller names. It is never
reached by a recursive `grep`, `glob` or `find`: the path is the whole exception, because
the caller already knows which file it wants. Nothing in these folders is discovered by
walking them, and a match inside one says nothing about the repository's own code.

## The web comes after the repository

A stage reaches the web only when no file in this repository answers the question.

When a stage reaches the web, it names the repository file it ruled out first — the file
it read and found silent, by path, not "the codebase" and not "no file covers this".

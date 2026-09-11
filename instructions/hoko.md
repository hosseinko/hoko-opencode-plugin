# Standing rules

These hold in every session and on every agent, with or without a skill loaded, in a
plan run or in plain build-mode chat.

## Branching

`main`, `master`, `staging` and `develop` are protected: never commit to them, and never
cut a branch from whatever happens to be checked out. Every branch starts from an
explicit, freshly fetched base:

| Branch     | Cut from  | Lands as                                    |
| ---------- | --------- | ------------------------------------------- |
| `feature/` | `develop` | PR → `develop`                              |
| `bugfix/`  | `develop` | PR → `develop`                              |
| `hotfix/`  | `main`    | PR → `main`, then a second PR → `develop`   |
| `release/` | `develop` | PR → `main`, then a second PR → `develop`   |

```bash
git fetch origin && git checkout -b <name> origin/<base>
```

Names are `<type>/<TICKET-><slug>`: `feature/ABC-123-token-refresh`, or
`feature/token-refresh` when the change has no ticket. Lowercase, hyphens only, the
ticket key uppercase and verbatim and never invented, the slug at most five words naming
the change rather than the files. The key comes from the plan's `Ticket:` line, or from
the request when there is no plan; from there the commit trailer and the PR title are
read back off the branch name, so the branch is where a ticket enters the workflow.

A repository without `develop` has no integration branch separate from its default one:
the default branch takes `develop`'s place in the table and `hotfix/` has nothing to
back-merge into. `HOKO_BASE_BRANCH` overrides which branch plays the `develop` role.

## Git stops at the commit

- **Never merge.** No `git merge`, `git rebase` or fast-forward that moves `main`,
  `master`, `staging` or `develop` onto a working branch. No `gh pr merge`, no
  `--auto` merge, no squash-and-land.
- **Never push** unless the user asked for it in this turn, or `HOKO_PR_AUTO=1` and you
  are following `hoko-pull-request`.
- **Never delete or reset a branch**, and never check out a different branch to "finish
  up".
- A branch reaches the integration branch as a pull request, via the
  `hoko-pull-request` skill — which stops by itself when `origin` is not GitHub and
  leaves the branch for the user.

Finishing a change means: committed, gate green, branch reported. Integration is the
user's call, always. If a change looks ready to land, say so and offer the PR; do not
land it.

## Delegation inside a plan run is already approved

A plan run's subagents — `hoko-plan-executor`, `hoko-code-reviewer`,
`hoko-quality-assurance`, `hoko-researcher` — are not ad-hoc delegation. Approving the
plan approved them, and `/hoko/execute-plan` requires every one of them: the review in
particular runs on every step, including a two-line diff. So a general rule against
spawning subagents, or against delegating code the user will review, does not reach
them. It still holds everywhere else: outside a plan run, ask before launching one.

# Standing rules

These hold in every session and on every agent, with or without a skill loaded, in a
plan run or in plain build-mode chat.

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

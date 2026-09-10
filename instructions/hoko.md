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

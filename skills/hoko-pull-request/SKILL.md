---
name: hoko-pull-request
description: >-
  Open a GitHub pull request instead of merging — checks that origin is GitHub, pushes the branch,
  and opens a PR against the integration branch (default develop) with the run's closing report as
  the body. Use at the end of a plan run, when asked to open a PR, or when asked how a finished
  branch reaches develop.
---

# Pull requests

Where a finished branch goes. A green run does not integrate itself: on a GitHub remote
the branch becomes a pull request against the integration branch; anywhere else it is
left on its branch for the user to integrate by hand.

Nothing here merges anything — not the PR, not a local merge, not auto-merge. Opening
the PR is the end of the run.

## Settings

The plugin exports `hoko.env` into every shell, so `printf '%s' "$HOKO_PR_AUTO"` reads
these:

- **`HOKO_BASE_BRANCH`** — the branch the PR targets. Unset means `develop`.
- **`HOKO_PR_AUTO`** — unset, empty, or `0`: show what would be opened and wait for
  confirmation before pushing. `1`: push and open it without asking.

`HOKO_PR_AUTO=1` is the only thing that authorises a push without an explicit request.
Without it, the confirmation in step 5 *is* that request.

## 1. Is the remote GitHub?

```bash
git remote get-url origin 2>/dev/null
```

- **No origin** — stop. Report the branch name and that there is no remote to open a PR
  on.
- **URL contains `github.com`** — GitHub. Continue.
- **Anything else** — run `gh repo view --json nameWithOwner` once; it resolves GitHub
  Enterprise hosts `gh` is configured for. If it succeeds, continue. If it fails, stop
  and report the host.

Every stop here ends the same way: the work is committed, the branch is left for manual
integration, and that is a normal ending. Never fall back to a local merge into the base
branch, and never drive the API by hand instead.

## 2. Is `gh` usable?

```bash
gh auth status
```

Missing or unauthenticated — stop, report exactly that with the branch name and
`gh auth login` as the fix. Do not install anything.

## 3. Is the branch ready?

```bash
BASE="${HOKO_BASE_BRANCH:-develop}"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
git status --porcelain
git ls-remote --exit-code --heads origin "$BASE"
git fetch origin "$BASE" && git rev-list --count "origin/$BASE..HEAD"
```

Stop and report, without pushing, if:

- `$BRANCH` is `$BASE` — there is nothing to open a PR from.
- the worktree is dirty — uncommitted work means the run is not finished.
- `$BASE` is not on the remote — say so and ask which branch to target; never retarget
  to `main` on your own.
- the commit count is `0` — the base already has this work.

## 4. Draft the title and body

- **Title** — the plan's `#` heading, or failing that the summary line of the run's
  first commit. A plain sentence, no prefixes. If the branch name carries a Jira-style
  ticket key (`ABC-123`), prefix the title with `ABC-123: `; never invent one.
- **Body** — the run's closing report, verbatim: the same text that gets journaled,
  minus the PR line you cannot know yet. Write it to a file and pass `--body-file`;
  never inline a body as a shell argument.
- No tool attribution, no "Generated with…" trailer — the same rule as commit messages.

## 5. Confirm, then open

Unless `HOKO_PR_AUTO=1`, show the base, the branch, the title and the commit subjects,
and get confirmation. Then:

```bash
git push -u origin HEAD
gh pr create --base "$BASE" --head "$BRANCH" --title "$TITLE" --body-file "$BODY_FILE"
```

If a PR for the branch already exists (`gh pr view --json url,state,isDraft`), the push
has just updated it — do not open a second one. Report that URL and say the branch was
updated. Leave a draft as a draft and reopen nothing.

## 6. Report

One line: the PR URL, the base branch, and how many commits it carries. When no PR was
opened, one line saying why and that the branch is left for manual integration. Inside a
plan run that line belongs in the closing report, so it lands in the journal.

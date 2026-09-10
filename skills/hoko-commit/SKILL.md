---
name: hoko-commit
description: Format git commit messages to this workflow's convention - a plain why-focused summary line plus one bullet per change. Use when asked to commit changes, write a commit message, or clean up a commit history.
---

# Commit conventions

Apply these when creating commits. Never commit or push without an explicit request
from the user.

**The commit is where this skill stops.** Committing is not integrating: never merge the
branch into `main`, `master`, `staging` or `develop`, never fast-forward one of them onto
your work, never `git push`, and never delete the branch afterwards. A finished branch
reaches the integration branch one way only — a pull request, through
`hoko-pull-request`. That holds whether the commit came from a plan run or from a plain
build-mode request, and "the change is done" is not permission to integrate it.

## Auto-commit

Check `HOKO_COMMIT_AUTO` (the plugin exports `hoko.env` into every shell, so
`printf '%s' "$HOKO_COMMIT_AUTO"` reads it):

- **Unset, empty, or `0`** — confirm the message with the user before committing, as in
  step 6 below.
- **`1`** — commit without asking once the checks pass, then report the subject line and
  the short SHA so the user can see what landed.

Two things auto mode never waives: the protected-branch check (step 2 — a protected
branch still stops and asks for a branch name) and the quality gate (step 4 — a red gate
is never committed through). `HOKO_COMMIT_AUTO` never authorises a push.

## Commit messages

Keep messages short and factual — avoid verbose descriptions or unnecessary
detail. Wrap all text at 72 characters.

Do not add yourself as an author or attribute the commit to a tool — no
`Co-Authored-By` line, no "Generated with…" or similar trailer. The commit is
authored solely by the user.

Structure:

1. **Summary line** — a plain, short sentence focused on *why* the change was
   made (the intent or problem solved), not *what* was mechanically changed.
   Don't emphasize it (no prefixes, bold, or all-caps) and don't pile on detail.
   End it with a full stop.
2. A blank line.
3. **One bullet per change** — each starts with `*` and is a short sentence in
   imperative form, ending with a full stop. Include the *why* when it isn't
   obvious from the change itself.
4. **Ticket reference** — if the current branch name contains a ticket key (a
   Jira-style key: uppercase letters, a hyphen, then digits, e.g. `ABC-123`),
   add a blank line and the key on its own as the last line — no label. If the
   branch has no such key, omit it entirely — never invent one.

Example (on branch `feature/ABC-123-token-refresh`):

```text
Keep users signed in instead of dropping them mid-session.

* Add JWT validation middleware to reject tampered tokens.
* Issue refresh tokens from the login endpoint so sessions persist.
* Cover the auth guard with tests to lock the behavior in.

ABC-123
```

## Workflow

1. Run `git status` and `git diff` (staged + unstaged) to see exactly what changed.
2. **Check the current branch.** If it is a protected branch (`main`, `master`,
   `staging`, or `develop`), never commit directly to it — create a new branch
   first:
   - Ask the user what the new branch should be called.
   - If they give only a prefix ending in `/` (e.g. `feature/`, `bugfix/`), append
     a short, meaningful slug derived from the staged changes, then show the full
     name and ask them to confirm it or supply a different one before creating it.
   - If they give a complete name, use it as-is.
   - Create it with `git checkout -b <name>`, then continue.
3. Group unrelated changes into separate commits — don't bundle a refactor with a fix.
4. **Run the quality gate.** Invoke the `hoko-quality-assurance` skill and follow it:
   find the project's own commands, then lint, then static analysis, then tests with
   coverage. Do not commit while any gate is red — report the failure instead.

   **One exception: a step commit inside a plan run.** When the caller says this commit
   is one step of `/hoko/execute-plan`, the fast gate — the analyser clean and the unit
   tests green — has already run in `hoko-code-reviewer`, and that is the gate for this
   commit. Do not re-run it, and do not start the full one: linting, the whole suite and
   coverage run once at the end of the run, in the `hoko-quality-assurance` subagent. If
   the reviewer's fast gate was red, there is no commit to make — that is a finding to
   fix first. Every other commit, this command included, runs the full gate.
5. Draft the message from the actual diff, not from assumptions.
6. Show the user the message and get confirmation before committing — unless
   `HOKO_COMMIT_AUTO=1`, in which case commit and report the subject and short SHA.
7. **Stop.** Report the commit and, if the branch now holds finished work, say it is
   ready for a pull request and offer `hoko-pull-request` — one line. Do not switch
   branches, merge, push or open the PR off your own bat. An approved commit message
   approves the commit and nothing beyond it.

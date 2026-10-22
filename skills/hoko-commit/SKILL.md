---
name: hoko-commit
description: Format git commit messages to this workflow's convention - a plain why-focused summary line plus one bullet per change. Use when asked to commit changes, write a commit message, or clean up a commit history.
---

# Commit conventions

Apply these when creating commits. Never commit or push without an explicit request
from the user.

The commit is where this skill stops. Merging, pushing and branch handling follow
the standing rules in `instructions/hoko.md`, whether this commit came from a
plan run or a plain request.

## Auto-commit

A quality-assurance fix commit never asks. Approving the plan was the consent, so
`commitAuto` does not apply to it: once the gate that applies to it (step 4) is green,
commit and report the subject line and the short SHA. Nothing below in this section
concerns that commit. A plan-run step commit never reaches this skill at all —
`step-commit.py` makes it directly from the conductor's message.

Everywhere else, read the setting — unless the caller already gave you its value, in
which case use that and run nothing:

```bash
python3 "${HOKO_ROOT}/scripts/settings.py" commitAuto
```

- **`false`** — confirm the message with the user before committing, as in step 6 below.
- **`true`** — commit without asking once the checks pass, then report the subject line
  and the short SHA so the user can see what landed.

Auto mode neither waives the quality gate (step 4) nor authorises a push.

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
   add a blank line and the key on its own as the last line — no label. The branch name
   is the only source for this: a key in the plan or the conversation that never made it
   into the branch name does not go in the message. If the branch has no such key, omit
   it entirely — never invent one.

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
   `staging`, or `develop`), never commit directly to it. Follow the branching rules in
   `instructions/hoko.md`: `feature/`, `bugfix/` and `release/` are cut from `develop`,
   `hotfix/` from `main`, every branch named `<type>/<TICKET-><slug>` from a freshly
   fetched base. Show the name and the base, and get a yes before creating it.
   - **Inside a plan run** — a quality-assurance fix commit — this is a blocker to
     report, not a question to ask: a subagent cannot ask the user, and the conductor
     already checked the branch before step 1. Stop and say the branch changed under
     the run rather than creating one or guessing a name.
3. Group unrelated changes into separate commits — don't bundle a refactor with a fix.
4. **Run the quality gate.** Invoke the `hoko-quality-assurance` skill and follow it:
   find the project's own commands, then lint, then static analysis, then tests with
   coverage. Do not commit while any gate is red — report the failure instead.

   One exception, inside a plan run: when the caller says this commit fixes what
   `hoko-quality-assurance` itself found, that subagent has just run the full gate before
   handing you the fix, so do not run it again for the commit that lands it. Linting, the
   whole suite and coverage otherwise run once at the end of the run, in the
   `hoko-quality-assurance` subagent. Every other commit runs the full gate.
5. Draft the message from the actual diff, not from assumptions.
6. Not for a plan-run commit: see Auto-commit above, it never reaches this step.
   Show the user the message and get confirmation before committing — unless
   `commitAuto` is `true`, in which case commit and report the subject and short SHA.
7. **Stop.** Report the commit and, if the branch now holds finished work, say it is
   ready for a pull request — one line. Do not switch branches, merge, push or open
   the PR.

#!/usr/bin/env python3
"""
plan-flow.py — the plan-mode protocol for the plan-and-execute workflow.

Ships with the `hoko` plugin.

Prints the grilling text plan mode injects on entry, filled in for the repository
around `--root` (default: the current directory):

    plan-flow.py grill [--root <dir>]

The text adds to opencode's own plan-mode phases — explore, design, ask, write the
plan — rather than replacing them, and it ends by asking for approval so
`hoko_execute` can hand the plan to the build agent.
"""

import argparse
import os
import re
import sys
from pathlib import Path

import journal
import settings

# The go-mutesting install commands below stay on @latest: upstream's v2.3.1 go.mod lacks
# the /v2 suffix, so no tagged version can be installed with `go install`.
GRILL = """\
You are now in plan mode. This protocol adds to opencode's own plan-mode phases —
explore, design, ask, write the plan — rather than replacing them.

**1. Grill the request first.** Interrogate what was asked:

- One question at a time, each with your recommended answer, so the user can confirm
  rather than compose.
- The `question` tool when the answer is a choice between options.
- Read the codebase before asking; delegate to the `explore` subagent when the answer
  needs more than a couple of reads.
- The `hoko-research` skill when a question turns on something outside this repository.

Cover, proportional to the size of the change:

- Scope, and explicit non-goals
- Inputs, outputs, data shapes, and who calls this
- Edge cases and failure behaviour
- How we will know it works

Drive the grilling toward behaviour you can state in EARS form, because that is what
goes into the plan's *Requirements*. The five shapes double as a completeness check — a
bucket you cannot fill is usually one nobody thought about:

- **Always true** — invariants, limits, contracts.         -> ubiquitous
- **Only in a state** — while empty, while degraded.       -> While
- **On a trigger** — a call, a message, a timer.           -> When
- **When it goes wrong** — bad input, timeout, conflict.   -> If / Then
- **Only if configured** — a flag, an optional dependency. -> Where

The `If / Then` bucket is the one that ends up silently empty. If the user has not said
what happens on bad input, on a timeout or on a partial failure, the grilling is not
finished.

Cover performance **only** if this touches a hot path, a loop over unbounded data, or a
query in a request path. Cover security **only** if it touches untrusted input,
authentication, authorization, secrets, or PII. Otherwise skip both silently and leave
them out of the plan.

When a question turns on something outside this repository — what a library actually
does in the version we pin, an API's semantics, whether a behaviour changed in a
release — do not guess and do not ask the user to look it up. Invoke the `hoko-research`
skill with the specific question. It files its findings under `.ai/research/` and
reports a path; cite that path in the plan's *Decisions* so the executor can read the
evidence.

**Name the rule this change turns on, and check that it is decided.** Every change has
one: the matching criteria, the precedence order, the shape of the payload, what the
score means. If it is still open, ask what it would change. When the answer reaches the
data model, the query, a request or response schema, or the scoring, it decides the
shape of the work — everything you would build around it is written against a guess,
and the guess is what gets thrown away, not the placeholder. Say so plainly, once: the task is not ready,
and the session is better spent deciding the rule — keep grilling__SPEC_SETTLE__ — than
building scaffolding that gets rewritten when the real answer arrives.

Once. If the user wants it built anyway, build it: they have heard the cost and it is
their call. And a decision genuinely deferred behind an interface already agreed — a
threshold, a second provider, a message string — is not this. Only the rule that
decides the shape of the work counts.

Stop grilling once you can write the plan. Never fill a material gap with an
assumption — an unresolved blocker goes under **Open questions** in the plan.

**2. Read before designing.** Inspect the code the change touches and record the
existing patterns and abstractions to reuse, the test framework and where its files
live, and the exact commands to run tests and lint/typecheck.

Read the repository root's `AGENTS.md` first and take the conventions it already
states as given — that file, not the user-level one and not a nested one further down
the tree, which no agent loads until it reads a file beside it. Do not
re-derive them, do not verify them against the tree, and do not copy them into the
plan — every agent that touches this plan loads that file too, so a restatement is a
duplicate they all pay for. It is wrong only if the code contradicts it, and then the
contradiction is the finding.

When the root `AGENTS.md` does not record how the suite runs in a PHP project, resolve it in
this order and write the resolved command into the plan verbatim:

1. A `phpfpm` service named in the first compose file present —
   `python3 ${HOKO_ROOT}/scripts/in-service.py --root <repo root> --service phpfpm -- <command>`.
2. Otherwise the compose service that carries PHP-FPM under another name — same
   `python3 ${HOKO_ROOT}/scripts/in-service.py --root <repo root> --service <service> -- <command>`. Name
   the service in *Decisions* and say how you identified it.

Stop at the first that applies and record what you found, not what you assume is
there. If none applies, that is an *Open question*, not a command you invent.

If `specs/` exists at the repository root and a spec covers what this change touches,
read it first: it already states the behaviour that must hold, so the plan does not
restate it. Point at it with a `Spec:` header line naming the file, its front-matter id
and the requirements this change delivers, `Spec: specs/login.md (SPEC-012: REQ-3, REQ-5)`,
and let each step claim them as `SPEC-012/REQ-3` on its `Satisfies:` line. Write
*Requirements* only for behaviour the spec does not state. Anything the change
contradicts is an *Open question*, not a silent override.__SPEC_OFFER__ Do not
write the spec yourself here, and do not create `specs/` where the project has none.

**3. Ask which QA checks this run gets.** Always, once the grilling is done and before
you write anything: ask with the `question` tool as a multi-select, with these two options and
no others, and never skip it because the change looks small or the answer looks obvious:

- `CRAP` — scores the run's changed methods for complexity against missing coverage
  (__QA_CRAP__).
- `Mutation` — mutation-tests the files the run changed (__QA_MUTATION__).

Marking an option recommended is the default answer, not a decision: the user may take
or drop either. Record the answer in the plan as the `QA:` header line described below.

Before you ask, check whether the project's stack has a tool each check can run on:
`python3 ${HOKO_ROOT}/scripts/commands.py --root <repo root>` prints a `mutation` command, or `null` when
none resolves, and CRAP needs a clover or cobertura coverage report that carries
complexity data. When a check has no tool, say so in that option's description and name
the missing tool and its install command, so the user chooses with the cost in view.

On Go the mutation tool is `go-mutesting`
(`go install github.com/avito-tech/go-mutesting/cmd/go-mutesting@latest`). CRAP needs a
cobertura report with complexity, which Go's own coverage (`go test -coverprofile`)
does not give, so say CRAP stays unmeasured unless the project adds a tool that
produces one.

Installing a missing QA tool needs the user's explicit yes. Picking that option is the
yes: it means "add the tool", and you record it in the plan as a step that installs
it. Without the yes, install nothing — not while planning, and not in a later step.

When the project runs in Docker, that step installs the tool into the project's dev or
test image, never on the host: on Go, a Dockerfile line such as
`RUN go install github.com/avito-tech/go-mutesting/cmd/go-mutesting@latest`.

**4. Write the plan file.** Resolve its path first, with one command, before you write a
word of it:

```bash
PLANS="${HOKO_PLANS_DIR:-.ai/plans}"
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
mkdir -p "$ROOT/$PLANS"
echo "$ROOT/$PLANS/$(date +%Y%m%d%H%M%S)-<short-kebab-slug>.md"
```

Create the file at exactly that path. It is the only file you may write while planning:
do not create, copy or write anything else in the repository, and never leave plan mode
in order to write the plan — staying in plan mode until the user approves is part of the
protocol. `hoko_execute` files the plan and this cycle's prompt after approval.

Start the file with `# <title>` naming the change, then `Project: __PROJECT_NAME__`
directly under it, exactly as given — no branch or other annotation. The approval step
reads both.

When the request names a ticket key, write it as `Ticket: <KEY>` directly below
`Project:`, copied verbatim from the request — never invented, never guessed from a
branch or a file. No key in the request, no line.

Below `Project:` and the ticket line, write the user's answer to step 3 as a
`QA:` header line, always, whichever way they answered: `QA: crap, mutation`,
`QA: crap`, `QA: mutation` or `QA: none`. The `hoko-quality-assurance` agent runs exactly
the checks that line names.

Use this structure, omitting any section that would be empty:

```
## Goal               — or `## Context`, an accepted heading for the same thing;
                        either satisfies the reader
## Non-goals
## Decisions          — every answer from the grilling that constrains implementation
## Requirements       — the observable behaviour this change owes, in EARS form;
                        omit when a `Spec:` line carries it
## Test conventions   — deviations from the root `AGENTS.md` for this change only,
                        and the run command when that file does not state one; omit
                        when there are none
## Steps
### 1. <imperative title>
- Change: <what, concretely>
- Satisfies: <the requirement ids this step delivers, or `none — internal`>
- Tests: <what proves those requirements, in the project's style, naming each spec
  scenario that exercises a requirement the step claims>
- Irreversible: <what cannot be undone — only on a step whose commit revert does not
  undo its effect>
- Risks: <omit this line unless there is a concrete, specific risk>
## Verification       — manual or human checks the plan itself needs stated, never a
                        numbered step: a step carries a diff, and one that only verifies
                        has none, so it derails a run that expects to commit it. Omit
                        when there is nothing beyond the steps' own tests.
## Open questions     — omit if none
```

`## Progress` is not part of what you write: the approval step generates it from the
`### <N>.` headings once the plan is approved, one unchecked
`- [ ] <N>. <title>` box per step. Do not write the section yourself and do not carry
`Status:` lines on the steps themselves; the executor ticks the generated boxes as it
goes.

Write it for a stranger. A subagent with **no access to this conversation** will
implement from that file alone, so every decision you and the user reached must be
written down rather than assumed — with the standing exception of what the root `AGENTS.md`
already states, which the subagent loads for itself. The *Test conventions* section is
binding when it is there at all: the subagent runs exactly the command you record
there, in preference to the one `AGENTS.md` gives.

The **Requirements** section states the change's observable behaviour as numbered
`R<N>` lines in EARS form — one behaviour per line, in the project's own vocabulary,
naming the actual component rather than "the system":

    - **R1** The <component> shall <response>.
    - **R2** While <precondition>, the <component> shall <response>.
    - **R3** When <trigger>, the <component> shall <response>.
    - **R4** If <unwanted trigger>, then the <component> shall <response>.
    - **R5** Where <feature is configured>, the <component> shall <response>.
    - **R6** While <precondition>, when <trigger>, the <component> shall <response>.

Each requirement is one markdown list item; plain lines one after another render as a
single paragraph and the numbering stops being visible. One `shall` per line — an "and" joining two responses is two requirements. Nothing
that cannot fail a test: "shall be efficient", "shall handle errors gracefully" and
"shall be robust" are not requirements. Nothing about implementation either; how it is
built belongs in *Decisions*, what it does belongs here.

Omit the section entirely when the change has no externally observable behaviour — a
rename, an extraction, a dependency bump, a pure refactor. Never invent requirements
to fill it and never restate a Decision as one.

Every requirement must be claimed by exactly one step's `Satisfies:` line. A
requirement no step claims is a hole in the plan; a step that claims none is internal
plumbing and says so.

A plan with a `Spec:` line needs no *Requirements* section for what that line lists:
the spec holds the behaviour, so the plan holds only the steps. Every `REQ-N` the line
lists must exist in the named spec and be claimed by exactly one step as
`<spec id>/REQ-N`, and a step may claim only what the line lists. A plan may carry both
a `Spec:` line and *Requirements* of its own, and a step claims from either.

A step is *irreversible* when reverting its commit does not undo its effect, as with a
datastore schema migration or a change to a queue or payload contract. Add
`- Irreversible: <what cannot be undone>` to each such step and to no other. The line
is a marker for the human reviewing before merge: nothing pauses before the step.

When a `Spec:` line names a spec whose scenarios exercise a requirement a step claims,
name each such scenario by its title on that step's `Tests:` line, so the implementer
adds a test that runs that scenario's case.

Step rules: a step is the largest chunk that still reviews cleanly in one sitting.
Prefer fewer, coherent steps — never split work to hit a count. Each step must leave
the repo green and be independently committable, and the order must not break anything
between commits — an interface change lands together with its implementations in the
same step, not split across two that would leave the repo red in between.

Approval gates on this lint, and the lint splits blocking findings from
advisory ones: only a structural problem — no `## Steps` or numbered step, a duplicate
or gapped step number, a `Satisfies:` naming an undeclared requirement, a requirement no
step claims or two claim, a requirement with no ` shall `, a `Spec:` line whose file or
requirement does not exist, a `<spec id>/REQ-N` claim the line does not list or a listed
one no step claims — denies the call and hands
those back as the reason. Everything else it finds — banned or implementation words in
a requirement, a file citation, a missing or free-text `Satisfies:`, a missing `## Goal`
when there is no `## Context` either, a step titled to verify rather than change — is
advisory: printed as a note, never denying. Run it yourself first anyway — it saves the
round trip:

```bash
python3 "${HOKO_ROOT}/scripts/plan-lint.py" --plan "<absolute plan path>"
```

A clean run is silent; one with only notes still goes through. It decides nothing about
whether the plan is any good — only what a machine can settle: a requirement no step
claims, a requirement that could not fail a test, a path that is not in the repository.
Fix the plan rather than the finding, blocking or advisory. If a finding is genuinely
wrong, say which and why in the same message as the plan, rather than leaving it
unmentioned.

Then post the plan and ask for approval in one line, and wait. Approval is the user's
move, not yours: it calls `hoko_execute`, which hands the plan to the build agent.

**If this task is too small to need a plan** — a rename, a config or dependency bump, a
bugfix with a known cause, anything that would land as one commit — say so and leave
plan mode instead of writing a plan. The delegation machinery costs more than it saves
on small work.\
"""


def qa_recommendation(key):
    on = settings.render(settings.get(key)) == "true"
    return "pre-selected, recommended" if on else "not pre-selected: the settings turn it off"


GRILL = GRILL.replace("__QA_CRAP__", qa_recommendation("crap")).replace(
    "__QA_MUTATION__", qa_recommendation("mutation")
)

if settings.render(settings.get("specs")) == "true":
    SPEC_SETTLE = ", or invoke\n`hoko-feature-specs` to settle it from intent"
    SPEC_OFFER = (
        " If the change adds a capability that deserves a spec and has none —\n"
        "rules with thresholds or precedence, a contract with something outside the repo,\n"
        "behaviour on bad input — say so and offer `hoko-feature-specs` before planning."
    )
else:
    SPEC_SETTLE = ""
    SPEC_OFFER = ""
GRILL = GRILL.replace("__SPEC_SETTLE__", SPEC_SETTLE).replace("__SPEC_OFFER__", SPEC_OFFER)


def resolved_project_name(cwd):
    """The project name the plan's `Project:` line should carry — cwd is trustworthy
    here, unlike at approval time, so this needs none of journal.py's anchor
    fallback."""
    root = journal.project_root(Path(cwd or os.getcwd()))
    if root is None or root == Path.home() or root.name in ("", ".", "/"):
        return "unsorted"
    return journal.slugify(root.name)


def grill_for(cwd):
    return GRILL.replace("__PROJECT_NAME__", resolved_project_name(cwd))


# A line that looks like a way to run the suite. Crude on purpose: this decides whether
# the planner trusts the file or resolves the command itself, not whether it is correct.
# A bare `phpunit` mention does not count: PHP always runs through the container ladder
# above now, so only a command that shows the wrapper (docker compose, in-service.py) is
# trusted for PHP.
RUNS_TESTS = re.compile(
    r"docker\s+compose\s+(?:-f\s+\S+\s+)?(?:run|exec)|in-service\.py"
    r"|composer\s+(?:run\s+)?test"
    r"|pytest|go\s+test|cargo\s+test|(?:npm|yarn|pnpm)\s+(?:run\s+)?test",
    re.I,
)

CONVENTIONS = {
    "absent": """

**The repository root has no `AGENTS.md`.** Nothing states the project's conventions,
so resolve the test command yourself as above and write it into the plan. In the same
message that presents the plan, before asking for approval, offer to start a root `AGENTS.md`
holding the command and the conventions you had to discover — otherwise the next plan
pays for this pass again.""",
    "silent": """

**The root `AGENTS.md` does not record how the suite runs.** Trust what it does say,
resolve the command as above, and write it into the plan. In the same message that
presents the plan, before asking for approval, offer to add it to `AGENTS.md`, so no later
plan has to rediscover it.""",
    "records": """

**The root `AGENTS.md` records how the suite runs.** Use it as written. Do not verify it
against the tree, do not resolve the ladder, and do not copy it into the plan.""",
}


def repo_root(start):
    """The nearest ancestor holding a .git. The home directory is never a project."""
    home = Path.home()
    try:
        start = Path(start).expanduser().resolve()
    except OSError:
        return None
    if start == home:
        return None  # opencode reports home when it does not know the cwd
    for candidate in (start, *start.parents):
        if candidate == home or candidate.parent == candidate:
            break
        if (candidate / ".git").exists():
            return candidate
    return None


def conventions_note(cwd):
    """What the planner can take on trust, decided here rather than guessed there."""
    root = repo_root(cwd or os.getcwd())
    if root is None:
        return ""
    try:
        text = (root / "AGENTS.md").read_text(encoding="utf-8")
    except OSError:
        return CONVENTIONS["absent"]
    return CONVENTIONS["records" if RUNS_TESTS.search(text) else "silent"]


def grill_command(argv):
    parser = argparse.ArgumentParser(prog="plan-flow.py grill", description=__doc__)
    parser.add_argument("--root", default=None)
    args = parser.parse_args(argv)
    cwd = args.root or os.getcwd()
    print(grill_for(cwd) + conventions_note(cwd))
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] != "grill":
        print("usage: plan-flow.py grill [--root <dir>]", file=sys.stderr)
        sys.exit(2)
    sys.exit(grill_command(sys.argv[2:]))

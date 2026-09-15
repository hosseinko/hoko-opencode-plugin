---
name: hoko-feature-specs
description: >-
  Write a feature spec into the repository's `specs/` folder — numbered EARS requirements,
  selective Gherkin acceptance criteria and short design notes, one file per capability —
  either from intent before the code exists or derived from code that already runs, and read
  them back when someone asks what a feature is supposed to do.
  Use when asked to write, generate or update a spec, to specify or document what a feature
  or an existing component does, or to check the code against its spec.
---

# Feature specs

A spec answers one question: **what must this do?** Not what we are changing this week —
that is a plan. Not how it does it — that is the code, and a spec that restates the code
is a second copy to keep honest. Not why it ended up this way either: the reasoning behind
a choice belongs in the plan that made it and the commit that landed it.

| Artifact | Question | Lives | Horizon |
| --- | --- | --- | --- |
| Spec — `specs/` | What must this do? | repo | as long as the feature |
| Plan — the plans directory (`.ai/plans/`, `HOKO_PLANS_DIR`) | What are we changing now? | repo | one run |
| Journal | What happened in that run? | outside the repo | history |

Two rules keep them apart. A spec is **present tense and impersonal** — no "we decided", no
"will be added", no dates. And a spec describes **observable behaviour**: if a statement
cannot be wrong from outside the component, it is a design note, not a requirement.

## Where they live

```
specs/
  README.md                     the index table
  supplier-record-clustering.md
  address-normalisation.md
```

`specs/` at the repo root. One file per capability, kebab-slug, no subdirectories until
there are more than about fifteen — then group by bounded context, not by file tree.

If `specs/` does not exist, ask before creating it, and seed `specs/README.md` with the
index header.

## When one is worth writing

The bar: **would a new colleague be wrong about this if they only read the code?**

Worth a spec:

- Rules with thresholds, precedence or tie-breaks — matching, scoring, deduplication
- A contract with something outside the repo — a supplier feed, a published API, a queue
- Behaviour on bad input: what is rejected, what is repaired, what is dropped silently
- Anything whose failure is a data incident rather than a stack trace
- A capability several people touch, or one nobody has touched in a year

Not worth one: CRUD with no rules, a wrapper, anything whose whole behaviour is its
signature, a bug fix, a refactor. **A spec per module is a specs folder that nobody reads.**
Say so rather than producing one — a declined spec is a good outcome.

Never write the file unprompted. Draft in the conversation, write once the user agrees.

## Size

One capability, one file, **two pages at most**. Past that, it is two capabilities — split it
and say why, rather than letting the file grow. Eight to fifteen requirements is a healthy
spec; thirty means the boundary is wrong.

A spec is not proportional to the work. A two-line change to a specified rule edits one `REQ`
line; it does not open a spec cycle.

## Two ways in

### From code that already runs

The common case here, and the one where the temptation to invent is strongest.

1. **Read before writing.** Delegate to the `explore` subagent when it spans more than a couple
   of files: entry points, the branch and threshold constants, the error and reject paths,
   and the tests — tests state intent the code does not.
2. **Derive, never assume.** Every requirement must be traceable to a line you read. A
   plausible behaviour you did not find in the code does not go in the file.
3. **Record what you could not settle.** Behaviour that is unreachable, contradicted between
   two call sites, or decided by a config value with no documented default goes in an
   `## Open questions` section — not as a confident `shall`.
4. **Contradictions are not yours to resolve.** Where the code plainly does something nobody
   would ask for, say so and ask: is that the requirement, or a bug? Write the answer, not
   the guess. If the user is not there to ask, specify the code's actual behaviour and flag
   the line.

### From intent, before the code exists

1. If the request is a sentence, it is not a spec yet — run `hoko-grill-me` first. A spec
   written from an unexamined one-liner is the failure mode the whole approach exists to
   prevent.
2. Grill toward the five EARS buckets: the always-true rule, the state-dependent one, the
   event, the optional feature, the unwanted-input path. An empty bucket is a question
   nobody asked, and the unwanted-input bucket is empty far more often than it should be.
3. Write the spec, get agreement on it, *then* plan. The plan's `## Requirements` are the
   subset this change delivers, carrying the spec's ids: `R1 (SPEC-012/REQ-3) …`.

## Template

````markdown
---
id: SPEC-NNN
title: <capability, as a noun phrase>
covers:
  - src/path/**
status: draft | accepted | superseded by SPEC-NNN
---

# <title>

## Context

What this capability is for, who calls it, what it assumes is already true, and any term
a reader must know to read the requirements. One paragraph, five lines at most.

## Requirements

REQ-1  The <component> shall <response>.
REQ-2  While <state>, the <component> shall <response>.
REQ-3  When <trigger>, the <component> shall <response>.
REQ-4  If <bad input or failure>, then the <component> shall <response>.

## Acceptance criteria

```gherkin
Scenario: <the case worth automating>
  Given <context>
  When <the one action>
  Then <the observable outcome>
```

## Design notes

How it currently works, and the numbers behind the requirements: why 0.72, which index,
what the blocking strategy is. This section ages fastest and binds nobody.

## Open questions

- <what the code or the conversation did not settle>
````

Drop `## Acceptance criteria` or `## Open questions` when empty. Never leave a placeholder.

## Writing the requirements

`reference/requirement-grammar.md` carries the EARS patterns, the wording rules and
worked bad-to-good rewrites. **Read it before writing the requirements section** — the
rules are short and getting them wrong is the whole difference between a spec and a wish.

The four that catch the most:

- **`shall` is the only binding word.** `will` states a fact, `should` states a hope;
  neither is a requirement. A line without `shall` is not a `REQ`.
- **One thought per line.** An `and` joining two behaviours is two requirements.
- **No implementation.** A library, a class, a query or a table name in a `REQ` line is a
  design note in the wrong section.
- **Verifiable or it is not a requirement.** "efficiently", "robustly", "as appropriate",
  "handles errors gracefully" — if you cannot name the observation that would prove it
  false, cut it or make it measurable.

Ids are permanent. Renumbering breaks every plan and review that cited them; a deleted
requirement's id is retired, not reused.

## Acceptance criteria: be selective

Write a Gherkin scenario **only where the case is worth executing** — the threshold, the
precedence rule, the rejection path. Everything else is prose in the `REQ` line.

Criteria attached to every requirement is how specs become tedious to review and then stop
being read. If the scenarios cannot run in this repo, write fewer of them, not more.

Declarative, in the domain's language: `When the record is scored against its block`, never
`When I call scorer.run(record, block)`.

## Before it lands

Check the draft against the code, requirement by requirement, and classify each one:
**confirmed** by a line you read, **contradicted**, or **unverifiable** from the code alone.
Report the contradicted and unverifiable ones — those are the spec's actual value on a
legacy component. Never let an unconfirmed requirement into the file as a plain `shall`.

Then read the whole thing back and cut: anything the signature already says, anything
restating the code, any sentence that would be true of any component.

## Index

`specs/README.md`:

```markdown
# Specs

| Spec | Capability | Status |
|------|------------|--------|
| [SPEC-001](supplier-record-clustering.md) | Supplier record clustering | accepted |
| [SPEC-002](address-normalisation.md) | Address normalisation | draft |
```

## Reading them back

Asked what a feature is supposed to do:

1. No `specs/` — say so, answer from the code, and offer to write one.
2. Scan the index, read the matching spec, answer from its requirements, and say which
   `REQ` ids the answer rests on.
3. A spec exists but the code disagrees — report both. Do not quietly prefer either: the
   code is the truth about behaviour, the spec is the truth about intent, and which one is
   wrong is a decision for the user.

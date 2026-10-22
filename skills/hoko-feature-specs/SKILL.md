---
name: hoko-feature-specs
description: >-
  Write a feature spec into the repository's `specs/` folder — numbered EARS requirements,
  selective Gherkin acceptance criteria and short design notes, one file per capability —
  either from intent before the code exists or derived from code that already runs, and read
  them back when someone asks what a feature is supposed to do.
  Use when asked to write, generate or update a spec, to specify or document what a feature
  or an existing component does, or to check the code against its spec.
  Disabled unless the `specs` setting is on.
---

# Feature specs

Run `python3 "${HOKO_ROOT}/scripts/settings.py" specs` first. On `false`, say spec
writing is switched off in `hoko.json` and stop — do not read further or write anything.
The one exception is `hoko-spec-writer` in a `/hoko/task` run that names a local spec path
(see *In a task*): it writes that file whatever the setting says.

A spec answers one question: what must this do? Not what we are changing this week —
that is a plan. Not how it does it — that is the code, and a spec that restates the code
is a second copy to keep honest. Not the story of the choice either: the history of how it
was decided belongs in the plan and the commit.

| Artifact | Question | Lives | Horizon |
| --- | --- | --- | --- |
| Spec — `specs/` | What must this do? | repo | as long as the feature |
| Plan — the plans directory (`.ai/plans/`, `HOKO_PLANS_DIR`) | What are we changing now? | repo | one run |
| Journal | What happened in that run? | outside the repo | history |

Two rules keep them apart. A spec is present tense and impersonal — no "we decided", no
"will be added", no dates. And a spec describes observable behaviour: if a statement
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
index header. In a plan run, create it without asking (see *In a plan run*).

## When one is worth writing

Specs are per behaviour, not per change. A feature, a fix or a refactor that touches a
behaviour means that behaviour has an up-to-date spec afterwards; the spec follows the
capability, whatever kind of change reached it. Only a diff that touches no behaviour at
all — docs, CI config, dependency bumps, tooling, test-only changes — writes nothing.

What goes in a spec is what a new colleague would get wrong from the code alone:

- Rules with thresholds, precedence or tie-breaks — matching, scoring, deduplication
- A contract with something outside the repo — a supplier feed, a published API, a queue
- Behaviour on bad input: what is rejected, what is repaired, what is dropped silently
- Anything whose failure is a data incident rather than a stack trace

Keep the spec to that: CRUD with no rules, a wrapper, anything whose whole behaviour is
its signature is one or two short requirements, not a page. A spec per module is a
specs folder that nobody reads — name the capability, not the file.

Interactive use: never write the file unprompted. Draft in the conversation, write once the
user agrees. A plan run is the one exception — see *In a plan run*.

## Size

One capability, one file, two pages at most. Past that, it is two capabilities — split it
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
2. **Derive, do not assume.** Every requirement must be traceable to a line you read. A
   plausible behaviour you did not find in the code does not go in the file.
3. **Record what you could not settle.** Behaviour that is unreachable, contradicted between
   two call sites, or decided by a config value with no documented default goes in an
   `## Open questions` section — not as a confident `shall`.
4. **Contradictions are not yours to resolve.** Where the code plainly does something nobody
   would ask for, say so and ask: is that the requirement, or a bug? Write the answer, not
   the guess. If the user is not there to ask, specify the code's actual behaviour and flag
   the line.

### From intent, before the code exists

1. If the request is a sentence, it is not a spec yet — run `grill-me` first. A spec
   written from an unexamined one-liner is the failure mode the whole approach exists to
   prevent.
2. Grill toward the five EARS buckets: the always-true rule, the state-dependent one, the
   event, the optional feature, the unwanted-input path. An empty bucket is a question
   nobody asked, and the unwanted-input bucket is empty far more often than it should be.
3. Write the spec, get agreement on it, *then* plan. The plan points at the spec with a
   `Spec:` line naming the requirements this change delivers, and its steps claim them by
   id (`SPEC-012/REQ-3`) instead of restating them.

## Template

````markdown
---
id: SPEC-NNN
title: <capability, as a noun phrase>
covers:
  - src/path/**
---

# <title>

## Context

What this capability is for, who calls it, what it assumes is already true, and any term
a reader must know to read the requirements. One paragraph, five lines at most.

## Requirements

- **REQ-1** The <component> shall <response>.
- **REQ-2** While <state>, the <component> shall <response>.
- **REQ-3** When <trigger>, the <component> shall <response>.
- **REQ-4** If <bad input or failure>, then the <component> shall <response>.

## Acceptance criteria

```gherkin
Scenario: <the case worth automating>
  Given <context>
  When <the one action>
  Then <the observable outcome>
```

## Design notes

How it currently works, and the numbers behind the requirements: which index, what the
blocking strategy is. An entry may give the basis of a number or a non-obvious choice in one
clause ("0.72, the cut-off that separated the labelled duplicates in the sample"); the story
of how it was decided stays out. This section ages fastest and binds nobody.

## Open questions

- <what the code or the conversation did not settle>
````

Drop `## Acceptance criteria` or `## Open questions` when empty. Never leave a placeholder.

## Writing the requirements

`reference/requirement-grammar.md` carries the EARS patterns, the wording rules and
worked bad-to-good rewrites. **Read it before writing the requirements section** — the
rules are short and getting them wrong is the whole difference between a spec and a wish.

Each requirement is one list item: `- **REQ-N** <sentence>`. Consecutive plain lines
collapse into one paragraph when the file is rendered, which is how a numbered list of
requirements turns into a wall of prose. The same holds everywhere the spec lists
one-line items — open questions, the index rows, a set of covered paths.

The four that catch the most:

- `shall` is the only binding word. `will` states a fact, `should` states a hope;
  neither is a requirement. A line without `shall` is not a `REQ`.
- One thought per line. An `and` joining two behaviours is two requirements.
- No implementation. A library, a class, a query or a table name in a `REQ` line is a
  design note in the wrong section.
- Verifiable or it is not a requirement. "efficiently", "robustly", "as appropriate",
  "handles errors gracefully" — if you cannot name the observation that would prove it
  false, cut it or make it measurable.

Ids are permanent. Renumbering breaks every plan and review that cited them; a removed
requirement's id is retired, not reused. A requirement dropped from a living spec keeps its
line as `- **REQ-N** _Retired._`.

## Acceptance criteria: be selective

Write a Gherkin scenario only where the case is worth executing — the threshold, the
precedence rule, the rejection path. Everything else is prose in the `REQ` line.

Criteria attached to every requirement is how specs become tedious to review and then stop
being read. If the scenarios cannot run in this repo, write fewer of them, not more.

Declarative, in the domain's language: `When the record is scored against its block`, never
`When I call scorer.run(record, block)`.

## Before it lands

Check the draft against the code, requirement by requirement, and classify each one:
confirmed by a line you read, contradicted, or unverifiable from the code alone.
Report the contradicted and unverifiable ones — those are the spec's actual value on a
legacy component. Never let an unconfirmed requirement into the file as a plain `shall`.

Then read the whole thing back and cut: anything the signature already says, anything
restating the code, any sentence that would be true of any component.

## Index

`specs/README.md`:

```markdown
# Specs

| Spec | Capability |
|------|------------|
| [SPEC-001](supplier-record-clustering.md) | Supplier record clustering |
| [SPEC-002](address-normalisation.md) | Address normalisation |

## Retired

- SPEC-003
```

The `## Retired` heading appears only once a spec has been retired. A capability that no
longer exists has its spec file and index row deleted and its id listed there, so the id is
never reused. A new `SPEC-NNN` is one above the highest id in the index, the retired list
included.

## In a plan run

`hoko-spec-writer` follows this section at the end of a `/hoko/execute-plan` run. It overrides
"never write unprompted" and "ask before creating `specs/`" for that mode only; everything
else in this skill still holds. Nobody is there to agree a draft, so the spec is written
from evidence and its doubts are recorded in it.

1. **Read the run.** Read the run's diff and the plan. List the behaviours the diff
   touches — a behaviour is something observable from outside the component.
2. **Reconcile or derive.** Where the plan has a `Spec:` line, the spec was written up front
   and states intent, so check the code against it instead of rewriting it from the code:
   - A listed requirement the diff confirms stays as the spec states it.
   - A listed requirement the diff contradicts keeps its text unchanged; record the
     contradiction under that spec's `## Open questions` (step 6).
   - Behaviour the diff adds beyond the listed requirements gets requirements derived from
     the code, as in *From code that already runs*.

   Where the plan has no `Spec:` line there is nothing upfront to reconcile: write the
   requirements of each behaviour the diff touches from the code, the plan saying what was
   intended.
3. **Find the covering spec.** Match each behaviour against the index: first by the
   `covers:` globs of every spec, then by capability. Update the spec that covers it —
   add or retire `REQ` lines, widen `covers:` when the diff reaches new paths — and, with no
   `Spec:` line, edit its requirements to match the code after the run.
4. **Create where none covers it.** Write a new spec for that capability, as in *From code
   that already runs*, with the id set by the rule under *Index*. If `specs/` does not exist,
   create it and its `README.md` index without asking.
5. **Retire what is gone.** A run that removes a capability deletes its spec file and index
   row and lists its id under `## Retired`. A requirement removed from a living spec becomes
   `- **REQ-N** _Retired._`.
6. **Record contradictions.** Where the plan's intent and the code disagree, or the code does
   something nobody would ask for, put it under the spec's `## Open questions`, not in a
   confident `shall`, and never change the text of a listed requirement to match.
7. **Write nothing on a behaviour-free diff.** Docs, CI config, dependency bumps, tooling and
   test-only changes touch no behaviour: no file, no index row, no commit.
8. **Touch only `specs/`.** Edit no non-spec file, and keep the index table in step
   with the files.

Before it lands, run *Before it lands* against the code. Report what changed per file — spec
id and `REQ` ids added, changed or retired.

## In a task

`hoko-spec-writer` follows this section for `Mode: write` and `Mode: revise` in a
`/hoko/task` run. The spec is written before the plan, from intent, so it overrides "never
write unprompted" and "get agreement" for that mode only. The `hoko-specifier` has already
grilled the prompt, so `scope.json` and `answers.json` stand where the conversation would. A
product doubt they leave open is a question handed back (`needs_input`), not a guess written
as a `shall`.

1. **write.** Follow *From intent, before the code exists* with the grilling already done:
   find the spec that covers the capability by the index and the `covers:` globs and edit
   it, or create one with the id *Index* prescribes (and `specs/` with its `README.md`,
   without asking). Write only the requirements this change delivers or alters, in EARS
   form. If the prompt names an existing spec file, that file is the spec.
2. **revise.** The planner found requirements that cannot be delivered as written. Change
   those, and only those, to what can be planned against.
3. **Local spec.** When the prompt says the `specs` setting is off and names a path, write
   one file there: the template above with `id: SPEC-LOCAL` in the front matter, no index
   row and nothing under `specs/`. The plan lint reads the id from the front matter, so a
   plan's `Spec:` line names this file the same way.
4. **Report the ids.** The hand-off lists every requirement the change delivers as
   `<spec id>/REQ-N`, never a retired one, so the planner can claim each exactly once.

## Reading them back

Asked what a feature is supposed to do:

1. No `specs/` — say so, answer from the code, and offer to write one.
2. Scan the index, read the matching spec, answer from its requirements (skipping lines
   marked `_Retired._`), and say which `REQ` ids the answer rests on.
3. A spec exists but the code disagrees — report both. Do not quietly prefer either: the
   code is the truth about behaviour, the spec is the truth about intent, and which one is
   wrong is a decision for the user.

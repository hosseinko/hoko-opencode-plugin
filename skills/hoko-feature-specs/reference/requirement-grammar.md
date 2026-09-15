# Requirement grammar

The sentence rules behind a spec's `## Requirements` and `## Acceptance criteria`
sections. EARS gives the shape, the wording rules make it verifiable, Gherkin makes the
cases that matter executable.

---

## EARS — the six patterns

A requirement has zero or many preconditions, zero or one trigger, one component name,
and one or many responses, in this order:

> **While** `<precondition>`, **when** `<trigger>`, the `<component>` **shall**
> `<response>`.

Every requirement is one of six shapes. If a line fits none of them, it is not yet a
requirement.

### 1. Ubiquitous — always true

> The `<component>` shall `<response>`.

- The clustering service shall assign every accepted record to exactly one cluster.
- The parser shall emit UTF-8 output regardless of input encoding.

Use for invariants. If it is only true sometimes, it is pattern 2 or 3.

### 2. State-driven — true while a state holds

> **While** `<state>`, the `<component>` shall `<response>`.

- While a full reindex is in progress, the search API shall serve results from the
  previous index generation.
- While the supplier feed is marked stale, the matcher shall exclude its records from
  new clusters.

`While` describes a condition that persists, not a moment.

### 3. Event-driven — a response to something that happens

> **When** `<trigger>`, the `<component>` shall `<response>`.

- When a record's match score is at or above 0.72, the clustering service shall merge it
  into the candidate cluster.
- When a supplier delivers a record whose id is already clustered, the ingester shall
  replace the stored record and re-score its cluster.

The most common pattern, and the one most often written without its trigger. A `shall`
with no `when` and no `while` is claiming to be an invariant — check that it is.

### 4. Optional feature — true only where a feature is present

> **Where** `<feature is included>`, the `<component>` shall `<response>`.

- Where geocoding is enabled, the normaliser shall attach coordinates to every accepted
  address.

For build flags, tiers, per-tenant features. Not for runtime state — that is pattern 2.

### 5. Unwanted behaviour — bad input, failure, abuse

> **If** `<trigger>`, **then** the `<component>` shall `<response>`.

- If a record is missing both coordinates and a postal address, then the ingester shall
  reject it and emit a `record.unmatchable` event.
- If the scoring service does not respond within 2 s, then the matcher shall retry once
  and, on a second timeout, leave the record unclustered.

**This is the bucket that is empty when it should not be.** A spec with no `if` lines
has almost certainly not been asked what happens when things go wrong.

### 6. Complex — a precondition and a trigger together

> **While** `<state>`, **when** `<trigger>`, the `<component>` shall `<response>`.

- While a full reindex is in progress, when a record is ingested, the ingester shall
  queue it rather than index it.

Two keywords is the limit. Three means two requirements.

---

## Wording rules

### `shall`, `will`, `should`

| Word | Means | In a spec |
| --- | --- | --- |
| **shall** | binding requirement | the only word a `REQ` line may use |
| **will** | statement of fact about the world | belongs in Context |
| **should** | a goal, an aspiration | belongs in Design notes, or nowhere |

"The importer should skip duplicates" is not a requirement. Either it must, or it is not
in the spec.

### One thought per line

One subject, one predicate. An `and` joining two behaviours is two requirements; an `and`
joining two objects of the same behaviour is fine.

- Split: "shall validate the record **and** write it to the index" → two `REQ` lines.
- Keep: "shall reject records missing **both** coordinates **and** a postal address".

### No implementation

A requirement says *what is observable*, never *how*. A class name, a library, a table, a
query, a file path in a `REQ` line means the sentence belongs in Design notes.

- Wrong: "The matcher shall use an OpenSearch `terms` query to fetch the block."
- Right: "The matcher shall score each record against every record sharing its block key."
  The query shape is a design note.

The test: could this requirement survive a rewrite of the component? If not, it is
describing the current implementation.

### Verifiable, or cut it

Every requirement must name an observation that could prove it false. These words never
survive that test:

> efficient, robust, flexible, adequate, user-friendly, fast, scalable, reliable,
> reasonable, appropriate, seamless, as needed, as appropriate, etc., and so on,
> maximise, minimise, optimise, improve, support, handle, manage, process

Most of them hide a missing number. "shall be fast" → "shall return within 200 ms at the
99th percentile over a one-minute window".

`support`, `handle`, `manage` and `process` hide a missing behaviour: *handle how?*

### Numbers carry units and tolerance

"within 200 ms", "at or above 0.72", "at most 5 000 records per batch". A bare number
with no unit and no comparison direction is ambiguous about its own boundary — say `at or
above`, not `above`, when the boundary is inclusive.

### No indefinite pronouns

"this", "that", "these", "it" — name the thing. A requirement is read alone, out of order,
by someone who has not read the line before it.

### No TBD

A requirement that cannot be stated goes in `## Open questions`, not in the requirements
list with a placeholder. A `REQ` line is a commitment.

### Ids are permanent

`REQ-7` means one thing forever. Deleting a requirement retires its id; it is never
reused, and the list is never renumbered to close a gap. Plans, reviews and commit
messages cite these ids.

---

## Worked rewrites

| Wish | Requirement |
| --- | --- |
| The system should handle bad addresses gracefully. | **If** an address fails normalisation, **then** the ingester **shall** store the raw address, mark the record `address_unparsed` and continue processing the batch. |
| Matching must be fast and accurate. | **When** a record is submitted for matching, the matcher **shall** return a result within 500 ms at the 95th percentile. *(accuracy is a separate, separately measurable requirement — or an open question)* |
| The service uses Redis to cache scores. | *Design note.* The requirement behind it: **When** the same record pair is scored twice within one run, the scorer **shall** return identical scores. |
| Duplicates are removed. | **When** two records in a cluster share a supplier id, the deduplicator **shall** retain the most recently delivered one and discard the other. |
| It should support multiple suppliers. | **Where** a supplier is configured with a field mapping, the ingester **shall** accept its feed without code changes. |
| The API will return 404 for unknown ids. | **If** a cluster id is not found, **then** the API **shall** respond `404` with an `error.code` of `cluster_not_found`. *(`will` → `shall`)* |

---

## Gherkin — for the cases worth executing

A scenario is one concrete example of one requirement. Write them **only** where the case
is worth running as a test; prose in the `REQ` line covers the rest.

```gherkin
Feature: Supplier record clustering

  Background:
    Given a block containing the seed record "H-1001"

  Scenario: a record at the merge threshold joins the cluster
    When a record scoring 0.72 against "H-1001" is submitted
    Then the record is merged into the cluster of "H-1001"

  Scenario: a record just below the threshold stays alone
    When a record scoring 0.71 against "H-1001" is submitted
    Then the record is placed in a singleton cluster

  Scenario Outline: unmatchable records are rejected
    When a record with <coordinates> and <address> is submitted
    Then the record is rejected with "record.unmatchable"

    Examples:
      | coordinates | address |
      | absent      | absent  |
      | absent      | blank   |
```

Structure: `Feature` groups scenarios; `Background` holds `Given` steps shared by all of
them; `Rule` groups scenarios under one business rule when a feature has several;
`Scenario Outline` plus `Examples` covers a table of cases; `@tags` group features for
selective runs. Steps run in order and chain with `And` and `But`. A step takes a data
table (pipe-delimited rows) or a doc string (triple quotes) when one value is not enough.

Four rules that keep scenarios readable:

- **One `When` per scenario.** Two actions is two scenarios, or the first one is setup and
  belongs in `Given`.
- **Declarative, not imperative.** `When the record is scored against its block`, never
  `When I call scorer.run(record, block)`. The scenario must survive a refactor.
- **The domain's words.** Use the vocabulary the team and the suppliers use — the same
  terms the spec's Context section defines.
- **`Then` asserts something observable.** A database row is observable; an internal call
  is not.

Name each scenario after the case, not the mechanics: "a record at the merge threshold
joins the cluster", not "test threshold".

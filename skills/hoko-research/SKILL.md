---
name: hoko-research
description: Answer one question from sources outside this repository — library or API documentation for the pinned version, release notes, specs — and file the findings with citations under .ai/research/. Use when a decision turns on external behaviour, when documentation must be checked before implementing, or when asked to research or investigate something this codebase cannot answer.
---

# Research

Question: the question the user asked, in full.

If that is empty, ask what I want researched and stop.

Launch the `hoko-researcher` subagent with the question rather than researching in your own
context: it has web access, files its findings, and reports a path plus the short answer,
so the evidence outlives the session and costs you almost nothing to carry.

Its prompt must be self-contained, because it starts with an empty context:

> Research this and file the findings: `<the question, in full>`
>
> Follow your protocol: pin the version from this repo's manifests, prefer primary
> sources for that version, fetch what you cite, keep verified claims separate from
> inferences, write the file under `.ai/research/`, and report the path plus the answer
> and any caveat that would change what gets built.

Add the repository path and the dependency in question if the question alone does not
say which project it is about.

When it returns, report the verdict and the path in one or two lines. If a plan or a
decision rests on this, cite that path in the plan's *Decisions* section rather than
copying the findings into it.

A question this codebase answers on its own is not research — read the code, or use the
`explore` subagent.

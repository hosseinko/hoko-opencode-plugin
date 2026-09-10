---
name: grill-me
description: Interview the user relentlessly about a plan or design until reaching shared understanding, resolving each branch of the decision tree. Use when the user wants to stress-test a plan, get grilled on their design, or mentions "grill me".
---

Interview me relentlessly about every aspect of this plan until we reach a shared
understanding. Walk down each branch of the design tree, resolving dependencies
between decisions one-by-one. For each question, provide your recommended answer.

Ask the questions one at a time — use the `question` tool when it is available so
I can pick an answer, otherwise ask in prose and wait for my reply.

If a question can be answered by exploring the codebase, explore the codebase
instead. Delegate that exploration to the `explore` subagent when the answer
needs more than a couple of reads.

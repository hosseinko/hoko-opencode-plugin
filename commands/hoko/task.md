---
description: Run a task end to end through the pipeline — refine, spec, plan, implement, QA, review — stopping only for product decisions
agent: build
---

<!-- hoko:command -->
Task: $ARGUMENTS

If that is empty, ask what the task is and stop.

Invoke the `hoko-task` skill and follow it from the top: start the task, then repeat
`task.py next` and dispatch the one action it prints, until `task.py finish` or
`task.py stop`. You conduct the pipeline and write no implementation code.

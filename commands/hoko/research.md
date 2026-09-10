---
description: Research an external question in a subagent and file the findings under .ai/research/
agent: hoko-researcher
---

<!-- hoko:command -->
Research this and file the findings:

$ARGUMENTS

If that is empty, say what you need to be asked and stop.

Follow your protocol: pin the version from this repo's manifests, prefer primary sources
for that version, fetch what you cite, keep verified claims separate from inferences,
write the file under `.ai/research/`, and report the path plus at most five lines.

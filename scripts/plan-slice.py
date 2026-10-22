#!/usr/bin/env python3
"""
plan-slice.py — cut one step out of a plan, for the subagent that implements or
reviews it.

Ships with the `hoko` plugin.

The executor and the reviewer are each told to read the plan, and the Read tool loads
all of it: every step's body, once per subagent, once per step. Everything before the
steps is shared context and stays. The other steps' bodies do not — the ones behind
this step are committed code by now, and the ones ahead are out of scope by the
executor's own rules. What survives of them is the `## Progress` checklist, which
carries the titles and how far the run has got in one line each. Every other section
is carried whether the template names it or not.

    plan-slice.py --plan <path> --step <N>

Prints the slice's path, written by default to `.slices/` next to the plan file —
under the repository's own plans directory when the plan is filed there, so the same
`.gitignore` entry that covers the plans directory covers this too. Exits non-zero,
saying what it could not find, when the plan does not parse — the caller then hands
over the plan itself. A slice that quietly dropped the step would derail the run in a
way nobody notices until the diff is wrong.
"""

import argparse
import hashlib
import sys
from pathlib import Path

import plan_format

# Everything but the steps is shared context and is carried whole, named section or
# not: a plan that predates the template, or one that grew a section of its own, would
# otherwise reach the executor with that section silently gone.
DROP = ("steps",)

HEADER = """\
<!--
  Step {step} of {total}, cut from {plan}
  That file is the plan; this is a working copy of the part you were given. Do not edit
  either one. Everything the plan says outside the steps is reproduced here in full.
-->
"""


def die(message):
    print(f"plan-slice: {message}", file=sys.stderr)
    sys.exit(1)


def steps(body):
    """(number, full text) per `### <N>.` heading inside the Steps section."""
    marks = plan_format.step_matches(body)
    return [
        (int(m.group(1)), body[m.start():(marks[i + 1].start() if i + 1 < len(marks) else len(body))].rstrip())
        for i, m in enumerate(marks)
    ]


def slice_plan(text, number):
    found = plan_format.sections(text)
    if not found:
        die("the plan has no `## ` sections — it is not in the plan format")

    carried = [text[start:end].rstrip() for name, start, end in found
               if name.lower().rstrip(":") not in DROP]

    steps_span = plan_format.section_span(text, "Steps", found)
    if steps_span is None:
        die("the plan has no `## Steps` section")
    steps_body = text[steps_span[0]:steps_span[1]].rstrip()
    numbered = steps(steps_body)
    if not numbered:
        die("the `## Steps` section has no `### <N>.` headings")

    wanted = [body for n, body in numbered if n == number]
    if not wanted:
        have = ", ".join(str(n) for n, _ in numbered)
        die(f"the plan has no step {number} — it has {have}")
    if len(wanted) > 1:
        die(f"the plan has {len(wanted)} steps numbered {number}")
    if not plan_format.STEP.sub("", wanted[0]).strip():
        die(f"step {number} has a heading and no body")

    # Whatever stands above the first section — the plan's title. `Status:` is the
    # run's own bookkeeping and means nothing to a subagent.
    lead = plan_format.header_block(text, found)
    lead = "\n".join(line for line in lead.splitlines()
                     if not line.lower().startswith("status:")).strip()

    parts = [p for p in (lead, *carried) if p.strip()]
    parts.append("## Your step\n\n" + wanted[0])
    return "\n\n".join(parts) + "\n", len(numbered)


def main():
    parser = argparse.ArgumentParser(prog="plan-slice.py", description=__doc__)
    parser.add_argument("--plan", required=True, help="absolute path to the plan file")
    parser.add_argument("--step", required=True, type=int, help="the step number to cut")
    parser.add_argument("--out-dir", help="where to write the slice (default: .slices/ next to the plan)")
    args = parser.parse_args()

    plan = Path(args.plan).expanduser()
    if not plan.is_file():
        die(f"no plan file at {plan}")
    plan = plan.resolve()

    body, total = slice_plan(plan.read_text(encoding="utf-8"), args.step)

    out_dir = Path(args.out_dir).expanduser() if args.out_dir else plan.parent / ".slices"
    out_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(str(plan).encode("utf-8")).hexdigest()[:8]
    # Same name every time for a given plan and step: a re-slice after the plan was
    # amended replaces the stale copy instead of leaving two.
    destination = out_dir / f"{plan.stem}-{digest}-step{args.step}.md"
    destination.write_text(
        HEADER.format(step=args.step, total=total, plan=plan) + "\n" + body,
        encoding="utf-8",
    )
    print(destination)


if __name__ == "__main__":
    main()

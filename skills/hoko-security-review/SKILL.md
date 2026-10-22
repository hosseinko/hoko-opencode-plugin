---
name: hoko-security-review
description: >-
  Review code against the security guide on demand — a diff, a path, or the working tree —
  without running a full code review. Use when asked to check or audit something for security,
  to look for vulnerabilities, injection, auth or authorization holes, leaked secrets or unsafe
  handling of untrusted input, or before shipping a change that touches any of those.
---

# Security review

Target: the diff command, path or working tree the user asked about.

If that is empty, review the working tree — `git diff HEAD` — and say that is what you
reviewed. If the target is ambiguous, ask once and stop; do not audit something adjacent.

This is the front door to `hoko-code-review`'s security guide, nothing more. The standards
live in
[`reference/security-review-guide.md`](../hoko-code-review/reference/security-review-guide.md),
the single source of truth, not in this file. Its sections set the scope and carry the
house checks; standard practice applies inside each section too, and a house check is
never skipped. Read it before reporting anything.

## Which way to run it

| Target | How |
| --- | --- |
| A diff, or a handful of files | Review it here, in this context |
| A module, a directory, a whole codebase | Delegate to the `hoko-security-auditor` subagent |

The line is roughly a few hundred lines of diff, or more files than you would read
attentively in one sitting. Reading a whole module here spends the context the subagent
exists to protect, so delegate.

Its prompt must be self-contained, because it starts with an empty context:

> Audit this for security: `<the path or diff command, in full>`
>
> Follow your protocol: scope from the triggers, read the security guide, work only the
> sections that apply, verify every finding against a line you read, file the report under
> `.ai/security/`, and report the path plus the blocking findings.

When it returns, report its verdict and the path in a couple of lines. Do not paste the
report back — it is a file for a reason.

## Scope it before you read

The triggers are in `hoko-code-review`, under **When the security guide is mandatory**:
authentication and sessions, authorization, untrusted input reaching a query or a path or
a shell or a deserialiser, secrets and configuration, sensitive data in logs and error
responses, and dependency changes in any of those paths.

Work only the guide's sections that the target actually matches. A full OWASP sweep over a
diff that touches one repository class is noise, and noise is how a security report stops
being read.

A target matching no trigger at all is a real answer: say so in one line and stop, with
no manufactured findings.

## Reporting

Findings carry the `hoko-code-review` severity labels — 🔴 `[blocking]`, 🟡 `[important]`,
🟢 `[nit]` — and each one names:

- the file and line
- what an attacker does with it, concretely — not the category name
- the fix, or the question that decides it

Every finding must trace to a line you read. A pattern the guide warns about that you did
not find in this code does not go in the report; suspicion that a call might be unsafe
goes in as a question, never as a 🔴.

What you did not check is part of the answer. Say which sections of the guide you
worked, and which parts of the target you did not read. A review that reads as complete
when it sampled is worse than one that admits its edges.

Do not fix what you find in the same breath: report, let the user decide, and fix in a
separate, reviewable change.

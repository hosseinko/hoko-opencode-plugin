---
name: hoko-code-review
description: >-
  Comprehensive code review guidance for React, Vue, Rust, TypeScript, Java, PHP, Python, Go and C/C++.
  Use when reviewing a pull request or a diff, conducting a code review, establishing review standards,
  auditing security, or looking for bugs in a change.
---


# Code Review Excellence

> Gate failures are review findings. Lint errors, a suppression entry or inline
> ignore comment added to buy a green analyser run, and coverage below the configured
> floor are all findings — see `hoko-quality-assurance`.
>
> PHP projects have two further skills that carry stack-specific conventions:
> invoke `hoko-senior-php-developer` (comments, typed object-in/object-out signatures,
> PSR naming, element-typed collections, mirrored test tree, tests that actually assert)
> and, for anything touching an HTTP endpoint, `hoko-api-developer` (JSON Schema under
> `res/schema/json/<project>/` with `$ref`'d components, `swagger.yml`, versioned and
> path-grouped named routes with middleware on the group).
>
> TypeScript/React projects have `hoko-senior-frontend-developer` (feature-first
> structure with unidirectional imports, an API layer split into schemas / endpoints /
> queries, composition over prop flags, server state left in the query cache, a test for
> every unit with a branch).
>
> Go projects have `hoko-senior-go-developer` (Go idioms, error handling, concurrency
> safety, and the version-gated workflow).
>
> All are opt-in by language: ignore the PHP ones on a diff that is not PHP, the
> frontend one on a diff that is not frontend, and the Go one on a diff that is not Go.

## Review Scope

**What to Review:**
- Logic correctness and edge cases
- Security vulnerabilities
- Performance implications
- Test coverage and quality
- Error handling
- Documentation and comments
- API design and naming
- Architectural fit

**What Not to Review Manually:**
- Code formatting (use Prettier, Black, etc.)
- Import organization
- Linting violations
- Simple typos

## The final review of a plan run

The phases and techniques below are written for a hand-run review of a human PR, and
stay as they are for that use. `hoko-final-reviewer`'s single end-of-run pass over a whole
plan run is judged differently:

- Judge the diff against the plan's Requirements and Decisions, not a PR description —
  a Decision the plan closed is correct even where you would have chosen differently.
- Look across step boundaries, not one file or one step at a time: an interaction
  between two steps that neither step's own diff shows on its own is exactly what this
  pass exists to catch.
- No time boxes.
- Skip "ask to split", "offer to pair" and praise. State each problem directly rather
  than asking a question.
- Every finding needs a scenario: the concrete input or state that triggers it and the
  wrong result it leads to. Drop a finding you cannot state one for.

## Review Process

### Phase 1: Context Gathering

Before diving into code, understand:
1. Read PR description and linked issue
2. Check PR size (>400 lines? Ask to split)
3. Review CI/CD status (tests passing?)
4. Understand the business requirement
5. Note any relevant architectural decisions

> For large diffs, pipe the diff through the plugin's analyzer (`git diff main...HEAD | python3 "${HOKO_ROOT}/skills/hoko-code-review/scripts/pr-analyzer.py"`) to triage complexity and get a suggested review approach before reading.

### Phase 2: High-Level Review

1. **Architecture & Design** - Does the solution fit the problem?
   - For significant changes, consult [Architecture Review Guide](reference/architecture-review-guide.md)
   - **Data modeling**: flag public methods returning bare/associative arrays where a typed model, value object, or DTO should represent domain data (default: models over arrays). Boundary/serialized/domain data → a model; transient internal projections may stay *typed* arrays. PHP specifics in the [PHP Guide](reference/php.md#data-modeling). For a new or reshaped domain type, apply the four-dimension check in [Type Design Review](reference/architecture-review-guide.md#type-design-review).
2. **Performance Assessment** - Are there performance concerns?
   - For performance-critical code, consult [Performance Review Guide](reference/performance-review-guide.md)
   - Check: Algorithm complexity, N+1 queries, memory usage
3. **Security Surface** - Does the diff touch any of the triggers below?
   - If it does, read [Security Review Guide](reference/security-review-guide.md) before Phase 3
   - Work the sections that apply, not the whole guide
4. **File Organization** - Are new files in the right places?
5. **Testing Strategy** - Are there tests covering edge cases? Do they assert behavior rather than implementation details (e.g. pinned SQL strings, mock call order, private structure) that would still pass after a rewrite that broke the behavior?

#### When the security guide is mandatory

Not a judgement call: read [Security Review Guide](reference/security-review-guide.md)
and review against it whenever the diff touches any of:

- **Authentication or sessions** - login, logout, password handling, tokens, JWT, cookies, MFA, password reset
- **Authorization** - permission or role checks, ownership checks, an id taken from the request and used to fetch a record
- **Untrusted input** - an HTTP request body, query string, path parameter, header, webhook payload, uploaded file, or a supplier/third-party feed reaching a query, a filesystem path, a shell command, a deserialiser or a template
- **CSRF** - a state-changing endpoint authenticated by something the browser attaches automatically, such as a session cookie or HTTP basic auth
- **Secrets and configuration** - `.env`, credentials, API keys, connection strings, crypto parameters, TLS or CORS settings
- **Sensitive data** - PII, payment data, anything that lands in a log line or an error response
- **Dependencies** - a new third-party package, or a version bump of one in any of the above paths

That analyzer flags most of these from the filenames alone (`.env`, `auth`,
`security`, `password`, `token`, `secret`); a hit there means the guide is in scope, a
miss does not mean it is not — the triggers above are by behaviour, not by filename.

A diff matching none of them gets the one-line security check in Phase 3 and nothing
more. Say which applied, or that none did, so the decision is visible rather than
silent.

To run this dimension on its own — outside a review, against a diff, a path or the
working tree — use `hoko-security-review`. It reads the same guide; a target larger than
a diff goes to the `hoko-security-auditor` subagent.

### Phase 3: Line-by-Line Review

For each file, check:
- **Logic & Correctness** - Edge cases, off-by-one, null checks, race conditions
- **Silent failures** - Swallowed errors, `.catch(() => [])`, defaults hiding a failed lookup, log-and-forget, missing timeouts or rollback. See [Silent Failures](reference/common-bugs-checklist.md#silent-failures)
- **Security** - Input validation, injection risks, XSS, sensitive data
- **Performance** - N+1 queries, unnecessary loops, memory leaks
- **Maintainability** - Clear names, single responsibility, comments

### Phase 4: Summary & Decision

1. Summarize key concerns
2. Highlight what you liked
3. Make clear decision:
   - ✅ Approve
   - 💬 Comment (minor suggestions)
   - 🔄 Request Changes (must address)
4. Offer to pair if complex

## Review Techniques

### Technique 1: The Checklist Method

Use checklists for consistent reviews. See [Security Review Guide](reference/security-review-guide.md) and work the sections that apply.

### Technique 2: State the Defect and Its Trigger

A finding names the problem, the input or state that triggers it, and the wrong result.
A question is for something you could not settle from the code, and is labelled as one.
When the comment goes to a human author on a PR, phrase it collaboratively, but the
defect and its trigger stay explicit rather than implied by a question.

### Technique 3: Differentiate Severity

Use labels to indicate priority:

- 🔴 `[blocking]` - Must fix before merge
- 🟡 `[important]` - Should fix, discuss if disagree
- 🟢 `[nit]` - Nice to have, not blocking
- 💡 `[suggestion]` - Alternative approach to consider
- 📚 `[learning]` - Educational comment, no action needed
- 🎉 `[praise]` - Good work, keep it up!

## Language-Specific Guides

Refer to the corresponding detailed guide based on the language of the code being reviewed:

| Language/Framework | Reference File | Key Topics |
|-------------------|----------------|------------|
| **React** | [React Guide](reference/react.md) | Hooks, useEffect, React 19 Actions, RSC, Suspense, TanStack Query v5 |
| **Rust** | [Rust Guide](reference/rust.md) | Ownership/borrowing, unsafe review, async code, error handling |
| **Go** | [Go Guide](reference/go.md) | Error handling, goroutines/channels, context, interface design |
| **PHP** | [PHP Guide](reference/php.md) | Data Modeling |
| **CSS/Less/Sass** | [CSS Guide](reference/css-less-sass.md) | Variable conventions, !important, performance optimization, responsive design, compatibility |

## House References

- **PHP** → [PHP Guide](reference/php.md), plus `hoko-senior-php-developer` and `hoko-api-developer` above
- **Type design** → [Type Design Review](reference/architecture-review-guide.md#type-design-review)
- **Silent failures** → [Silent Failures](reference/common-bugs-checklist.md#silent-failures)
- **Security** → [Security Review Guide](reference/security-review-guide.md)

## Additional Resources

- [Architecture Review Guide](reference/architecture-review-guide.md) - Architecture design review guide (SOLID, anti-patterns, coupling)
- [Performance Review Guide](reference/performance-review-guide.md) - Performance review guide (Web Vitals, N+1, complexity)
- [Common Bugs Checklist](reference/common-bugs-checklist.md) - Common bugs checklist by language
- [PR Review Template](assets/pr-review-template.md) - PR review comment template
- [Review Checklist](assets/review-checklist.md) - Quick reference checklist

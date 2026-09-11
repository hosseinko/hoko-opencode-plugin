---
name: hoko-code-review
description: >-
  Comprehensive code review guidance for React, Vue, Rust, TypeScript, Java, PHP, Python, Go and C/C++.
  Use when reviewing a pull request or a diff, conducting a code review, establishing review standards,
  auditing security, or looking for bugs in a change.
---


# Code Review Excellence

> **Gate failures are review findings.** Lint errors, a suppression entry or inline
> ignore comment added to buy a green analyser run, and coverage below the configured
> floor are all findings — see `hoko-quality-assurance`.
>
> **PHP projects** have two further skills that carry stack-specific conventions:
> invoke `hoko-senior-php-developer` (comments, typed object-in/object-out signatures,
> PSR naming, element-typed collections, mirrored test tree, tests that actually assert)
> and, for anything touching an HTTP endpoint, `hoko-api-developer` (JSON Schema under
> `res/schema/json/<project>/` with `$ref`'d components, `swagger.yml`, versioned and
> path-grouped named routes with middleware on the group). Both are opt-in by language:
> ignore them on a diff that is not PHP.
>
> **TypeScript/React projects** have `hoko-senior-frontend-developer` (feature-first
> structure with one-way imports, the `schemas` / `endpoints` / `queries` API layer,
> composition over boolean prop flags, server state left in the query cache, and the
> list of hacks that are never the fix). Same deal: ignore it on a diff that is not
> frontend.

Transform code reviews from gatekeeping to knowledge sharing through constructive feedback, systematic analysis, and collaborative improvement.

## When to Use This Skill

- Reviewing pull requests and code changes
- Establishing code review standards for teams
- Mentoring junior developers through reviews
- Conducting architecture reviews
- Creating review checklists and guidelines
- Improving team collaboration
- Reducing code review cycle time
- Maintaining code quality standards

## Core Principles

### 1. The Review Mindset

**Goals of Code Review:**
- Catch bugs and edge cases
- Ensure code maintainability
- Share knowledge across team
- Enforce coding standards
- Improve design and architecture
- Build team culture

**Not the Goals:**
- Show off knowledge
- Nitpick formatting (use linters)
- Block progress unnecessarily
- Rewrite to your preference

### 2. Effective Feedback

**Good Feedback is:**
- Specific and actionable
- Educational, not judgmental
- Focused on the code, not the person
- Balanced (praise good work too)
- Prioritized (critical vs nice-to-have)

```markdown
❌ Bad: "This is wrong."
✅ Good: "This could cause a race condition when multiple users
         access simultaneously. Consider using a mutex here."

❌ Bad: "Why didn't you use X pattern?"
✅ Good: "Have you considered the Repository pattern? It would
         make this easier to test. Here's an example: [link]"

❌ Bad: "Rename this variable."
✅ Good: "[nit] Consider `userCount` instead of `uc` for
         clarity. Not blocking if you prefer to keep it."
```

### 3. Review Scope

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

## Review Process

### Phase 1: Context Gathering (2-3 minutes)

Before diving into code, understand:
1. Read PR description and linked issue
2. Check PR size (>400 lines? Ask to split)
3. Review CI/CD status (tests passing?)
4. Understand the business requirement
5. Note any relevant architectural decisions

> For large diffs, pipe the diff through [`scripts/pr-analyzer.py`](scripts/pr-analyzer.py) (`git diff main...HEAD | python scripts/pr-analyzer.py`) to triage complexity and get a suggested review approach before reading.

### Phase 2: High-Level Review (5-10 minutes)

1. **Architecture & Design** - Does the solution fit the problem?
   - For significant changes, consult [Architecture Review Guide](reference/architecture-review-guide.md)
   - Check: SOLID principles, coupling/cohesion, anti-patterns
   - **Data modeling**: flag public methods returning bare/associative arrays where a typed **model, value object, or DTO** should represent domain data (default: models over arrays). Boundary/serialized/domain data → a model; transient internal projections may stay *typed* arrays. PHP specifics in the [PHP Guide](reference/php.md#data-modeling).
2. **Performance Assessment** - Are there performance concerns?
   - For performance-critical code, consult [Performance Review Guide](reference/performance-review-guide.md)
   - Check: Algorithm complexity, N+1 queries, memory usage
3. **File Organization** - Are new files in the right places?
4. **Testing Strategy** - Are there tests covering edge cases?

### Phase 3: Line-by-Line Review (10-20 minutes)

For each file, check:
- **Logic & Correctness** - Edge cases, off-by-one, null checks, race conditions
- **Security** - Input validation, injection risks, XSS, sensitive data
- **Performance** - N+1 queries, unnecessary loops, memory leaks
- **Maintainability** - Clear names, single responsibility, comments

### Phase 4: Summary & Decision (2-3 minutes)

1. Summarize key concerns
2. Highlight what you liked
3. Make clear decision:
   - ✅ Approve
   - 💬 Comment (minor suggestions)
   - 🔄 Request Changes (must address)
4. Offer to pair if complex

## Review Techniques

### Technique 1: The Checklist Method

Use checklists for consistent reviews. See [Security Review Guide](reference/security-review-guide.md) for comprehensive security checklist.

### Technique 2: The Question Approach

Instead of stating problems, ask questions:

```markdown
❌ "This will fail if the list is empty."
✅ "What happens if `items` is an empty array?"

❌ "You need error handling here."
✅ "How should this behave if the API call fails?"
```

### Technique 3: Suggest, Don't Command

Use collaborative language:

```markdown
❌ "You must change this to use async/await"
✅ "Suggestion: async/await might make this more readable. What do you think?"

❌ "Extract this into a function"
✅ "This logic appears in 3 places. Would it make sense to extract it?"
```

### Technique 4: Differentiate Severity

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

## Additional Resources

- [Architecture Review Guide](reference/architecture-review-guide.md) - Architecture design review guide (SOLID, anti-patterns, coupling)
- [Performance Review Guide](reference/performance-review-guide.md) - Performance review guide (Web Vitals, N+1, complexity)
- [Common Bugs Checklist](reference/common-bugs-checklist.md) - Common bugs checklist by language
- [Security Review Guide](reference/security-review-guide.md) - Security review guide
- [PR Review Template](assets/pr-review-template.md) - PR review comment template
- [Review Checklist](assets/review-checklist.md) - Quick reference checklist

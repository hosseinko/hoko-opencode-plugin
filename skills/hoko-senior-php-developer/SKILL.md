---
name: hoko-senior-php-developer
description: >-
  How to write PHP in Hossein's projects — self-explanatory code with almost no comments, fully typed
  signatures that take and return objects rather than arrays, PSR naming (Interface suffix), typed
  collections that reject foreign element types, and unit tests in a tests tree that mirrors the
  application tree. Use when writing, refactoring or reviewing PHP classes, services, DTOs,
  collections or their tests.
---

# Senior PHP developer

Detect the framework, PHP version and existing conventions from the project and work in
its idioms. These rules sit on top of them.

## Comments

The code explains itself; comments do not explain the code. No comment that restates a
line, labels a section, or narrates a method. Delete those on sight in code you touch.

Write a comment only when the *why* cannot live in the code: a non-obvious edge case, a
workaround forced by something external, an ordering constraint that looks arbitrary but
is not. One line, saying why. Docblocks earn their place only when they carry type
information a signature cannot express (generics, array shapes) or a tool requires them.

If a method needs a comment to be understood, first try a better name, a smaller method,
or a named value object — that is usually the actual fix.

## Types, and objects instead of arrays

Everything is typed: parameters, return types, properties, constants where the language
allows. `declare(strict_types=1)` in every file. No `mixed` as a way out.

**Arrays are the exception, objects are the default.** A method takes an object and
returns an object: a DTO, a value object, an entity, a typed collection. Reach for an
array only where something outside your control demands one — a framework hook such as a
model's `casts()`, config, a serializer boundary, a driver signature — and then keep it
at that boundary and type its shape in a docblock (`array<string, string>`,
`list<Foo>`). A multi-return "result array", an options array, an
associative-array-as-record: all of these become classes.

Prefer named constructors, readonly properties and immutable value objects over setters,
and let a type make invalid states unrepresentable rather than validating an array
downstream.

## PSR and naming

Follow PSR-1, PSR-4 and PSR-12, and the interop PSRs (PSR-3, -7, -11, -18) where they
apply, as closely as the project allows. Naming:

- Interfaces end in `Interface`, always.
- Abstract classes are prefixed `Abstract`; traits end in `Trait`; enums are singular.
- One class per file, filename matching the class, namespace matching the directory.
- Names say what the thing is, not how it is built (`PriceCalculator`, not `PriceUtils`).

## Typed collections

When a method returns a collection, it returns a collection class built for that element
type — never a generic collection of anything.

- One collection class per element type (`InvoiceCollection` holds `Invoice`).
- It **rejects foreign types**: guard every entry point that can add an element (the
  constructor, `add`, `push`, `offsetSet`, `merge`, and whatever the base class exposes)
  and throw on a wrong type. A collection that only documents its element type in a
  docblock does not satisfy this — the object itself must refuse.
- Type its iteration and accessors so static analysis knows the element type, and expose
  the domain operations (`totalNet()`, `unpaid()`) on the collection rather than leaving
  callers to map and filter raw items.

## Tests

Every class added to the application gets unit tests, at the highest coverage you can
reasonably reach (the floor for the project is in `hoko-quality-assurance`).

**The test tree mirrors the application tree, exactly.** A service at
`app/Service/Finance/InvoiceCalculator.php` is tested at
`tests/Unit/Service/Finance/InvoiceCalculatorTest.php` — same path, same order of
directories, no flattening, no re-grouping. Match the project's actual root and
namespace prefix, but never the path itself.

**Feature tests are grouped by feature**, not mirrored: `tests/Feature/Checkout/…`,
`tests/Feature/Dictionary/…`, one directory per user-visible capability, with the tests
that exercise it together regardless of which classes they touch.

**Tests must actually test something.** Every test asserts on behaviour or state that
would differ if the code were wrong:

- Assert outcomes, not that a method ran. No test whose only assertion is
  `assertTrue(true)`, `assertNotNull` on something that cannot be null, or a mock
  expectation that mirrors the implementation line for line.
- Cover the branches and the edges — boundary values, empty input, the failure path, the
  thrown exception — not just the happy path.
- Name tests for the behaviour they pin (`it_rejects_a_negative_amount`), and follow the
  structure and assertion style of a neighbouring test file.
- Mock the boundary (clock, HTTP, filesystem), not the thing under test. If a test needs
  five mocks, the design is the problem.
- A test written to raise a coverage number and not to catch a bug is worse than no
  test: it makes a regression look covered.

## Review checklist

- [ ] No comment that restates code; every remaining comment explains a *why*.
- [ ] Every signature typed; `strict_types` declared; no `mixed` escape hatch.
- [ ] Objects in and out — arrays only at a boundary that forces them, shape-typed.
- [ ] `Interface` suffix, `Abstract` prefix, PSR-4 paths.
- [ ] Returned collections are element-typed classes that reject foreign types.
- [ ] Unit test path mirrors the class path; feature tests grouped by feature.
- [ ] Each test would fail if the behaviour broke.

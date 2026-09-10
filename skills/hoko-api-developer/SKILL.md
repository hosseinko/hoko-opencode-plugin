---
name: hoko-api-developer
description: >-
  API design rules for PHP projects — a JSON Schema per JSON payload under res/schema/json/<project>/
  with shared components reused by $ref, a swagger.yml at the project root that references them, and
  routes that are versioned, grouped by shared path, named, and carry middleware on the group.
  Use when adding, changing or reviewing an HTTP API endpoint, a request payload, a route file, or the
  OpenAPI/Swagger definition.
---

# API developer

These rules are not optional and not proportional to the size of the change. A new
endpoint that ships without its schema, its swagger entry, its version group and its
route name is unfinished, not "to be tidied later".

Detect the framework and router from the project (`composer.json`, the route files,
existing endpoints) and express these rules in that project's idioms. Match the
conventions already in the repo where they do not contradict what follows.

## 1. A JSON Schema for every JSON payload

Every endpoint that accepts a JSON body has a JSON Schema file. Responses get one too
when they are part of the contract (a documented payload, something a consumer parses).

Location — `res/schema/json/<project>/` at the project root, where `<project>` is the
project's own name (the package part of `composer.json`'s `name`, or the repository
directory when that is absent):

```
res/schema/json/
└── <project>/
    ├── components/
    │   ├── address.json
    │   ├── money.json
    │   ├── pagination.json
    │   └── error.json
    └── v1/
        └── dictionary/
            ├── create-entry.request.json
            └── entry.response.json
```

Rules:

- **Reuse, never restate.** A shape that appears in two schemas becomes one file under
  `components/` and is pulled in with `$ref`. Before writing a new object, grep
  `components/` for it. Copy-pasting a property block between two schema files is the
  failure this rule exists to prevent.
- One schema per payload, named `<action>.request.json` / `<resource>.response.json`,
  mirroring the route's version and path segments as directories.
- Declare `$schema`, `$id`, `type`, `required`, and `additionalProperties: false`.
  Constrain values — formats, enums, min/max, patterns — rather than leaving bare
  `"type": "string"` everywhere.
- The schema is the source of truth for validation. Wire the project's validation layer
  to it, or keep the validator and the schema provably in step; two independent
  definitions of the same payload is one too many.

## 2. swagger.yml at the project root

A single `swagger.yml` lives at the project root and describes every exposed endpoint.

- It does not inline payload shapes: it `$ref`s the files under
  `res/schema/json/<project>/`, so a shape is defined once and consumed by both.
- Every path carries its method, summary, parameters, request body, response codes
  (including the error responses, via the shared error component) and the security
  scheme it requires.
- Paths in `swagger.yml` are the real, versioned, grouped paths — no aliases, no
  aspirational endpoints.
- Changing an endpoint means changing `swagger.yml` in the same commit. Validate it
  before committing (any OpenAPI validator the project has; otherwise at minimum parse
  the YAML and resolve every `$ref`).

## 3. Versioned routes

All routes live under a version group, starting at `v1` — no unversioned endpoint,
ever, not even for internal or debug use.

- A breaking change opens `v2`; it never mutates a shipped `v1` shape.
- The version is the outermost group, with everything else nested inside it.

## 4. Group by shared path, and put the middleware on the group

Inside a version, routes sharing a path prefix are one group: everything under
`/dictionary/` is a `dictionary` group, nested further where the paths nest deeper.

- **Configure the group, not the route.** Middleware, prefix, name prefix, controller,
  and auth belong on the group. Repeating the same middleware on five sibling routes is
  the smell this rule targets — if you are writing the same modifier twice, it belongs
  one level up.
- A middleware that genuinely applies to a single route stays on that route; that is the
  exception, and it should be visibly the exception.

## 5. Every route has a name

No anonymous routes. Names derive from the group hierarchy, so they read as a path —
`v1.dictionary.entries.store` — and come from group name prefixes rather than being
spelled out per route. Reference routes by name in code, tests and redirects, never by
literal URL string.

## Definition of done

Before you call an endpoint finished:

- [ ] Request payload has a schema under `res/schema/json/<project>/`, reusing
      `components/` via `$ref` for every shape that is not unique to it.
- [ ] Response payload has a schema when it is part of the contract.
- [ ] `swagger.yml` describes the endpoint and `$ref`s those schemas; it parses and every
      `$ref` resolves.
- [ ] The route sits inside a version group (`v1` or later) and inside a path group.
- [ ] Middleware, prefix and name prefix are set on the group, not repeated per route.
- [ ] The route has a name, and the code refers to it by that name.

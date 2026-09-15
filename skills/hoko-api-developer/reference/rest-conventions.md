# REST conventions

Stack-agnostic rules for the shape of an endpoint: its URL, its method, its status
codes, its payload envelope, and how it grows. The layout rules in the main skill say
*where the schema and the route live*; this file says *what the contract looks like*.

Where the project already has a house style that contradicts a rule here, the project
wins — consistency across endpoints beats correctness on one. Say so explicitly in the
review rather than silently following the older pattern.

## URLs

Resources are plural nouns, lowercase, kebab-case. The verb is the HTTP method.

```
GET    /v1/team-members
GET    /v1/team-members/{id}
POST   /v1/team-members
PATCH  /v1/team-members/{id}
DELETE /v1/team-members/{id}

GET    /v1/team-members/{id}/assignments   # sub-resource, expresses ownership
POST   /v1/orders/{id}/cancel              # a verb only where no resource fits
```

Wrong: `/v1/getUsers`, `/v1/user`, `/v1/team_members`, `/v1/users/{id}/getOrders`.

Nest a sub-resource only when it cannot exist without its parent. Two levels is the
practical limit; deeper, promote it to a top-level resource with a filter.

## Methods

| Method | Idempotent | Safe | Use for |
|--------|-----------|------|---------|
| GET | yes | yes | reads only — never a side effect, never a state change |
| POST | no | no | create, or an action that maps to no resource |
| PUT | yes | no | full replacement |
| PATCH | no | no | partial update |
| DELETE | yes | no | removal — a second call returns 404 or 204, not an error |

A GET that mutates is a bug, not a shortcut: it will be prefetched, cached and retried.

## Status codes

```
200 OK                    GET, PATCH, PUT with a body
201 Created               POST — include a Location header pointing at the new resource
202 Accepted              work queued, not yet done
204 No Content            DELETE, or a write with nothing to return

400 Bad Request           malformed body, unparseable JSON, bad query parameter
401 Unauthorized          missing or invalid credentials
403 Forbidden             authenticated, but not allowed
404 Not Found             no such resource — also the correct answer when revealing
                          existence would itself leak information
409 Conflict              duplicate, or a state transition that is not legal now
410 Gone                  removed permanently, e.g. a sunset API version
422 Unprocessable Entity  valid syntax, invalid data — schema validation failures
429 Too Many Requests     rate limited — include Retry-After

500 Internal Server Error unexpected; never leaks a trace, a query or a class name
502 / 503                 upstream failed / temporarily overloaded, with Retry-After
```

The failure mode to watch for in review is `200` with a `"success": false` body. The
status code is part of the contract; clients, proxies and monitoring all read it.

## Payload envelope

Pick one envelope per project and hold it. The common choice:

```json
{
  "data": { "id": "abc-123", "name": "Alice", "createdAt": "2026-01-15T10:30:00Z" }
}
```

Collections carry their paging metadata alongside:

```json
{
  "data": [ { "id": "abc-123" }, { "id": "def-456" } ],
  "meta": { "total": 142, "page": 1, "perPage": 20, "totalPages": 8 }
}
```

Errors are a single shape, always, with a stable machine-readable `code` — clients
branch on the code, humans read the message:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Request validation failed",
    "details": [
      { "field": "email", "code": "invalid_format", "message": "Must be a valid email address" },
      { "field": "age",   "code": "out_of_range",  "message": "Must be between 0 and 150" }
    ]
  }
}
```

Field casing is a project-wide decision, not a per-endpoint one. Whichever you use,
the JSON Schema is what records it.

## Pagination

Every collection endpoint paginates. An unbounded list endpoint is a production
incident waiting for the table to grow.

**Offset** — `?page=2&perPage=20`. Use for admin screens, search results, anything where
users expect page numbers. Degrades badly at large offsets and skips or repeats rows
when the underlying set changes between pages.

**Cursor** — `?cursor=<opaque>&limit=20`, returning `meta.nextCursor` and
`meta.hasNext`. Use for feeds, infinite scroll, exports, and any set large enough that
`OFFSET` hurts. Stable under concurrent writes; cannot jump to page N.

Enforce a maximum `perPage`/`limit` server-side and document the default.

## Filtering, sorting, sparse fields

```
?status=active&customerId=abc-123      equality
?price[gte]=10&price[lte]=100          comparison
?category=electronics,clothing         multiple values
?sort=-createdAt,price                 leading '-' is descending, comma-separated
?fields=id,name,email                  sparse fieldset
?q=wireless+headphones                 full-text search
```

Filterable fields are an allow-list, not whatever reaches the query builder — an
open filter parameter is both an injection surface and an unindexed-scan surface. Every
field exposed for filtering or sorting needs an index behind it.

## Versioning

Start at `v1` and stay there until a change is genuinely breaking.

Non-breaking, no new version: adding a response field, adding an optional query
parameter, adding an endpoint, relaxing a constraint.

Breaking, needs a new version: removing or renaming a field, changing a field's type or
its meaning, tightening validation, changing the URL structure, changing auth.

Run at most two versions at once (current and previous). Deprecate with a `Sunset`
header and an announced date; return `410 Gone` after it. A silently changed `v1` is
worse than a `v2` nobody migrated to yet.

## Auth and rate limiting

- Every endpoint is authenticated unless it is deliberately public, and "deliberately
  public" is written down in the OpenAPI security section, not assumed.
- Authorisation is checked per resource, not just per route: owning the token does not
  mean owning row 4712. A 403 on someone else's resource, or a 404 where existence is
  itself sensitive.
- Public endpoints are rate limited. Return `429` with `Retry-After`, and expose
  `X-RateLimit-Limit` / `-Remaining` / `-Reset` so clients can back off before they are
  cut off. Authentication endpoints get a stricter limit than the rest.

## Endpoint review checklist

- [ ] Plural, kebab-case, verb-free URL, consistent with the endpoints beside it
- [ ] Method matches the semantics; no state change behind a GET
- [ ] Status codes used semantically — 201 + `Location` on create, 422 on validation,
      204 on empty writes, never 200-with-an-error-body
- [ ] Request validated against its schema before anything else runs
- [ ] Error responses use the project's single error shape with a stable `code`
- [ ] Collection endpoints paginate, with a server-enforced maximum page size
- [ ] Filter and sort fields are allow-listed and indexed
- [ ] Authentication required or explicitly documented as public; authorisation checked
      on the resource, not just the route
- [ ] Rate limiting configured
- [ ] No internal detail in any error path — no traces, SQL, class names or file paths
- [ ] Change is either non-breaking or lands in a new version
- [ ] OpenAPI definition updated in the same commit

---
name: hoko-senior-frontend-developer
description: >-
  Frontend conventions for TypeScript/React projects — feature-first structure with unidirectional
  imports, an API layer split into schemas / endpoints / queries so every call has one obvious home,
  components built by composition rather than prop flags, server state kept in the query cache instead
  of a store, a test for every unit that has a branch, and a named list of hacks that are never the
  fix. Use when writing, refactoring or
  reviewing frontend code: components, hooks, an API client, data fetching, or their tests.
---

# Senior frontend developer

The rules below are stack-neutral in intent and written against React + TypeScript,
which is where the examples come from. On Vue, Svelte or Angular, keep the structure
and the API-layer rules exactly and translate the component rules into that framework's
idioms — a composable is a hook, an SFC is a component file.

## 0. Read the project before writing in it

Before the first line: the package manifest (framework and major version, data-fetching
library, validation library, router, styling approach), the existing folder layout, and
two or three files near the change. Work in the project's idioms and match its
conventions wherever they do not contradict what follows. Never introduce a second way
of doing something the project already does one way — a second HTTP client, a second
state library, a second styling system. If a rule below needs a dependency the project
does not have, follow the rule's *shape* with what is there rather than adding the
dependency unasked.

## 1. Structure: features, and one direction

```
src/
├── app/          composition root — routes, providers, router, layout shell
├── components/   shared UI, owned by no feature
├── features/     one folder per user-visible capability
├── hooks/        shared hooks
├── lib/          configured third-party clients (http, queryClient, i18n)
├── types/        shared types
└── utils/        shared pure helpers
```

A feature holds everything that belongs to it and nothing that does not:

```
src/features/hotels/
├── api/          schemas, endpoints, queries — see section 2
├── components/   components only this feature uses
├── hooks/        feature hooks
├── types/        feature types not derived from a schema
└── index.ts      the feature's public surface
```

Three rules make this hold:

- **Imports flow one way: `shared → features → app`.** Shared code (`components/`,
  `hooks/`, `lib/`, `utils/`, `types/`) never imports from `features/` or `app/`, and a
  feature never imports from `app/`.
- **Features do not import each other.** If two features need the same thing, it moves
  up into shared; if one needs to render the other, they are composed in `app/`. A
  cross-feature import is the moment a codebase starts to rot, so enforce it in the
  linter (`import/no-restricted-paths` zones) rather than in review.
- **A feature is entered through its `index.ts`.** Deep imports into another feature's
  internals are not allowed; what is not exported there is private, and that is the
  point.

Promote to shared on the *second* real use, not the first anticipated one. A component
that lives in one feature and is exported "in case" is a shared component with extra
steps.

## 2. The API layer

The goal is navigational: given an endpoint, a URL, or a screen, there is exactly one
file it can be in, and its name says so. This is reached by splitting the layer by
*role*, not by wrapping it in classes — no `ApiService`, no repository hierarchy, no
base class. Plain modules, plain functions, one job each.

Per resource, three files plus a barrel:

```
src/features/hotels/api/
├── hotel.schemas.ts     what the wire looks like, and what we turn it into
├── hotel.endpoints.ts   one function per endpoint, no framework, no cache
├── hotel.queries.ts     queryOptions + mutation hooks built on those functions
└── index.ts
```

**`lib/http.ts` — one client, once.** Base URL, auth header, error normalisation,
timeout, JSON handling live there and nowhere else. It throws a typed error (status +
code + message); every endpoint inherits that behaviour and no endpoint re-implements
it. `fetch` is never called from a component, a hook, or an endpoint file's body beyond
this client.

**`*.schemas.ts` — the boundary is validated.** Every response the app parses gets a
schema, and the schema is where the wire shape stops. Server types are *derived* from
schemas (`z.infer`), never hand-written in parallel; a hand-maintained interface next to
a schema is two definitions of one thing. Where the API's naming differs from the app's,
the schema transforms once, here, and the rest of the codebase only ever sees the app's
shape. A shape used by two resources becomes its own schema module and is imported —
copy-pasting a field block between schema files is the failure this rule prevents.

**`*.endpoints.ts` — one exported function per endpoint, and nothing else.** No caching,
no React, no state, no side effects beyond the call.

```ts
export const listHotels = async (params: ListHotelsParams): Promise<Hotel[]> =>
  hotelListSchema.parse(await http.get('/v1/hotels', { params }))

export const getHotel = async (id: HotelId): Promise<Hotel> =>
  hotelSchema.parse(await http.get(`/v1/hotels/${id}`))

export const createHotel = async (input: CreateHotelInput): Promise<Hotel> =>
  hotelSchema.parse(await http.post('/v1/hotels', createHotelInputSchema.parse(input)))
```

- Name for the operation, not the verb of the transport: `listHotels`, `getHotel`,
  `createHotel`, `archiveHotel`. Grepping `/v1/hotels` lands on every call site of that
  path, and there is one.
- Parameters are a typed object, never a positional sprawl and never `any`.
- The URL is built here and only here. No endpoint path string exists anywhere else in
  the app.

**`*.queries.ts` — cache policy, and the hooks components use.** Query keys come from one
factory per resource so no key is ever spelled out twice, and each query is a
`queryOptions` object so the same definition serves `useQuery`, `prefetchQuery` and
`useSuspenseQuery`.

```ts
export const hotelKeys = {
  all: ['hotels'] as const,
  list: (params: ListHotelsParams) => [...hotelKeys.all, 'list', params] as const,
  detail: (id: HotelId) => [...hotelKeys.all, 'detail', id] as const,
}

export const hotelListQuery = (params: ListHotelsParams) =>
  queryOptions({ queryKey: hotelKeys.list(params), queryFn: () => listHotels(params) })

export const useCreateHotel = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: createHotel,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: hotelKeys.all }),
  })
}
```

- Every mutation states what it invalidates. A mutation that leaves the cache stale is
  unfinished.
- `staleTime`, `retry` and `select` are decided here, per resource, not sprinkled at call
  sites.
- Components import from `features/<feature>/api` — never from `*.endpoints.ts`
  directly. A component calling an endpoint function by hand has stepped around the
  cache, and that is how two screens end up disagreeing about the same record.

When a resource grows past roughly a dozen endpoints, split by sub-resource
(`hotel-rates.endpoints.ts`) rather than letting one file sprawl. That is the only
reshaping this layout invites.

## 3. Components

**Composition over configuration.** A component that has grown a set of boolean props
(`isCompact`, `withHeader`, `hideFooter`, `variantSecondaryAlt`) is one component doing
three jobs. Split it, or give it slots — children and named element props — so callers
assemble what they need instead of switching it on. Related parts that only make sense
together become a compound component (`<Table>`, `<Table.Row>`) rather than a config
object.

- One component per file, named for what it is, filename matching.
- Props are an explicit named type. No `any`, no `{...props}` spread onto a DOM element
  without a typed rest. Optional props get a sane default, not a null check at every use.
- **Presentational and connected are different components.** A component that fetches
  does not also decide how things look; a component that renders takes data through
  props and can be rendered in a test or a story with a literal. Keep the fetch at the
  top of the screen or in a thin connected wrapper.
- Server types do not travel to leaf components. A `<Badge>` takes `status`, not `Hotel`.
- A component is not reusable because it is in `components/`. It is reusable when it has
  no knowledge of where it is used — no feature imports, no route names, no global
  store reads.
- Keep files short enough to hold in your head. Long JSX with three nested ternaries is
  an extraction waiting to happen, not a formatting problem.

## 4. State: know which kind you have

Four kinds, four homes, and the common bug is putting one in another's:

- **Server state** — lives in the query cache. Never copied into a store or mirrored into
  `useState` on mount. If you are writing `useEffect(() => setItems(data), [data])`, the
  cache already had it.
- **URL state** — filters, tabs, pagination, the selected id. These belong in the URL so
  a link reproduces the screen.
- **Local UI state** — open/closed, hovered, the in-progress text. `useState`, in the
  component that owns it, as close to the use as possible.
- **Shared client state** — genuinely global and genuinely client-side (theme, session
  UI). A store, kept small.

Derived values are computed during render, not stored. `useEffect` is for synchronising
with something outside React — a subscription, a DOM API, a timer — and for nothing
else.

## 5. Styling

Follow the project's system; do not introduce a second one. Whatever it is:

- Values come from the project's tokens — colours, spacing, radii, typography, breakpoints.
  A hex code, a `px` nudge or a `z-index: 9999` typed inline is a missing token or a
  layout bug, and it is fixed as one of those.
- Variants are data, not branches: one place that maps a variant name to its classes or
  styles, not a chain of conditionals across the JSX.
- Layout belongs to the parent, not the child. A reusable component does not set its own
  margins.
- No `!important`, and no styling another component's internals from outside it.

## 6. Hacks that are never the fix

Each of these buys a green screen now and costs an afternoon later. If one feels
necessary, the design is the problem:

- `setTimeout` / `requestAnimationFrame` to wait for a render, a ref, or "the data".
- `any`, `as unknown as`, `@ts-expect-error` or a non-null `!` to silence a type the
  shape actually contradicts.
- `key={Math.random()}`, or changing a `key` to force a remount instead of resetting
  state deliberately.
- Reaching into the DOM with `document.querySelector` for something React owns.
- `!important`, escalating `z-index`, or negative margins to defeat a layout you could
  fix.
- `dangerouslySetInnerHTML` on anything that is not sanitised at the boundary.
- Copying a component "temporarily" to change two lines.
- Catching an error to make a console warning stop.
- Disabling a lint rule inline. The suppression rules in `hoko-quality-assurance` apply
  here in full.

## 7. Comments and types

Comments follow `instructions/communication.md`: the code explains itself, and a comment
exists only where the *why* cannot live in the code. No comment that restates a line or
labels a section.

Types are inferred where inference is honest and explicit where it is load-bearing —
props, exported functions, module boundaries. Model impossible states out of existence
with discriminated unions (`{ status: 'idle' } | { status: 'error', error: ApiError }`)
rather than four independent booleans.

## 8. Tests

The coverage floor and the gate order are in `hoko-quality-assurance`. What is specific
here:

### What a unit is on the frontend

There is a unit test on the frontend; the unit is just not always a class. **Every unit
you add gets a test**, and these are the units:

| Unit | Tested by |
| --- | --- |
| Pure function in `utils/` | Call it. Inputs → output, plus the edges. |
| Schema in `*.schemas.ts` | Parse a real payload fixture; assert the transform, and assert it *rejects* a malformed one. |
| Endpoint in `*.endpoints.ts` | Intercept the request: assert the URL, method and body it sends, and the parsed result it returns. |
| Hook (`use…`) | Render it in isolation with the project's hook-testing helper; assert the values and transitions it exposes, never its internals. |
| Presentational component | Render with literal props; assert what the user would see for each state it can be in. |
| Connected component / screen | Render with the network intercepted; assert the states in order — loading, then data, or empty, or error. |
| Store slice / reducer | Call the actions; assert the resulting state. |

That last row of the table is the frontend's *integration* test, and it is the one that
catches the most per line written. Write it for every screen. The units above it stop you
having to enumerate every combination inside it.

The rule has one deliberate exception: a component with no logic — no branch, no
condition, no derived value, no interaction — does not need a test that only asserts it
rendered. That test costs maintenance and catches nothing. Coverage of such components
comes from the screen test that renders them. **Anything with a branch is a unit and gets
its own test**, and that includes a one-line `formatPrice` and a three-line `useDebounce`.

### How to write them

- **Test behaviour through the public surface** — what a user sees and does. Query by
  role and accessible name, not by test id or class, and never assert on internal state,
  on a hook's render count, or on a component's private helpers.
- **Tests sit next to what they test** (`HotelCard.test.tsx` beside `HotelCard.tsx`).
  This is the frontend exception to the mirrored test tree used elsewhere; follow the
  project if it already mirrors.
- **Mock the network at the network** — a request interceptor against real URLs — not by
  stubbing the endpoint functions or the hooks. That way a schema or URL change fails a
  test instead of passing one. Stubbing `useHotels` tests the mock.
- **Cover the states the thing actually has**: loading, empty, error, populated, and the
  disabled or permission-denied variant if it has one. A component with an error branch
  and no error test is untested, whatever the coverage number says.
- **Fixtures are built, not copied.** One factory per resource (`buildHotel(overrides)`),
  so a schema change breaks in one place and each test states only the fields it cares
  about.
- Each test would fail if the behaviour broke. A test asserting a render happened, or a
  snapshot nobody reads, is not a test — and a test written to raise a coverage number
  and not to catch a bug is worse than none, because it makes a regression look covered.

## Definition of done

- [ ] Imports flow `shared → features → app`; no feature imports another feature; no deep
      import past a feature's `index.ts`.
- [ ] Every response parsed by a schema; server types derived from it, not written twice.
- [ ] One exported function per endpoint in `*.endpoints.ts`; every URL built there and
      nowhere else; typed object params.
- [ ] Query keys come from the resource's key factory; queries defined as `queryOptions`;
      every mutation invalidates what it changed.
- [ ] No component calls `fetch` or an endpoint function directly.
- [ ] No boolean-prop pile-up; presentational components take data, not fetches; no
      server type on a leaf component.
- [ ] Server state read from the cache only — not copied into state or a store; no
      `useEffect` computing a derived value.
- [ ] No hardcoded colour, spacing or `z-index`; no `!important`.
- [ ] Nothing from section 6 in the diff, and no inline lint suppression.
- [ ] Every added unit with a branch has a test — util, schema, endpoint, hook,
      component, store slice; every screen has an integration test.
- [ ] Tests query by role, mock at the network (not the hook), build fixtures from a
      factory, and cover loading, empty and error.

# Performance and pitfalls

The correctness traps that are invisible until they bite: shared slice backing arrays,
`append` that writes into a caller's memory, nil maps versus nil slices, deferred calls in a
loop, typed nil in an interface, field alignment, string and byte conversions. It closes with
the mental-model shifts for someone arriving from PHP.

Version basis: **Go 1.27.1** (released 2026-09-01); the language spec is "Language version
go1.27". Every rule here is stated against that toolchain. `[official]` —
[Go release history](https://go.dev/doc/devel/release),
[Go spec](https://go.dev/ref/spec)

## Slices, `append` and aliasing

- A slice value is a three-word header (pointer, length, capacity). Assignment and argument
  passing copy the header, never the elements. "When we pass slice values around, the header
  gets copied but the array it points to is always shared"; `a[x] = v` is visible through every
  slice over that array. `[official]` — [Go Slices: usage and internals](https://go.dev/blog/slices-intro)
- `append` reuses the underlying array whenever spare capacity exists; otherwise it allocates a
  new, sufficiently large array. So `return append(s, x)` can write into a caller's array past
  the caller's length; the caller's own header is unchanged, but a sibling slice sees the value.
  This is the classic aliasing bug. `[official]` —
  [Go spec §Appending to and copying slices](https://go.dev/ref/spec#Appending_to_and_copying_slices)

  ```go
  a := make([]int, 0, 4)
  a = append(a, 1, 2, 3)
  b := append(a, 4) // writes into a's spare slot
  c := append(a, 5) // overwrites it
  fmt.Println(b, c) // [1 2 3 5] [1 2 3 5]
  ```

- If a function must not touch the caller's array, copy first with `slices.Clone` or
  `append([]T(nil), s...)`. `[official]` — [pkg.go.dev/slices](https://pkg.go.dev/slices#Clone)
- The growth factor of `append` is unspecified; the spec promises only "a new, sufficiently
  large underlying array". The common statement that `append` doubles capacity is a
  simplification, not a guarantee. Never depend on a particular capacity after `append`; when
  a stable capacity is needed, allocate it with `make` or `slices.Grow`. `[official]` —
  [Go spec §Appending to and copying slices](https://go.dev/ref/spec#Appending_to_and_copying_slices)
- Slicing does not copy, so a small sub-slice retains the whole backing array and can pin a
  large allocation. Copy out with `slices.Clone`, `slices.Clip`, `strings.Clone` or
  `bytes.Clone` when only a small piece is kept. `[official]` —
  [Go Slices: usage and internals](https://go.dev/blog/slices-intro),
  [pkg.go.dev/strings §Clone](https://pkg.go.dev/strings#Clone)
- The `slices` and `maps` packages (Go 1.21+) are the idiomatic toolbox — `Clone`, `Grow`,
  `Clip`, `Compact`, `Delete`, `Equal`, `Sort`, and `maps.Clone`/`Copy`/`Equal`/`DeleteFunc` —
  and they define nil handling explicitly (`slices.Equal` treats nil and empty as equal;
  `Clone` preserves nilness). Do not hand-roll what they provide.
  `[official]` — [pkg.go.dev/slices](https://pkg.go.dev/slices),
  [pkg.go.dev/maps](https://pkg.go.dev/maps)

## nil map versus nil slice

- A nil map is readable and length-zero; reading a missing key yields the zero value. Writes
  panic: "A nil map behaves like an empty map when reading, but attempts to write to a nil map
  will cause a runtime panic." Allocate with `make(map[K]V)` before writing. `[official]` —
  [Go spec §Map types](https://go.dev/ref/spec#Map_types),
  [Go maps in action](https://go.dev/blog/maps)
- A nil slice is fully usable: `len` and `cap` are zero, ranging yields no iterations, and the
  first `append` allocates. "A nil slice is functionally equivalent to a zero-length slice…
  It has length zero and can be appended to, with allocation." `[official]` —
  [Arrays, slices (and strings): the mechanics of append](https://go.dev/blog/slices)
- Prefer `var t []string` to `t := []string{}`; the exception is JSON, where nil encodes `null`
  and empty encodes `[]`. The nil-versus-empty choice is a wire-format decision, not a
  performance one, and an API should be designed so callers need not distinguish them.
  `[official]` — [Code Review Comments §Declaring Empty Slices](https://go.dev/wiki/CodeReviewComments#declaring-empty-slices)

## `defer` in a loop

- `defer` is function-scoped, not block-scoped; its arguments are evaluated at the `defer`
  statement, and the calls run LIFO when the surrounding function returns. Effective Go's
  `for i := 0; i < 5; i++ { defer fmt.Printf("%d ", i) }` prints `4 3 2 1 0`. `[official]` —
  [Go spec §Defer statements](https://go.dev/ref/spec#Defer_statements),
  [Effective Go §Defer](https://go.dev/doc/effective_go#defer)
- A `defer` inside a loop therefore defers every iteration's call until the function returns:
  files stay open and memory accumulates. Extract the body into a function, or use a closure
  with its own `defer`, so each iteration's `Close`/`Unlock` runs before the next iteration.
  `[community]` — [Effective Go §Defer](https://go.dev/doc/effective_go#defer)

  ```go
  for _, name := range names {
      if err := readOne(name); err != nil { // readOne defers its own Close
          return err
      }
  }
  ```

- "`defer` is slow" is mostly obsolete: Go 1.14 "improves the performance of most uses of
  `defer` to incur almost zero overhead". The limit is that open-coded defers apply only when
  every `defer` executes at most once — "a `defer` may be on a conditional path, but is never
  in a loop in the control-flow graph" — and to at most eight defers, so loop defers fall back
  to the runtime chain. That is the same case this section already tells you to restructure.
  `[official]` — [Go 1.14 release notes](https://go.dev/doc/go1.14),
  [Open-coded defers design](https://go.googlesource.com/proposal/+/master/design/34481-opencoded-defers.md)

## Typed nil in an interface

- An interface is a `(type, value)` pair and "is `nil` only if the `V` and `T` are both unset".
  Storing a nil `*T` sets the type, so the interface is non-nil:

  ```go
  var p *MyError = nil
  var err error = p
  fmt.Println(err == nil) // false
  ```

  This is defined behaviour, not a quirk. Return `nil` explicitly from a function whose result
  is `error`; never return a concrete nil pointer typed as an error. `[official]` —
  [Go FAQ §Why is my nil error value not equal to nil?](https://go.dev/doc/faq#nil_error)

## Struct field alignment

- A struct's size includes padding introduced for field alignment, so field order changes the
  size. `unsafe.Sizeof`, `unsafe.Alignof` and `unsafe.Offsetof` expose it, and the
  `fieldalignment` analyzer "detects structs that would use less memory if their fields were
  sorted". `[official]` — [pkg.go.dev/unsafe](https://pkg.go.dev/unsafe),
  [fieldalignment](https://pkg.go.dev/golang.org/x/tools/go/analysis/passes/fieldalignment)
- Reordering is not universally worth it: care when the struct is large, instantiated in very
  large numbers, or sits in hot memory; do not reorder a public struct, because field order is
  part of the API for positional literals; and keep hot fields together. `fieldalignment` is an
  explicit `x/tools` analyzer, not part of the default `go vet` suite. `[community]` —
  [fieldalignment](https://pkg.go.dev/golang.org/x/tools/go/analysis/passes/fieldalignment)

## String and `[]byte` conversions, `Builder` and `Buffer`

- A `string` is immutable, so a `string`↔`[]byte` conversion normally copies: "when we do
  either of these conversions, a copy of the array must be made." `[official]` —
  [Arrays, slices (and strings): the mechanics of append](https://go.dev/blog/slices)
- The compiler elides the copy in specific idioms — `m[string(b)]` map lookup,
  `for i, c := range []byte(s)`, and a `string(b)` used only for comparison — but that is an
  optimisation, not a guarantee. Do not write code whose correctness depends on the elision.
  `[community]` — [CompilerOptimizations](https://go.dev/wiki/CompilerOptimizations)
- `strings.Builder` builds a string with minimal copying; "the zero value is ready to use. Do
  not copy a non-zero Builder." Use it when the output is a string and you only append, and
  call `Grow(n)` to preallocate. `bytes.Buffer` is a variable-sized read/write buffer; use it
  when you need to read back, implement `io.Reader`/`io.Writer`, or use `AvailableBuffer`/`Next`.
  `[official]` — [pkg.go.dev/strings §Builder](https://pkg.go.dev/strings#Builder),
  [pkg.go.dev/bytes §Buffer](https://pkg.go.dev/bytes#Buffer)
- Do not build a string with `+=` in a loop; use a `Builder` or `Buffer` with `Grow`, or
  `strings.Join` for a known slice. `[community]` —
  [pkg.go.dev/strings §Builder](https://pkg.go.dev/strings#Builder)

## `sync.Pool` and preallocation

- `sync.Pool` is a temporary-object free list, not a cache: "Any item stored in the Pool may be
  removed automatically at any time without notification", and its purpose is "relieving
  pressure on the garbage collector". Reset state before reuse, prefer pointer types (the
  example returns `new(bytes.Buffer)`), and never rely on an item surviving. The performance
  wiki warns that "incorrect use of `sync.Pool` can lead to use-after-free bugs".
  `[official]` — [pkg.go.dev/sync §Pool](https://pkg.go.dev/sync#Pool),
  `[community]` — [Performance](https://go.dev/wiki/Performance)
- "Only use `sync.Pool` once a profile shows allocation or GC pressure" is community
  convention, consistent with the stdlib docs but not stated by them as a rule.
  `[community]` — [Performance](https://go.dev/wiki/Performance)
- Preallocate when a typical size is known: "If you know a typical size of the slice, you can
  preallocate a backing array for it." Idioms are `make([]T, 0, n)`, `slices.Grow(s, n)` and
  `b.Grow(n)`; do not guess a capacity, because over-allocation trades memory for nothing.
  `[community]` — [Performance](https://go.dev/wiki/Performance)

## `range` copies and loop-variable pointers

- `for _, v := range xs` assigns each element to `v`, so `v` is a copy, not a pointer into the
  slice. `[official]` — [Go spec §For statements](https://go.dev/ref/spec#For_statements),
  `[community]` — [Range](https://go.dev/wiki/Range)
- For large structs, iterate by index (`for i := range xs { use xs[i] }`) or take `&xs[i]`.
  The compiler may avoid the copy when `v` is neither mutated nor address-taken, but that is an
  inference from escape analysis, not a documented guarantee. `[community]` —
  [Range](https://go.dev/wiki/Range)
- Loop-variable capture is fixed for a module that declares `go 1.22` or later, as detailed in
  [concurrency.md](concurrency.md#the-go-122-loop-variable-change). A pre-1.22 module still
  shares one variable across iterations, so `&v` can still be wrong there. `[official]` —
  [Go 1.22 release notes](https://go.dev/doc/go1.22)

## Coming from PHP

- **Errors are values, not exceptions.** Go has no `try`/`catch`/`finally`; errors are returned
  and checked with `if err != nil`, which is normal control flow. `panic`/`recover` are for
  catastrophic conditions, not for routine failures. `[official]` —
  [Go FAQ §Why does Go not have exceptions?](https://go.dev/doc/faq#exceptions),
  [Code Review Comments §Don't Panic](https://go.dev/wiki/CodeReviewComments#dont-panic)
- **Zero values replace `null`.** Good design makes the zero value usable (`bytes.Buffer`,
  `sync.Mutex` need no `Init`). There is no general "unset"; where absence matters, use an
  `ok` second return, a pointer, or `omitempty` explicitly. `[official]` —
  [Effective Go §Allocation with new](https://go.dev/doc/effective_go#allocation_new)
- **There are no associative arrays.** Use a map for dynamic keys and a struct for fixed
  fields. Maps are reference types, unordered, and not safe for concurrent writes; structs give
  typed, compile-checked fields. Do not reach for `map[string]any` to imitate a PHP array.
  `[official]` — [Go maps in action](https://go.dev/blog/maps),
  [Go FAQ §Why are map operations not defined to be atomic?](https://go.dev/doc/faq#atomic_maps)
- **Everything is passed by value.** That differs from PHP, where objects behave like handles
  and arrays copy on assignment. Choose a pointer receiver to mutate, to avoid copying a value
  that holds a mutex, or for a large struct; choose a value receiver for a small
  naturally-value type, and do not mix the two on one type. `[official]` —
  [Go FAQ §Pass by value](https://go.dev/doc/faq#pass_by_value),
  [Code Review Comments §Receiver Type](https://go.dev/wiki/CodeReviewComments#receiver-type)
- **Goroutines are not event-loop callbacks.** They are multiplexed coroutines with resizable
  stacks, not threads and not a single-threaded loop. Prefer synchronous functions, make every
  goroutine's lifetime obvious, and coordinate with channels and `context` rather than shared
  mutable globals. `[official]` — [Go FAQ §Why goroutines instead of threads?](https://go.dev/doc/faq#goroutines),
  [Code Review Comments §Goroutine Lifetimes](https://go.dev/wiki/CodeReviewComments#goroutine-lifetimes)
- **Porting PHP idioms produces un-idiomatic Go.** Dynamic arrays become slices with `append`
  and `make(..., 0, n)`/`slices.Grow`; PHP array functions become `slices`/`maps`; string
  interning has no equivalent, and `strings.Clone` is for unpinning memory, per its doc, "only
  rarely, and only when profiling indicates that it is needed". The real gap is copying versus
  sharing (see the aliasing section) and explicit allocation, not syntax. This mapping is this
  skill's synthesis, inference from Go's documented semantics rather than a Go-team comparison.
  `[community]` — [pkg.go.dev/strings §Clone](https://pkg.go.dev/strings#Clone),
  [Go Slices: usage and internals](https://go.dev/blog/slices-intro)

## Sources

- [Go Slices: usage and internals](https://go.dev/blog/slices-intro)
- [Arrays, slices (and strings): the mechanics of append](https://go.dev/blog/slices)
- [Go maps in action](https://go.dev/blog/maps)
- [pkg.go.dev/slices](https://pkg.go.dev/slices)
- [pkg.go.dev/maps](https://pkg.go.dev/maps)
- [pkg.go.dev/strings](https://pkg.go.dev/strings)
- [pkg.go.dev/bytes](https://pkg.go.dev/bytes)
- [pkg.go.dev/sync](https://pkg.go.dev/sync)
- [pkg.go.dev/unsafe](https://pkg.go.dev/unsafe)
- [Go FAQ](https://go.dev/doc/faq)
- [The Go Programming Language Specification](https://go.dev/ref/spec)
- [Effective Go](https://go.dev/doc/effective_go)
- [Go Code Review Comments](https://go.dev/wiki/CodeReviewComments)
- [Range](https://go.dev/wiki/Range)
- [CompilerOptimizations](https://go.dev/wiki/CompilerOptimizations)
- [Performance](https://go.dev/wiki/Performance)
- [Go 1.14 release notes](https://go.dev/doc/go1.14)
- [Go 1.22 release notes](https://go.dev/doc/go1.22)
- [Go release history](https://go.dev/doc/devel/release)
- [fieldalignment](https://pkg.go.dev/golang.org/x/tools/go/analysis/passes/fieldalignment)
- [Open-coded defers design](https://go.googlesource.com/proposal/+/master/design/34481-opencoded-defers.md)

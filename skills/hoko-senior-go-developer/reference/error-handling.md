# Error handling

Errors are values, so wrapping, identity and recovery are all explicit choices. This file
covers `%w` versus `%v`, the wrap-once question, sentinels versus custom types, the
`errors` helpers including Go 1.26's `AsType`, multi-errors, the panic policy, and where
storage errors turn into domain and HTTP errors.

The mechanics below are current for a module on `go 1.27`: Go 1.27 lists no change to
`errors`, `fmt` error wrapping, or `net/http` panic handling. `[official]` —
[Go 1.27 release notes](https://go.dev/doc/go1.27)

## `%w` versus `%v`: exposure, not depth

- The decision is per-error and is about API exposure. "Wrap an error to expose it to
  callers. Do not wrap an error when doing so would expose implementation details." Wrapping
  "makes that error part of your API"; if you will not commit to that error in future, do not
  wrap it. `[official]` — [Working with Errors in Go 1.13](https://go.dev/blog/go1.13-errors)
- `%w` and `%v` produce the same error text. The only difference is whether
  `errors.Is`/`errors.As` can reach the wrapped value. `[official]` —
  [Working with Errors in Go 1.13](https://go.dev/blog/go1.13-errors)
- The blog's canonical example repackages an `*os.PathError` with `%v` precisely because
  `%w` "would permit the caller to unwrap the original `*os.PathError`". `[official]` —
  [Working with Errors in Go 1.13](https://go.dev/blog/go1.13-errors)
- Wrapping is opt-in because it "would effectively change the exposed surface of a package by
  revealing the types of the wrapped errors". `[official]` —
  [Error values design doc](https://go.googlesource.com/proposal/+/master/design/29934-error-values.md)
- The Error Values FAQ frames it as a weighing: "For each error you return, you have to weigh
  the choice between helping your clients and locking yourself in." You can add human context
  with `%v` or a custom `Error()` without granting programmatic access. `[community]` —
  [Error Values FAQ](https://go.dev/wiki/ErrorValueFAQ)
- Put `%w` at the end, `"...: %w"`, so the printed chain reads newest-to-oldest, except for a
  sentinel that categorises the failure, which may go at the front (`"%w: invalid header"`).
  `[community]` — [Google Go best practices §Errors](https://google.github.io/styleguide/go/best-practices#errors)

## "Wrap once, at the layer that adds information" — contested

The Go team states **no rule that you should wrap at every layer and no rule that you must
wrap exactly once**. The per-error expose/don't-expose test above is the Go-team position.
The familiar "wrap once, at the layer that adds information" phrasing is a useful community
rule of thumb, but it is not Go-team language, and this doc labels it accordingly.
`[contested]` — [Working with Errors in Go 1.13](https://go.dev/blog/go1.13-errors)

- One community camp wraps or annotates at every return site for context: `pkg/errors`
  (`errors.Wrap`) is the origin, CockroachDB wraps with a stack at every site, the Terraform
  AWS provider mandates it, and the `wrapcheck` linter enforces it. `[community]` —
  [rednafi, "Go errors: to wrap or not to wrap?"](https://rednafi.com/go/to-wrap-or-not-to-wrap/),
  [Dave Cheney, "Stack traces and the errors package"](https://dave.cheney.net/2016/06/12/stack-traces-and-the-errors-package)
- The other camp wraps only where the wrap adds information or defines the API, because deep
  wrapping produces nested "checking warehouse: querying database: connection refused" chains
  and turns every layer into contract. `[community]` —
  [rednafi, "Go errors: to wrap or not to wrap?"](https://rednafi.com/go/to-wrap-or-not-to-wrap/)
- The launch decision itself raised the risk: "indiscriminate wrapping can expose
  implementation details, introducing undesired coupling between packages." `[official]` —
  [Error values design doc](https://go.googlesource.com/proposal/+/master/design/29934-error-values.md)

**This skill takes the exposure test, not the frequency rule: wrap with `%w` where you are
adding information and are willing to make the cause part of your API, and use `%v` when the
cause is an implementation detail.** `[contested]` —
[Working with Errors in Go 1.13](https://go.dev/blog/go1.13-errors)

## Sentinel errors versus custom types

- A sentinel is a package-level `errors.New` value returned wrapped, so callers match it with
  `errors.Is`; the blog's `FetchItem` example returns an error wrapping `ErrNotFound`.
  `[official]` — [Working with Errors in Go 1.13](https://go.dev/blog/go1.13-errors)
- A custom type is right when the caller needs structured data out of the error, such as
  `*os.PathError`'s `Path` field or `json.SyntaxError`'s `Offset`. `[official]` —
  [Error handling and Go](https://go.dev/blog/error-handling-and-go)
- A predicate function is an accepted third shape. `[community]` —
  [Error Values FAQ](https://go.dev/wiki/ErrorValueFAQ)
- `errors.New` returns a distinct value on every call even for identical text, so a sentinel
  must be one declared package-level variable reused everywhere; otherwise `errors.Is` on two
  equal-text errors is false. `[official]` — [pkg.go.dev/errors](https://pkg.go.dev/errors#New)
- Prefer wrapping a sentinel over returning it directly, so callers are forced through
  `errors.Is` and you can add context later. `[official]` —
  [Working with Errors in Go 1.13](https://go.dev/blog/go1.13-errors)
- `io.EOF` is the exception that should never be wrapped: callers compare `err == io.EOF`, and
  `io.Reader` contracts assume the value survives. `[community]` —
  [Error Values FAQ](https://go.dev/wiki/ErrorValueFAQ)
- Error strings are not capitalised and do not end in punctuation, because they are usually
  printed after other context. `[official]` —
  [Code Review Comments §Error Strings](https://go.dev/wiki/CodeReviewComments#error-strings)

## `errors.Is`, `errors.As`, `errors.AsType`, `errors.Unwrap`

- An error wraps another if it has `Unwrap() error` or `Unwrap() []error`; a nil return means
  it wraps nothing, and an `Unwrap() []error` may not contain a nil element. `[official]` —
  [pkg.go.dev/errors](https://pkg.go.dev/errors)
- `Is` and `As` inspect the whole tree of an error, "examining first the error itself followed
  by the tree of each of its children in turn (pre-order, depth-first traversal)". Once
  `Unwrap() []error` exists, successive unwrapping is a tree, not a list. `[official]` —
  [pkg.go.dev/errors](https://pkg.go.dev/errors)
- `Is(err, target)` is true when a node equals `target`, or has an `Is(error) bool` method
  returning true; `target` must be comparable. Use `errors.Is` instead of `==`.
  `[official]` — [pkg.go.dev/errors](https://pkg.go.dev/errors)
- `As(err, target)` finds the first node assignable to the pointer `target`, or whose
  `As(any) bool` sets it; it panics if `target` is not a non-nil pointer to a type that
  implements `error` or to any interface type. Use it instead of a type assertion.
  `[official]` — [pkg.go.dev/errors](https://pkg.go.dev/errors)
- Go 1.26 adds `func AsType[E error](err error) (E, bool)`, and the current package docs say:
  "For most uses, prefer `AsType`." The release notes call it "type-safe, faster, and, in most
  cases, easier to use". Prefer `errors.AsType[*fs.PathError](err)` over
  `errors.As(err, &pathErr)`. `errors.As` is not deprecated. `[official]` —
  [pkg.go.dev/errors](https://pkg.go.dev/errors#AsType),
  [Go 1.26 release notes](https://go.dev/doc/go1.26)

  ```go
  pathErr, ok := errors.AsType[*fs.PathError](err)
  if ok {
      log.Printf("path %q: %v", pathErr.Path, pathErr.Err)
  }
  ```

- `errors.Unwrap` calls only an `Unwrap() error` method; it does not unwrap errors returned by
  `Join`. Prefer `Is`/`As` over hand-written unwrap loops. `[official]` —
  [pkg.go.dev/errors](https://pkg.go.dev/errors#Unwrap)
- An `Is` method should "only shallowly compare err and the target and not call `Unwrap` on
  either". `[official]` — [pkg.go.dev/errors](https://pkg.go.dev/errors#Is)

## `errors.Join` and multiple wrapped errors

- `errors.Join` (Go 1.20) discards nil errors, returns nil when all are nil, formats the
  remainder separated by newlines, and the non-nil result implements `Unwrap() []error`, so
  `Is`/`As` inspect every element. `[official]` —
  [pkg.go.dev/errors](https://pkg.go.dev/errors#Join)
- Since Go 1.20 `fmt.Errorf` accepts multiple `%w` verbs and returns an error that unwraps to
  all of them. `[official]` — [Go 1.20 release notes](https://go.dev/doc/go1.20)

  ```go
  err := errors.Join(validateName(name), validateAge(age))
  if errors.Is(err, ErrInvalidName) {
      // reached through the joined tree
  }
  ```

- `Is`/`As` traverse a multiply-wrapped error depth-first; `errors.Unwrap` does not.
  `[official]` — [pkg.go.dev/errors](https://pkg.go.dev/errors#Unwrap)

## `panic` and `recover`

- Legitimate panics mark truly unrecoverable conditions and impossible states. Effective Go
  calls panic "a way to indicate that something impossible has happened", says library
  functions "should avoid panic", and allows initialization failure as a possible exception.
  `[official]` — [Effective Go §Panic](https://go.dev/doc/effective_go#panic)
- Do not use panic for normal error handling; return an `error` and multiple values instead.
  `[official]` — [Code Review Comments §Don't Panic](https://go.dev/wiki/CodeReviewComments#dont-panic)
- By convention, no explicit `panic()` crosses a package boundary; report error conditions to
  callers by returning an error value. Effective Go's `regexp`-style example recovers only its
  own error type, lets anything else keep unwinding, and so "does not expose panics to its
  client". `[community]` — [Go wiki §PanicAndRecover](https://go.dev/wiki/PanicAndRecover),
  `[official]` — [Effective Go §Recover](https://go.dev/doc/effective_go#recover)
- `recover` only works when called directly by a deferred function, and a panic cannot be
  recovered by a different goroutine. `[official]` —
  [Go spec §Handling panics](https://go.dev/ref/spec#Handling_panics)
- The strongest form of "do not recover panics you did not cause" is Google's: recovering to
  avoid a crash can propagate a corrupted state, and a recovery must distinguish the panics it
  raises itself from those it did not (`if !ok { panic(p) } // Propagate the panic`). The
  exact phrase is community/Google language, not a verbatim Go-team sentence; the Go-team
  equivalents are the package-boundary rule and the re-panic-on-foreign-value pattern.
  `[community]` —
  [Google Go best practices §When to panic](https://google.github.io/styleguide/go/best-practices#when-to-panic)

## `log.Fatal` and `os.Exit` in libraries

- `log.Fatal` is `Print` followed by `os.Exit(1)`, and `os.Exit` terminates immediately
  without running any deferred function, so a caller's files, locks, transactions and buffers
  are not cleaned up and the condition cannot be recovered or translated. `[official]` —
  [pkg.go.dev/log](https://pkg.go.dev/log#Fatal),
  [Go issue #24869](https://go.dev/issue/24869)
- Calling `os.Exit` directly in a library "should generally be avoided". `[official]` —
  [Go issue #30219](https://go.dev/issue/30219)
- Libraries should return an error rather than abort the program; an initialization error
  belongs to `main`, which may then exit. `[community]` —
  [Google Go best practices §Program initialization](https://google.github.io/styleguide/go/best-practices#program-initialization)

## Service and API boundaries

- The official database tutorial translates `sql.ErrNoRows` at the call boundary and discards
  the storage identity, using a fresh error with `%v`, not `%w`:

  ```go
  if err := db.QueryRow("SELECT stock FROM album WHERE id = ?", id).Scan(&enough); err != nil {
      if errors.Is(err, sql.ErrNoRows) {
          return false, fmt.Errorf("canPurchase %d: unknown album", id)
      }
      return false, fmt.Errorf("canPurchase %d: %v", id, err)
  }
  ```

  `[official]` — [Querying for data](https://go.dev/doc/database/querying)
- A package that uses `database/sql` "probably should not return an error which unwraps to the
  result of one of those calls"; wrapping `sql.ErrNoRows` makes it part of your API forever.
  Catch `errors.Is(err, sql.ErrNoRows)` in the repository or storage layer and return a domain
  sentinel such as `ErrUserNotFound` instead. If you wrap, wrap the domain sentinel, not the
  driver error. `[official]` —
  [Working with Errors in Go 1.13](https://go.dev/blog/go1.13-errors)
- Mapping a domain error to an HTTP status has no Go-team canonical document; this is
  inference from absence. The common shape is a transport-layer translator, a small
  `func(error) int` or a typed `statusError{status int; err error}` the handler consults with
  `errors.AsType[*statusError]`, defaulting to 500 and never returning the internal message to
  the client. Keep HTTP status codes out of the domain layer. `[community]` —
  [rednafi, "Error translation in Go services"](https://rednafi.com/go/error-translation/),
  [boldlygo, "Error handling in Go web apps"](https://boldlygo.tech/posts/2024-01-08-error-handling/)
- Never let an internal error (driver, filesystem, RPC) become unwrappable across a public API
  unless you commit to it. Repackage with `%v` to keep the text and drop the structure.
  `[official]` — [Working with Errors in Go 1.13](https://go.dev/blog/go1.13-errors)
- At an RPC, IPC or storage boundary, translate domain errors into a canonical error space
  (for example gRPC `codes.NotFound`) rather than `%w`-wrapping the raw error, because the
  client does not care about the internal filesystem error. `[community]` —
  [Google Go best practices §Errors](https://google.github.io/styleguide/go/best-practices#errors)
- Return a client-facing message from a separate field or a fresh `%v` error, log the full
  error server-side, and do not send an internal error's `err.Error()` to the client.
  `[community]` —
  [rednafi, "Error translation in Go services"](https://rednafi.com/go/error-translation/)

## `panic`/`recover` in a handler and in a worker goroutine

- You do not need your own `recover` to keep an HTTP server alive. If `ServeHTTP` panics, the
  server assumes the effect was isolated to the request, recovers, logs a stack trace, and
  closes the connection or sends an HTTP/2 `RST_STREAM`. To abort a handler without a logged
  stack trace, panic with the sentinel value `ErrAbortHandler`. `[official]` —
  [pkg.go.dev/net/http](https://pkg.go.dev/net/http#Server)
- Add a handler `recover` only for different logging or telemetry or to return a specific
  status, and re-panic on values that are not yours. The standard library's own recovery is
  described as a deliberate historical exception to the no-recover rule. `[community]` —
  [Google Go best practices §When to panic](https://google.github.io/styleguide/go/best-practices#when-to-panic)
- The server's recovery does not protect goroutines you start. A panic in a spawned goroutine
  crashes the process unless that goroutine or a defer inside it recovers, and a panic cannot
  be recovered by a different goroutine. A long-lived worker whose single bad job must not
  kill the process needs its own `defer func() { if r := recover(); r != nil { … } }()`, with
  the same discipline of re-panicking on foreign values. `[official]` —
  [Go spec §Handling panics](https://go.dev/ref/spec#Handling_panics),
  [Effective Go §Recover](https://go.dev/doc/effective_go#recover)

  ```go
  func safelyDo(job Job) {
      defer func() {
          if r := recover(); r != nil {
              if err, ok := r.(jobPanic); ok {
                  log.Printf("job %v panicked: %v", job.ID, err)
                  return
              }
              panic(r)
          }
      }()
      job.Run()
  }
  ```

## Sources

- [Working with Errors in Go 1.13](https://go.dev/blog/go1.13-errors)
- [Error handling and Go](https://go.dev/blog/error-handling-and-go)
- [pkg.go.dev/errors](https://pkg.go.dev/errors)
- [Error Values FAQ](https://go.dev/wiki/ErrorValueFAQ)
- [Go Code Review Comments](https://go.dev/wiki/CodeReviewComments)
- [Go wiki §PanicAndRecover](https://go.dev/wiki/PanicAndRecover)
- [Effective Go](https://go.dev/doc/effective_go)
- [The Go Programming Language Specification](https://go.dev/ref/spec)
- [Go 1.20 release notes](https://go.dev/doc/go1.20)
- [Go 1.26 release notes](https://go.dev/doc/go1.26)
- [Go 1.27 release notes](https://go.dev/doc/go1.27)
- [Querying for data](https://go.dev/doc/database/querying)
- [Error values design doc](https://go.googlesource.com/proposal/+/master/design/29934-error-values.md)
- [pkg.go.dev/log](https://pkg.go.dev/log)
- [pkg.go.dev/net/http](https://pkg.go.dev/net/http)
- [Go issue #24869](https://go.dev/issue/24869)
- [Go issue #30219](https://go.dev/issue/30219)
- [Google Go Style Guide — best practices](https://google.github.io/styleguide/go/best-practices)
- [rednafi, "Go errors: to wrap or not to wrap?"](https://rednafi.com/go/to-wrap-or-not-to-wrap/)
- [rednafi, "Error translation in Go services"](https://rednafi.com/go/error-translation/)
- [boldlygo, "Error handling in Go web apps"](https://boldlygo.tech/posts/2024-01-08-error-handling/)
- [Dave Cheney, "Stack traces and the errors package"](https://dave.cheney.net/2016/06/12/stack-traces-and-the-errors-package)

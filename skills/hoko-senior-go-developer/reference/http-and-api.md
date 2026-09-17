# HTTP and API

Building a service on the standard library: routing with `ServeMux`, choosing a router,
middleware, decoding and validating requests, JSON encoding and error responses, server
timeouts, graceful shutdown and panic recovery.

The `net/http` and `encoding/json` docs cited here render at `go1.27.1`. Method and wildcard
routing needs the module's `go` directive at 1.22 or higher; `MaxHeaderValueCount`,
`httptest.NewTestServer` and the `encoding/json/v2` packages need 1.27. `[official]` —
[pkg.go.dev/net/http](https://pkg.go.dev/net/http),
[Go 1.22 release notes](https://go.dev/doc/go1.22),
[Go 1.27 release notes](https://go.dev/doc/go1.27)

## Routing with the standard library

- A `ServeMux` pattern is `[METHOD ][HOST]/[PATH]`, with all parts optional. Method and
  literal path parts are case-sensitive and a hostless pattern matches any host. A pattern
  with no method matches every method; `GET` also matches `HEAD`; any other method must match
  exactly. `[official]` — [pkg.go.dev/net/http](https://pkg.go.dev/net/http)
- A path segment may be `{NAME}` (matches one segment) or `{NAME...}` (matches the rest,
  only at the end). Wildcard names must be valid Go identifiers and occupy a full segment:
  `/{x}` is a wildcard, `/a{x}` is invalid. A trailing slash acts as an anonymous `...`
  wildcard, and `{$}` anchors the pattern to the end of the URL: `/{$}` matches only `/`,
  while `/` matches every path. `[official]` — [pkg.go.dev/net/http](https://pkg.go.dev/net/http)
- Read wildcard values with `r.PathValue(name)`, which returns the empty string when the
  request did not match a pattern. `[official]` —
  [pkg.go.dev/net/http](https://pkg.go.dev/net/http#Request.PathValue)
- Precedence is most-specific-wins: P1 is more specific than P2 when P1 matches a strict
  subset of P2's requests. If neither is more specific the patterns conflict, and registering
  the second makes `Handle`/`HandleFunc` panic. One backwards-compatibility exception: if a
  host pattern and a hostless pattern would conflict, the host pattern wins.
  `[official]` — [pkg.go.dev/net/http](https://pkg.go.dev/net/http#ServeMux)
- `GODEBUG=httpmuxgo121=1` restores the pre-1.22 match behaviour. It is read once at
  startup. `[official]` — [pkg.go.dev/net/http](https://pkg.go.dev/net/http#ServeMux)
- The additions removed the per-handler `r.Method` switch and manual path splitting for
  common REST routes. The Go team framed it as "one fewer dependency for many projects"
  while keeping third-party frameworks "a fine choice for … programs with advanced routing
  needs". `[official]` — [Routing enhancements](https://go.dev/blog/routing-enhancements)

  ```go
  mux := http.NewServeMux()
  mux.HandleFunc("GET /items/{id}", getItem)
  mux.HandleFunc("GET /items/{$}", listItems)
  mux.HandleFunc("POST /items", createItem)

  func getItem(w http.ResponseWriter, r *http.Request) {
      id := r.PathValue("id")
      // ...
  }
  ```

## Choosing a router — contested

The Go team takes a balanced position, not a tribal one: the routing additions mean one fewer
dependency for many projects, and third-party web frameworks remain a fine choice for
advanced routing. `[official]` — [Routing enhancements](https://go.dev/blog/routing-enhancements)

- **chi** (`go-chi/chi/v5`) is a stdlib-compatible radix-tree router: its `Router` is an
  `http.Handler` and its handlers are plain `http.Handler`. It adds route groups (`Route`,
  `Group`), inline middleware (`With`), a middleware stack (`Use`), sub-router mounting
  (`Mount`), regex/typed params (`{slug:[a-z-]+}`) and `chi.URLParam`. It keeps its own
  pattern syntax and does not delegate to `ServeMux`. `[community]` —
  [go-chi/chi](https://github.com/go-chi/chi)
- **gin** is httprouter-based, uses a bespoke `*gin.Context` instead of the stdlib handler
  signature, and bundles binding/validation, grouping, recovery and rendering. Its README
  states 1.12.0 and requires Go 1.26+. **echo** is built on `net/http` and interoperates via
  `WrapHandler`/`WrapMiddleware`, adding a radix router, binding with a pluggable validator,
  groups and centralized error handling; its README states v5 is current and v4 receives
  security and bug fixes until 2026-12-31. These version and support numbers are the
  projects' own self-report. `[community]` — [gin](https://github.com/gin-gonic/gin),
  [echo](https://github.com/labstack/echo)
- Community write-ups split along the same line: stdlib for small, flat services, chi when
  middleware grouping and a nested route tree grow, gin/echo when batteries-included binding
  and rendering is valued. Those thresholds are blog-post guidance. `[community]` —
  [Go web frameworks in 2026](https://abrarqasim.com/blog/golang-web-frameworks-2026-the-router-i-reach-for-first/)

**This skill takes the stdlib `ServeMux` as the default. Reach for chi only when per-group
middleware or route nesting genuinely demands it; gin and echo are not the default guidance.**
`[contested]` — [Routing enhancements](https://go.dev/blog/routing-enhancements)

## Middleware

- There is no middleware type in the standard library. The community convention is
  `func(http.Handler) http.Handler`, chained by hand (`mwA(mwB(handler))`) or with a small
  local chain helper. Because that signature is the stdlib `http.Handler`, net/http-style
  middleware composes with chi and wrapped echo middleware; gin middleware
  (`gin.HandlerFunc`) is gin-specific. `[community]` — [pkg.go.dev/net/http](https://pkg.go.dev/net/http#Handler),
  [go-chi/chi](https://github.com/go-chi/chi),
  [labstack/echo](https://github.com/labstack/echo)
- Structured logging comes from the standard library's `log/slog`. `[official]` —
  [pkg.go.dev/log/slog](https://pkg.go.dev/log/slog)
- Wiring an `slog` logger into request-logging middleware is community usage, not a
  prescribed `net/http` pattern. `[community]` —
  [pkg.go.dev/net/http](https://pkg.go.dev/net/http)

  ```go
  func RequestLog(log *slog.Logger, next http.Handler) http.Handler {
      return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
          start := time.Now()
          rec := &statusRecorder{ResponseWriter: w, status: http.StatusOK}
          next.ServeHTTP(rec, r)
          log.Info("request",
              "method", r.Method,
              "path", r.URL.Path,
              "status", rec.status,
              "duration", time.Since(start),
          )
      })
  }
  ```

## Decoding and validating requests

- Decode with an `encoding/json` `Decoder` and call `DisallowUnknownFields()` to reject
  object members that do not match an exported field. The v2 equivalent knob is
  `json.RejectUnknownMembers(true)`, and `json.UnmarshalRead(r.Body, &v)` reads an
  `io.Reader`. `[official]` —
  [pkg.go.dev/encoding/json](https://pkg.go.dev/encoding/json#Decoder.DisallowUnknownFields),
  [pkg.go.dev/encoding/json/v2](https://pkg.go.dev/encoding/json/v2)
- Cap the request body with `http.MaxBytesReader(w, r.Body, n)`, or wrap the handler with
  `http.MaxBytesHandler(h, n)`. Exceeding the limit surfaces as `*http.MaxBytesError`.
  `[official]` — [pkg.go.dev/net/http](https://pkg.go.dev/net/http#MaxBytesReader),
  [pkg.go.dev/net/http](https://pkg.go.dev/net/http#MaxBytesHandler)
- Semantic and field validation (required fields, ranges, cross-field rules) is yours; the
  standard library does not do it. Validate at the transport boundary, before the value
  reaches the domain layer. `[official]` — [pkg.go.dev/encoding/json](https://pkg.go.dev/encoding/json)

  ```go
  func decode[T any](w http.ResponseWriter, r *http.Request, dst *T) error {
      r.Body = http.MaxBytesReader(w, r.Body, 1<<20)
      dec := json.NewDecoder(r.Body)
      dec.DisallowUnknownFields()
      if err := dec.Decode(dst); err != nil {
          return err
      }
      return nil
  }
  ```

## JSON encoding and error responses

- Go 1.27 adds `encoding/json/v2` (semantic marshal/unmarshal with variadic options) and
  `encoding/json/jsontext` (syntactic tokens and values). `[official]` —
  [Go 1.27 release notes](https://go.dev/doc/go1.27)
- **The v1 `encoding/json` package is now implemented on top of the v2 engine but keeps its
  v1 defaults**, because it calls v2 with `DefaultOptionsV1()`. It still replaces invalid
  UTF-8, allows duplicate object names, and matches names case-insensitively; only error
  message text may differ. Do not describe `encoding/json` as rejecting duplicate names.
  `[official]` — [pkg.go.dev/encoding/json](https://pkg.go.dev/encoding/json#hdr-Migrating_to_v2)
- **`encoding/json/v2` itself is stricter by default**: it rejects invalid UTF-8 and rejects
  duplicate object names, and matches names case-sensitively. Relax the first two with
  `jsontext.AllowInvalidUTF8(true)` and `jsontext.AllowDuplicateNames(true)`.
  `[official]` — [pkg.go.dev/encoding/json/v2](https://pkg.go.dev/encoding/json/v2#hdr-Security_Considerations),
  [pkg.go.dev/encoding/json/jsontext](https://pkg.go.dev/encoding/json/jsontext)
- The v1 docs state the migration position for new code: "All new usages of 'json' in Go
  should use the v2 package, but the v1 package will forever remain supported." Migration can
  be incremental through `DefaultOptionsV1()`/`DefaultOptionsV2()` and the per-behaviour
  options. Build with `GOEXPERIMENT=nojsonv2` to opt out of the new engine entirely.
  `[official]` — [pkg.go.dev/encoding/json](https://pkg.go.dev/encoding/json#hdr-Migrating_to_v2),
  [Go 1.27 release notes](https://go.dev/doc/go1.27)
- The standard library gives you encoding, not a response contract. `http.Error` writes
  `text/plain`, not JSON. A consistent JSON error shape such as `{"error": ...}` or RFC 9457
  problem details is community convention; the Go team prescribes none.
  `[community]` — [pkg.go.dev/net/http](https://pkg.go.dev/net/http#Error),
  [pkg.go.dev/encoding/json/v2](https://pkg.go.dev/encoding/json/v2)

## Server timeouts and hardening

- The zero `Server` is valid but has no timeouts. `[official]` —
  [pkg.go.dev/net/http#Server](https://pkg.go.dev/net/http#Server)
- `ReadTimeout` bounds reading the entire request including the body (zero or negative means
  none); the docs say most users prefer `ReadHeaderTimeout`, which bounds only headers and
  falls back to `ReadTimeout` when zero. `WriteTimeout` bounds writes and resets when a new
  request's header is read. `IdleTimeout` bounds keep-alive idle waits and falls back to
  `ReadTimeout`. `[official]` — [pkg.go.dev/net/http#Server](https://pkg.go.dev/net/http#Server)
- `MaxHeaderBytes` defaults to `DefaultMaxHeaderBytes`, 1 MB. `[official]` —
  [pkg.go.dev/net/http#Server](https://pkg.go.dev/net/http#Server)
- `MaxHeaderValueCount` is new in Go 1.27 and bounds the number of header values. Zero means
  `DefaultMaxHeaderValueCount`, 500. Comma-separated values in one line count once; multiple
  header lines count multiple times. `[official]` —
  [Go 1.27 release notes](https://go.dev/doc/go1.27),
  [pkg.go.dev/net/http](https://pkg.go.dev/net/http#DefaultMaxHeaderValueCount)

  ```go
  srv := &http.Server{
      Addr:              ":8080",
      Handler:           mux,
      ReadHeaderTimeout: 5 * time.Second,
      ReadTimeout:       15 * time.Second,
      WriteTimeout:      15 * time.Second,
      IdleTimeout:       60 * time.Second,
  }
  ```

## Graceful shutdown

- `Server.Shutdown(ctx)` closes listeners, closes idle connections, then waits for active
  connections to go idle. It returns the context error if the deadline expires, otherwise
  the listener-close error. `Serve` and the `ListenAndServe*` functions return
  `ErrServerClosed` immediately, and the program must wait for `Shutdown` to return before
  exiting. `[official]` — [pkg.go.dev/net/http#Server.Shutdown](https://pkg.go.dev/net/http#Server.Shutdown)
- Hijacked connections (WebSockets) are neither closed nor waited on; use
  `RegisterOnShutdown` for those. `[official]` —
  [pkg.go.dev/net/http#Server.Shutdown](https://pkg.go.dev/net/http#Server.Shutdown)
- The documented example uses `signal.Notify` with a `context.Background()`, not
  `signal.NotifyContext`. `NotifyContext` is available and widely used and returns a context
  marked done when a listed signal arrives, but no fetched Go-team page prescribes it for
  shutdown. `[official]` — [pkg.go.dev/net/http#Server.Shutdown](https://pkg.go.dev/net/http#Server.Shutdown),
  `[community]` — [pkg.go.dev/os/signal#NotifyContext](https://pkg.go.dev/os/signal#NotifyContext)

  ```go
  ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
  defer stop()

  go func() {
      if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
          log.Fatalf("listen: %v", err)
      }
  }()

  <-ctx.Done()
  stop()

  shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
  defer cancel()
  if err := srv.Shutdown(shutdownCtx); err != nil {
      log.Fatalf("shutdown: %v", err)
  }
  ```

## Panic recovery

- `net/http` recovers a panic per request: it logs a stack trace and closes the connection
  (HTTP/1) or sends an HTTP/2 `RST_STREAM`. Panicking with the sentinel `http.ErrAbortHandler`
  aborts the response while suppressing the stack-trace log. `[official]` —
  [pkg.go.dev/net/http#Handler](https://pkg.go.dev/net/http#Handler),
  [pkg.go.dev/net/http#ErrAbortHandler](https://pkg.go.dev/net/http#ErrAbortHandler)
- Because the default recovery closes the connection, a custom recovery middleware is used
  when you want to write a 500 and keep serving. That inference is not stated in the docs;
  chi, gin and echo each ship a recovery middleware. Re-panic on values that are not yours.
  `[community]` — [pkg.go.dev/net/http#Handler](https://pkg.go.dev/net/http#Handler),
  [go-chi/chi](https://github.com/go-chi/chi)

## Sources

- [pkg.go.dev/net/http](https://pkg.go.dev/net/http)
- [pkg.go.dev/log/slog](https://pkg.go.dev/log/slog)
- [pkg.go.dev/os/signal](https://pkg.go.dev/os/signal)
- [pkg.go.dev/encoding/json](https://pkg.go.dev/encoding/json)
- [pkg.go.dev/encoding/json/v2](https://pkg.go.dev/encoding/json/v2)
- [pkg.go.dev/encoding/json/jsontext](https://pkg.go.dev/encoding/json/jsontext)
- [Routing enhancements](https://go.dev/blog/routing-enhancements)
- [Go 1.22 release notes](https://go.dev/doc/go1.22)
- [Go 1.27 release notes](https://go.dev/doc/go1.27)
- [go-chi/chi](https://github.com/go-chi/chi)
- [gin-gonic/gin](https://github.com/gin-gonic/gin)
- [labstack/echo](https://github.com/labstack/echo)
- [Go web frameworks in 2026](https://abrarqasim.com/blog/golang-web-frameworks-2026-the-router-i-reach-for-first/)

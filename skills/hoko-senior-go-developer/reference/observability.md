# Observability

What a Go service emits so an operator can tell what it is doing without attaching a
debugger: structured logs with `log/slog`, a request ID that follows the request through
the context, RED and USE metrics, traces with OpenTelemetry, and health and readiness
endpoints. Profiling a service that is already misbehaving is in
[profiling-and-diagnostics.md](profiling-and-diagnostics.md); the request-logging
middleware sketch is in [http-and-api.md](http-and-api.md#middleware).

`log/slog` needs the module's `go` directive at 1.21 or higher. `Request.Pattern`, used for
metric labels below, needs 1.23. `[official]` —
[Go 1.21 release notes](https://go.dev/doc/go1.21),
[Go 1.23 release notes](https://go.dev/doc/go1.23)

## `slog`: handler, levels and attributes

- `slog` splits a `Logger` (the call site API) from a `Handler` (the output format). The
  stdlib ships `TextHandler` (`key=value`) and `JSONHandler`. `[official]` —
  [pkg.go.dev/log/slog](https://pkg.go.dev/log/slog)
- Pick the handler by consumer: `JSONHandler` for a service whose logs are parsed by an
  aggregator, `TextHandler` for a CLI or local development. Choose once in `main` and pass
  the `*slog.Logger` down as a dependency; do not reach for the global logger from library
  code. `[community]` — [Go blog: Structured logging with slog](https://go.dev/blog/slog)
- `slog.SetDefault` sets the default logger and also routes the old `log` package's output
  through its handler, so third-party code that still calls `log.Printf` ends up in the same
  stream. `[official]` — [pkg.go.dev/log/slog](https://pkg.go.dev/log/slog#SetDefault)
- Levels are integers: `Debug` -4, `Info` 0, `Warn` 4, `Error` 8. The handler's
  `HandlerOptions.Level` is the minimum; give it a `*slog.LevelVar` to change the level at
  runtime (a debug endpoint or a signal) without a restart. `[official]` —
  [pkg.go.dev/log/slog](https://pkg.go.dev/log/slog#LevelVar)
- Use levels for the operator's decision, not the author's mood: `Error` means a human or a
  pager should look, `Warn` means degraded but handled, `Info` is the request and lifecycle
  trail, `Debug` is off in production. An expected client failure (a 404, a validation
  error) is `Info` or `Debug` at most, not `Error`. `[community]` —
  [Go blog: Structured logging with slog](https://go.dev/blog/slog)
- Write attributes as key-value pairs, not interpolated into the message. The message stays
  a constant string so it can be grouped and counted, and the variable parts are
  fields. `[official]` — [Go blog: Structured logging with slog](https://go.dev/blog/slog)

  ```go
  log.Info("order placed", "order_id", id, "items", len(items), "total", total)
  log.Error("charge failed", "order_id", id, "err", err)   // not fmt.Sprintf in the message
  ```

- Keys and values passed as alternating arguments are not type-checked: a missing value
  produces a `!BADKEY` attribute. Run `go vet`, whose `slog` analyzer flags the mismatch, or
  use `slog.Attr` constructors (`slog.String`, `slog.Int`, `slog.Any`) through `LogAttrs`,
  which also avoids allocating on the hot path. `[official]` —
  [pkg.go.dev/log/slog](https://pkg.go.dev/log/slog#Logger.LogAttrs),
  [pkg.go.dev/cmd/vet](https://pkg.go.dev/cmd/vet)
- Pass the error itself as an attribute (`"err", err`), not `err.Error()`: the handler
  renders it and a custom handler can still inspect it. Log an error at the layer that
  handles it, once; logging it and also returning it duplicates the line at every layer, see
  [error-handling.md](error-handling.md#service-and-api-boundaries). `[community]` —
  [Go blog: Structured logging with slog](https://go.dev/blog/slog)

## `With`, groups and `LogValuer`

- `Logger.With(args...)` returns a logger that adds those attributes to every record. Build
  a per-request or per-component logger once (`log.With("component", "billing")`) instead of
  repeating the attributes at each call. `[official]` —
  [pkg.go.dev/log/slog](https://pkg.go.dev/log/slog#Logger.With)
- `Logger.WithGroup(name)` and `slog.Group(name, ...)` nest attributes under a key (a
  `request.method` path in text, an object in JSON). Group by subsystem to keep key names
  from colliding across packages. `[official]` —
  [pkg.go.dev/log/slog](https://pkg.go.dev/log/slog#Logger.WithGroup)
- A type implements `slog.LogValuer` (`LogValue() slog.Value`) to control how it is logged.
  Resolution happens in the handler, so the cost is only paid when the record is emitted.
  Return `slog.GroupValue(...)` to log a struct as a set of chosen fields. `[official]` —
  [pkg.go.dev/log/slog](https://pkg.go.dev/log/slog#LogValuer)
- `LogValuer` is the redaction point: put it on the type that holds the secret, so no call
  site can forget. `[official]` for the interface, `[community]` for using it to redact —
  [Go blog: Structured logging with slog](https://go.dev/blog/slog)

  ```go
  type User struct {
      ID    string
      Email string
      Token string
  }

  func (u User) LogValue() slog.Value {
      return slog.GroupValue(
          slog.String("id", u.ID),
          // Email and Token are deliberately left out.
      )
  }

  log.Info("login", "user", u) // logs user.id only
  ```

- `HandlerOptions.ReplaceAttr` rewrites or drops attributes by key as a last line of
  defence (drop `password`, `authorization`, `token`). It is a backstop, not the primary
  control: it only catches keys you thought of. `[official]` —
  [pkg.go.dev/log/slog](https://pkg.go.dev/log/slog#HandlerOptions)

## No secrets or PII in logs

- Never log credentials, tokens, API keys, session identifiers, full payment data, or the
  request and response bodies of an endpoint that carries them. Logs are copied to
  aggregators, laptops and tickets, and outlive the access control on the original data.
  `[community]` — [OWASP Logging Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html)
- Personal data (email, name, address, IP, phone number) is data to be minimised too: log a
  stable opaque ID and look the person up when needed. If a field must be logged, redact or
  hash it in a `LogValuer`. `[community]` —
  [OWASP Logging Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html)
- Do not log the whole `*http.Request`, a whole config struct or a whole database row with
  `%+v` or `slog.Any`: the unlisted field is the one that leaks. Log the fields you chose.
  `[community]` — [OWASP Logging Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html)
- Log the route pattern or a redacted path, not the raw URL, when the query string can carry
  a token. `[community]` — [OWASP Logging Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html)
- Untrusted text in a log line can forge records in a line-oriented format. `JSONHandler`
  escapes values, and `TextHandler` quotes values that contain spaces or control
  characters; hand-built `fmt.Printf` lines do not, which is another reason not to write
  them. `[community]` — [OWASP Logging Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html)

## A request ID through the context

- Carry request-scoped identifiers in `context.Context` values, not in function parameters
  or struct fields: the request ID is the textbook request-scoped value. Use an unexported
  key type so no other package can collide with it, and expose typed accessors. `[official]` —
  [pkg.go.dev/context](https://pkg.go.dev/context#WithValue)
- Set it once, in the outermost middleware: take the inbound `X-Request-ID` only after
  validating its length and character set (otherwise generate one), echo it in the response
  header, and store it in the context. An unvalidated inbound ID is untrusted text that lands
  in every log line. `[community]` —
  [OWASP Logging Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html)
- Handlers do not read the context by themselves. Either build a per-request logger with
  `log.With("request_id", id)` in the middleware and put the logger in the context, or wrap
  the handler so `Handle(ctx, record)` appends the ID from `ctx`, and call the `...Context`
  methods (`log.InfoContext(ctx, ...)`) so the context reaches it. `[official]` —
  [pkg.go.dev/log/slog](https://pkg.go.dev/log/slog#Handler)

  ```go
  type ctxKey struct{}

  func WithRequestID(ctx context.Context, id string) context.Context {
      return context.WithValue(ctx, ctxKey{}, id)
  }

  func RequestID(ctx context.Context) string {
      id, _ := ctx.Value(ctxKey{}).(string)
      return id
  }

  type contextHandler struct{ slog.Handler }

  func (h contextHandler) Handle(ctx context.Context, r slog.Record) error {
      if id := RequestID(ctx); id != "" {
          r.AddAttrs(slog.String("request_id", id))
      }
      return h.Handler.Handle(ctx, r)
  }

  func (h contextHandler) WithAttrs(a []slog.Attr) slog.Handler {
      return contextHandler{h.Handler.WithAttrs(a)}
  }

  func (h contextHandler) WithGroup(name string) slog.Handler {
      return contextHandler{h.Handler.WithGroup(name)}
  }
  ```

  A wrapping handler must forward `WithAttrs` and `WithGroup` and re-wrap the result, or the
  wrapper is lost after the first `With`. `[official]` —
  [slog handler guide](https://github.com/golang/example/blob/master/slog-handler-guide/README.md)
- Pass the same ID on outbound calls (set the header from the context in the client's
  `RoundTripper`) so a request can be followed across services. When tracing is on, the trace
  ID serves this purpose and the request ID is the fallback for services without it.
  `[community]` — [OpenTelemetry context propagation](https://opentelemetry.io/docs/concepts/context-propagation/)

## Metrics: RED and USE

- Instrument a request-serving service with RED: **R**ate (requests per second),
  **E**rrors (failed requests per second) and **D**uration (latency distribution). They
  answer "are users affected". `[community]` —
  [Grafana: The RED Method](https://grafana.com/blog/the-red-method-how-to-instrument-your-services/)
- Instrument each resource (a connection pool, a worker queue, a CPU, a disk) with USE:
  **U**tilization, **S**aturation and **E**rrors. They answer "why". For a Go service the
  saturation signals that matter are queue depth, pool wait time and goroutine count.
  `[community]` — [Brendan Gregg: The USE Method](https://www.brendangregg.com/usemethod.html)
- Record duration as a histogram, not an average: an average hides the tail, and
  percentiles are computed from histogram buckets. Count errors as a counter split by
  outcome. `[community]` —
  [Prometheus: histograms and summaries](https://prometheus.io/docs/practices/histograms/)
- Keep label cardinality bounded. Every distinct label value is a new time series, so label
  by method, status class and route pattern (`r.Pattern`, 1.23+), never by raw path, user ID,
  request ID or error text. `[community]` —
  [Prometheus: instrumentation practices](https://prometheus.io/docs/practices/instrumentation/),
  [pkg.go.dev/net/http](https://pkg.go.dev/net/http#Request)
- The Prometheus Go client (`prometheus/client_golang`) is the common choice: register
  collectors once at start-up, expose `promhttp.Handler()` on the operations listener, and
  use the Go runtime and process collectors it ships for goroutine count, heap and GC
  figures. `[community]` —
  [prometheus/client_golang](https://github.com/prometheus/client_golang)
- Runtime figures are also available in-process through `runtime/metrics`, a stable
  name-based API; use it to read a number, and use the profiler to find out why it moved.
  `[official]` — [pkg.go.dev/runtime/metrics](https://pkg.go.dev/runtime/metrics)
- A metric nobody alerts on or charts is cost without value: add each one for a named
  question, and prefer the few RED and USE series to a long tail of ad hoc counters.
  `[community]` — [Grafana: The RED Method](https://grafana.com/blog/the-red-method-how-to-instrument-your-services/)

## Tracing with OpenTelemetry

- OpenTelemetry (`go.opentelemetry.io/otel`) is the vendor-neutral API and SDK for traces.
  Application code depends on the API (`otel.Tracer("pkg").Start(ctx, "name")`); only `main`
  configures the SDK, exporter and propagator. `[official]` —
  [OpenTelemetry Go](https://opentelemetry.io/docs/languages/go/)
- A span lives in a `context.Context`: `ctx, span := tracer.Start(ctx, "charge")`, then
  `defer span.End()`, and pass the new `ctx` on so child spans nest. Dropping the context
  breaks the trace into unrelated pieces. `[official]` —
  [OpenTelemetry Go: instrumentation](https://opentelemetry.io/docs/languages/go/instrumentation/)
- Record failures with `span.RecordError(err)` and `span.SetStatus(codes.Error, msg)`;
  `RecordError` alone does not mark the span failed. `[official]` —
  [OpenTelemetry Go: instrumentation](https://opentelemetry.io/docs/languages/go/instrumentation/)
- Instrument the edges first, because that is where the time goes and where failures are
  ambiguous: the inbound handler (`otelhttp.NewHandler`), every database call, and every
  outbound HTTP or RPC call (`otelhttp.NewTransport` on the shared client, see
  [http-and-api.md](http-and-api.md#outgoing-requests-response-bodies)). Add spans inside
  business logic only when a trace shows an unexplained gap. `[community]` —
  [OpenTelemetry Go: instrumentation libraries](https://opentelemetry.io/docs/languages/go/libraries/)
- Set a propagator (`otel.SetTextMapPropagator`, W3C `TraceContext` plus `Baggage`) in `main`
  so the trace crosses service boundaries; without one, each service starts its own trace.
  `[official]` — [OpenTelemetry context propagation](https://opentelemetry.io/docs/concepts/context-propagation/)
- Sample, do not trace everything at full rate: a head sampler such as
  `sdktrace.ParentBased(sdktrace.TraceIDRatioBased(0.1))` keeps 10% of new traces and
  honours the caller's decision for the rest, so a trace is whole or absent. Keep errors and
  slow requests with tail sampling in a collector, not in the process. `[official]` —
  [OpenTelemetry: sampling](https://opentelemetry.io/docs/concepts/sampling/)
- The `TracerProvider` batches spans in memory: call its `Shutdown(ctx)` on the way out of
  graceful shutdown, with a bounded context, or the last spans are lost. `[official]` —
  [OpenTelemetry Go: getting started](https://opentelemetry.io/docs/languages/go/getting-started/)
- Correlate logs with traces: read `trace.SpanContextFromContext(ctx)` in the same wrapping
  handler as the request ID and add `trace_id` and `span_id`. `[community]` —
  [OpenTelemetry: logs](https://opentelemetry.io/docs/concepts/signals/logs/)
- Span attributes follow the same rules as log attributes: no secrets or PII, bounded
  cardinality for anything used to group. A SQL statement is fine, its bound values are
  not. `[community]` —
  [OpenTelemetry: semantic conventions](https://opentelemetry.io/docs/specs/semconv/)

## Health and readiness endpoints

- Expose two different questions, on two different paths. **Liveness** (`/healthz`):
  is the process wedged, so should it be restarted? **Readiness** (`/readyz`): can it serve
  traffic now, so should the load balancer send it any? Kubernetes acts on them differently:
  a failing liveness probe restarts the container, a failing readiness probe only removes
  it from the endpoints. `[official]` —
  [Kubernetes: liveness, readiness and startup probes](https://kubernetes.io/docs/concepts/configuration/liveness-readiness-startup-probes/)
- Keep liveness shallow: it returns 200 if the handler runs. A liveness probe that checks
  the database turns a database outage into a restart loop across every replica.
  `[official]` — [Kubernetes: liveness, readiness and startup probes](https://kubernetes.io/docs/concepts/configuration/liveness-readiness-startup-probes/)
- Readiness may check the dependencies the service cannot work without (a database `PingContext`
  with a short timeout), and should not fail for an optional one. Bound every check with a
  deadline and cache the result for a few seconds so a probe storm does not become load.
  `[community]` — [Kubernetes: liveness, readiness and startup probes](https://kubernetes.io/docs/concepts/configuration/liveness-readiness-startup-probes/)
- Flip readiness to failing at the start of shutdown, wait for the load balancer to notice,
  and only then call `Server.Shutdown`, so no new request arrives during the drain. See
  [http-and-api.md](http-and-api.md#graceful-shutdown). `[community]` —
  [Kubernetes: pod termination](https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/#pod-termination)

  ```go
  var ready atomic.Bool

  mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) {
      w.WriteHeader(http.StatusOK)
  })
  mux.HandleFunc("GET /readyz", func(w http.ResponseWriter, r *http.Request) {
      if !ready.Load() {
          http.Error(w, "shutting down", http.StatusServiceUnavailable)
          return
      }
      ctx, cancel := context.WithTimeout(r.Context(), time.Second)
      defer cancel()
      if err := db.PingContext(ctx); err != nil {
          http.Error(w, "database unavailable", http.StatusServiceUnavailable)
          return
      }
      w.WriteHeader(http.StatusOK)
  })

  // on SIGTERM: ready.Store(false); sleep the drain period; srv.Shutdown(ctx)
  ```

- Serve health, metrics and the pprof handlers on an operations listener bound to an
  internal address, not the public one: they expose internals and, for pprof, can be used
  to exhaust the process. Return a status code and a terse body, never the error text or
  the dependency's address. `[community]` —
  [pkg.go.dev/net/http/pprof](https://pkg.go.dev/net/http/pprof)

## Sources

- [pkg.go.dev/log/slog](https://pkg.go.dev/log/slog)
- [Go blog: Structured logging with slog](https://go.dev/blog/slog)
- [slog handler guide](https://github.com/golang/example/blob/master/slog-handler-guide/README.md)
- [pkg.go.dev/context](https://pkg.go.dev/context)
- [pkg.go.dev/runtime/metrics](https://pkg.go.dev/runtime/metrics)
- [pkg.go.dev/net/http/pprof](https://pkg.go.dev/net/http/pprof)
- [Go 1.21 release notes](https://go.dev/doc/go1.21)
- [Go 1.23 release notes](https://go.dev/doc/go1.23)
- [OWASP Logging Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html)
- [Grafana: The RED Method](https://grafana.com/blog/the-red-method-how-to-instrument-your-services/)
- [Brendan Gregg: The USE Method](https://www.brendangregg.com/usemethod.html)
- [Prometheus: instrumentation practices](https://prometheus.io/docs/practices/instrumentation/)
- [Prometheus: histograms and summaries](https://prometheus.io/docs/practices/histograms/)
- [prometheus/client_golang](https://github.com/prometheus/client_golang)
- [OpenTelemetry Go](https://opentelemetry.io/docs/languages/go/)
- [OpenTelemetry: sampling](https://opentelemetry.io/docs/concepts/sampling/)
- [OpenTelemetry context propagation](https://opentelemetry.io/docs/concepts/context-propagation/)
- [Kubernetes: liveness, readiness and startup probes](https://kubernetes.io/docs/concepts/configuration/liveness-readiness-startup-probes/)

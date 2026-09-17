# Concurrency

Coroutines that must be given an exit, contexts that are passed rather than stored, the choice
between channels and the `sync` primitives, and the version-gated facts that decide whether
older advice still applies.

The package docs cited here render at `go1.27.1`. A few long-standing claims in circulation
are now version-stale; each is labelled with what changed.

## Give every goroutine an exit

- "When you spawn goroutines, make it clear when - or whether - they exit." Goroutines leak by
  blocking on a channel send or receive, and the garbage collector will not terminate a
  goroutine even when the channels it blocks on are unreachable. `[official]` —
  [Code Review Comments §Goroutine Lifetimes](https://go.dev/wiki/CodeReviewComments#goroutine-lifetimes)
- "Goroutines are not garbage collected; they must exit on their own." The canonical leak is a
  pipeline stage blocked sending on an unbuffered channel after the downstream consumer
  returned early; the sender can never proceed, and its stack keeps referenced data alive.
  `[official]` — [Go Concurrency Patterns: Pipelines](https://go.dev/blog/pipelines)
- The patterns to avoid: a blocked send with no cancellation, a blocked receive with no
  cancellation, a producer whose consumer abandons it, the pre-1.23 timer leak from
  `time.After` in a loop (no longer a leak on Go 1.23+, see below), and an unbounded
  goroutine-per-item, which Effective Go says "can consume unlimited resources". `[official]` —
  [Go Concurrency Patterns: Pipelines](https://go.dev/blog/pipelines),
  [Effective Go §A leaky buffer](https://go.dev/doc/effective_go#leaky_buffer)
- Fixes: pass a `done`/`ctx` channel and put the send or receive in a `select` with a
  `case <-done:`/`case <-ctx.Done(): return`; `close(done)` broadcasts because a receive on a
  closed channel proceeds immediately; stage functions close their outbound channel when sends
  are done and keep receiving until the inbound channel is closed. `[official]` —
  [Go Concurrency Patterns: Pipelines](https://go.dev/blog/pipelines)
- Use a buffer only when the exact number of values is known at channel creation; using one to
  "fix" blocked goroutines is "bad code" and "fragile". Bound parallelism with a fixed worker
  count or `errgroup.SetLimit`. `[official]` —
  [Go Concurrency Patterns: Pipelines](https://go.dev/blog/pipelines)
- Google adds: do not fire and forget, wait for goroutines to exit (channels, `WaitGroup`,
  `errgroup`), and do not start goroutines in `init()`. `[community]` —
  [Google Go best practices §Goroutine lifetimes](https://google.github.io/styleguide/go/best-practices#goroutine-lifetimes)

## `context.Context`

- Propagate a `Context` down the entire call chain from incoming requests to outgoing calls;
  incoming requests create one and outgoing calls accept one. `[official]` —
  [pkg.go.dev/context](https://pkg.go.dev/context)
- A function that uses a `Context` takes it as the first parameter, named `ctx`:
  `func DoSomething(ctx context.Context, arg Arg) error`. `[official]` —
  [pkg.go.dev/context](https://pkg.go.dev/context)
- Do not store a `Context` in a struct; pass it explicitly to each function that needs it. The
  one stated exception is a method whose signature must match a standard-library or third-party
  interface, as `net/http.Request` carries one for Go 1 compatibility. Prefer duplicating a
  function with a `...Context` suffix over storing a context. `[official]` —
  [Contexts and structs](https://go.dev/blog/context-and-structs),
  [Code Review Comments §Contexts](https://go.dev/wiki/CodeReviewComments#contexts)
- Do not pass a nil `Context` even when a function permits it; pass `context.TODO()` when
  unsure. `[official]` — [pkg.go.dev/context](https://pkg.go.dev/context)
- `context.Background` belongs to `main`, `init`, tests, and the top level of an incoming
  request. This is not a hard "only at the top" rule: "A function that is never request-specific
  may use `context.Background()`, but err on the side of passing a Context even if you think
  you don't need to." `[official]` —
  [Code Review Comments §Contexts](https://go.dev/wiki/CodeReviewComments#contexts)
- Cancelling or expiring a parent cancels every derived context, and an earlier parent deadline
  wins over a later child one. `[official]` — [pkg.go.dev/context](https://pkg.go.dev/context)
- `WithCancel`, `WithDeadline` and `WithTimeout` return a `CancelFunc`; failing to call it
  "leaks the child and its children until the parent is canceled", and `go vet` checks that
  cancel functions are used on all control-flow paths. `defer cancel()` immediately after
  creation is the idiom. `[official]` — [pkg.go.dev/context](https://pkg.go.dev/context)
- Context values are for request-scoped data that crosses processes or APIs, never for optional
  function parameters; use an unexported type for the key to avoid collisions. A context is
  immutable and safe to pass to many goroutines. `[official]` —
  [pkg.go.dev/context](https://pkg.go.dev/context)
- The cause-aware forms are available: `WithCancelCause`/`Cause`, `WithDeadlineCause` and
  `WithTimeoutCause`, `AfterFunc`, and `WithoutCancel`. `[official]` —
  [pkg.go.dev/context](https://pkg.go.dev/context)
- `signal.NotifyContext(parent, signals...)` returns a context marked done when a listed signal
  arrives, `stop()` is called, or the parent is done, plus a `stop` cancel function. Call
  `stop` as soon as the operations complete; it unregisters the signal behaviour and may
  restore the default exit behaviour. From Go 1.26 the context is cancelled with a cause, so
  `context.Cause(ctx)` returns an error naming the signal. `[official]` —
  [pkg.go.dev/os/signal §NotifyContext](https://pkg.go.dev/os/signal#NotifyContext)

  ```go
  ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt)
  defer stop()
  ```

## Channels versus the `sync` primitives

Choose by the job, not by habit; the entries below come from the package documentation.
`[official]` — [pkg.go.dev/sync](https://pkg.go.dev/sync),
[pkg.go.dev/golang.org/x/sync/errgroup](https://pkg.go.dev/golang.org/x/sync/errgroup)

| Tool | Use it for |
| --- | --- |
| channel | communication and ownership transfer between goroutines, pipelines, fan-out/fan-in, signalling completion or cancellation, `select` multiplexing |
| `sync.Mutex` | guarding shared state and invariants; the zero value is an unlocked mutex and may be locked and unlocked by different goroutines |
| `sync.RWMutex` | many readers and one writer; the zero value is usable, it is not recursively read-lockable, and there is no upgrade or downgrade between `RLock` and `Lock` |
| `sync.Once` / `OnceFunc` / `OnceValue` / `OnceValues` | exactly-once initialization; `OnceValue`/`OnceValues` cache a computed result instead of a hand-rolled `Once` plus variable |
| `sync.WaitGroup` | waiting for a set of goroutines; `Add` must happen before `Wait`, and the value must not be copied |
| `sync/atomic` | low-level lock-free primitives, such as preserving a lock-free flag or counter |
| `golang.org/x/sync/errgroup` | a group of goroutines with error propagation and context cancellation |

- Package overview: "Other than the `Once` and `WaitGroup` types, most are intended for use by
  low-level library routines. Higher-level synchronization is better done via channels and
  communication." `[official]` — [pkg.go.dev/sync](https://pkg.go.dev/sync)
- Prefer `wg.Go(f)` (added in Go 1.25) over `Add`, `go` and `defer Done`; the package doc says
  "Callers should prefer WaitGroup.Go". `[official]` — [pkg.go.dev/sync §WaitGroup](https://pkg.go.dev/sync#WaitGroup)

  ```go
  var wg sync.WaitGroup
  for _, item := range items {
      wg.Go(func() { process(item) })
  }
  wg.Wait()
  ```

- `errgroup.WithContext` derives a context cancelled on the first non-nil error or on `Wait`,
  whichever comes first; `Wait` returns the first non-nil error; `SetLimit(n)` bounds active
  goroutines and `TryGo` starts only when under the limit. Use it instead of `WaitGroup` when
  subtasks can fail. `[official]` —
  [pkg.go.dev/golang.org/x/sync/errgroup](https://pkg.go.dev/golang.org/x/sync/errgroup)

## Buffered versus unbuffered

- A channel with absent or zero capacity is unbuffered: a send and receive succeed only when
  both sides are ready. A buffered channel lets a send complete without blocking while the
  buffer is not full, and a receive complete while it is not empty; a nil channel is never
  ready for communication. `[official]` —
  [Go spec §Channel types](https://go.dev/ref/spec#Channel_types)
- Unbuffered channels combine communication with synchronisation, so the exchange guarantees
  both goroutines are in a known state; a buffered channel of known capacity is useful as a
  semaphore to limit throughput. `[official]` —
  [Effective Go §Channels](https://go.dev/doc/effective_go#channels)
- A buffer avoids a blocked goroutine only when the number of values is known at creation time
  (`make(chan int, len(nums))`); choosing a size to paper over missing cancellation is
  "fragile" and breaks as soon as the number of values or the consumer changes. `[official]` —
  [Go Concurrency Patterns: Pipelines](https://go.dev/blog/pipelines)
- The buffer choice is about backpressure: unbuffered makes the rate coupling explicit, a
  buffer hides it. Google's convention is that channels "should usually have a size of one or
  be unbuffered", and any other size is "subject to a high level of scrutiny"; signal channels
  such as the one `signal.Notify` fills conventionally use size one. `[community]` —
  [Google Go best practices §Channel size](https://google.github.io/styleguide/go/best-practices#channel-size)

## `select` and the `time.After` leak

- Among ready communications `select` picks one by uniform pseudo-random selection; with none
  ready it runs `default` if present and otherwise blocks. A `select` with only nil channels
  and no `default` blocks forever. `[official]` —
  [Go spec §Select statements](https://go.dev/ref/spec#Select_statements)
- The cancellation-aware loop is the standard shape and the fix for a blocked send:

  ```go
  for {
      select {
      case <-ctx.Done():
          return ctx.Err()
      case out <- v:
      }
  }
  ```

  `[official]` — [Go Concurrency Patterns: Pipelines](https://go.dev/blog/pipelines)
- Adding `default` makes the `select` non-blocking; an empty `select {}` blocks forever, and a
  bare `for { select {} }` spins. `[official]` —
  [Go spec §Select statements](https://go.dev/ref/spec#Select_statements)

### `time.After` in a loop — the old leak advice is version-stale

- The `time` package documentation used to warn that the underlying timer of `After` would not
  be recovered by the garbage collector until it fired. As of Go 1.23 that changed: "the
  garbage collector can recover unreferenced, unstopped timers. There is no reason to prefer
  NewTimer when After will do." Go 1.23 also made timer and ticker channels unbuffered and made
  unstopped tickers collectable, and the `asynctimerchan` compatibility mode was removed
  permanently in Go 1.27. `[official]` — [pkg.go.dev/time §After](https://pkg.go.dev/time#After),
  [Go 1.23 release notes §Timer changes](https://go.dev/doc/go1.23)
- So for a module on `go 1.23` or later, `time.After` inside a `for`/`select` does not create a
  permanent leak: once the `select` completes, the timer and its channel are unreferenced and
  collectable. Blog posts that still warn about it are repeating pre-1.23 advice. `[official]`
  — [pkg.go.dev/time §After](https://pkg.go.dev/time#After)

  ```go
  for {
      select {
      case <-time.After(time.Second):
          poll()
      case <-ctx.Done():
          return ctx.Err()
      }
  }
  ```

- Residual, and an inference rather than a Go-team rule: a hot loop still allocates and
  schedules a runtime timer per iteration, so if a profile shows timer churn, reuse a
  `time.Timer` with `Reset`/`Stop` or use a `time.Ticker`. `[community]` —
  [pkg.go.dev/time §Timer](https://pkg.go.dev/time#Timer)

## The race detector and `-race` in CI

- With `-race`, the compiler instruments all memory accesses and the runtime reports
  unsynchronised accesses with both conflicting stacks. "It will not issue false positives, so
  take its warnings seriously." `[official]` —
  [Introducing the Go Race Detector](https://go.dev/blog/race-detector)
- It can only find races in code paths that actually execute, so its value depends on test
  coverage and workload; run race-enabled binaries under realistic load, or deploy one
  race-enabled instance in a production pool. It does not find deadlocks, goroutine leaks or
  logic errors, only observed happens-before violations, and it cannot derive the happens-before
  relation for an unsynchronised send plus close. `[official]` —
  [Introducing the Go Race Detector](https://go.dev/blog/race-detector),
  [Data Race Detector](https://go.dev/doc/articles/race_detector)
- Cost and requirements: typically 5–10x memory and 2–20x execution time, cgo enabled, and a C
  compiler on non-Darwin platforms. Under `-race`, allocations for `defer`/`recover` are not
  reclaimed until the goroutine exits, so a long-running goroutine that defers repeatedly can
  grow. `[official]` — [Data Race Detector](https://go.dev/doc/articles/race_detector)
- "Mandatory in CI" is community convention, not a Go-team mandate. The Go team says to run
  tests with the race detector and to use realistic workloads, and the Go project runs it in its
  own continuous build, but no Go-team document requires `go test -race` in every pipeline.
  Treat it as an organisational policy decision. `[community]` —
  [Data Race Detector](https://go.dev/doc/articles/race_detector)

## The Go 1.22 loop-variable change

- Go 1.22 gives each iteration of a `for` loop its own variables: "The long-standing 'for' loop
  gotcha with accidental sharing of loop variables between iterations is now resolved." For a
  range loop the effect is as though the body began with `k := k` and `v := v`; a 3-clause loop
  gets a per-iteration `i := i` with a copy-back at iteration end. `[official]` —
  [Go 1.22 release notes §Changes to the language](https://go.dev/doc/go1.22)
- The change is gated on the module's `go` directive (or a per-file `//go:build` constraint),
  not on the installed toolchain. A module below `go 1.22` keeps the old sharing semantics.
  `[community]` — [LoopvarExperiment](https://go.dev/wiki/LoopvarExperiment)
- For a module on `go 1.22` or later, the defensive copy is unnecessary: `x := x`,
  `kCopy := k`, `go func(v int) { … }(v)`, and the `t.Parallel()` subtest workaround all
  disappear. The wiki's FAQ answers "Does this mean I don't have to write `x := x` in my loops
  anymore?" with "After you update your module to use go1.22 or a later version, yes."
  `[community]` — [LoopvarExperiment](https://go.dev/wiki/LoopvarExperiment)
- `go vet`'s `loopclosure` check no longer reports references to loop variables from function
  literals that might outlive the iteration, for packages that require `go 1.22` or later.
  `[official]` — [Go 1.22 release notes §Vet](https://go.dev/doc/go1.22)
- It does not make every address-taking pattern equivalent. Code that relied on there being a
  single variable per loop, such as keying a map by `&x`, changes behaviour; the wiki gives
  `sum(list []int)` and a function capturing `i` as programs the change breaks. That is the
  intended fix, not a defect. `[community]` —
  [LoopvarExperiment](https://go.dev/wiki/LoopvarExperiment)
- Pre-declared iteration variables are still shared, and the per-iteration change can add an
  allocation where the variable escapes; profile hot loops rather than assuming. `[community]` —
  [LoopvarExperiment](https://go.dev/wiki/LoopvarExperiment)
- Stale examples persist in the wild, including in current `errgroup` docs, so seeing `x := x`
  is not by itself a bug. `[community]` —
  [pkg.go.dev/golang.org/x/sync/errgroup](https://pkg.go.dev/golang.org/x/sync/errgroup)

## The Go 1.27 `goroutineleak` profile

- Go 1.27 makes the goroutine leak profile generally available: a new profile type,
  `goroutineleak`, is supported by `runtime/pprof` and exposed as
  `/debug/pprof/goroutineleak`. The experimental `goroutineleakprofile` `GOEXPERIMENT` is
  deleted. `[official]` — [Go 1.27 release notes §Runtime](https://go.dev/doc/go1.27)
- "A leaked goroutine is a goroutine blocked on some concurrency primitive (channels,
  `sync.Mutex`, `sync.Cond`, etc) that cannot possibly become unblocked." Detection uses GC
  reachability: if a goroutine is blocked on a primitive unreachable from any runnable goroutine
  or from any goroutine those could unblock, it can never wake. `[official]` —
  [Go 1.27 release notes §Runtime](https://go.dev/doc/go1.27)
- It detects the classic early-return pipeline leak well, where a function returns early and the
  blocked-on channel becomes unreachable with unknown numbers of sender goroutines still
  waiting. `[official]` — [Go 1.26 release notes §Runtime](https://go.dev/doc/go1.26)
- Limits: because detection is reachability-based, it may miss leaks blocked on a primitive
  reachable through a global variable or a runnable goroutine's locals, and it reports a leak
  only after the primitive becomes unreachable. `[official]` —
  [Go 1.26 release notes §Runtime](https://go.dev/doc/go1.26)

## "Share memory by communicating" is not a ban on mutexes

- Effective Go's formulation is "Do not communicate by sharing memory; instead, share memory by
  communicating", immediately followed by the caveat: "This approach can be taken too far.
  Reference counts may be best done by putting a mutex around an integer variable." `[official]`
  — [Effective Go §Share by communicating](https://go.dev/doc/effective_go#sharing)
- The `sync` overview makes the same split: the low-level primitives are for low-level library
  routines, and "higher-level synchronization is better done via channels and communication".
  `[official]` — [pkg.go.dev/sync](https://pkg.go.dev/sync)
- The proverb is about ownership transfer: passing a value on a channel arranges that one
  goroutine has it at a time. It does not mean every shared field must be channelled, and
  channels do not remove the need for synchronization reasoning; sending a pointer still shares
  the pointee, and the receiver must not touch it concurrently. Prefer channels when goroutines
  coordinate or exchange, and a mutex when they guard shared state. `[community]` —
  [Share Memory By Communicating](https://go.dev/blog/share-memory-by-communicating)
- Choosing a channel where a mutex fits is the usual failure mode; `sync.Cond` is rarely the
  right choice and channels usually replace it. `[community]` —
  [pkg.go.dev/sync §Cond](https://pkg.go.dev/sync#Cond)

## Sources

- [pkg.go.dev/context](https://pkg.go.dev/context)
- [Contexts and structs](https://go.dev/blog/context-and-structs)
- [pkg.go.dev/sync](https://pkg.go.dev/sync)
- [pkg.go.dev/os/signal](https://pkg.go.dev/os/signal)
- [pkg.go.dev/golang.org/x/sync/errgroup](https://pkg.go.dev/golang.org/x/sync/errgroup)
- [pkg.go.dev/time](https://pkg.go.dev/time)
- [Go Concurrency Patterns: Pipelines](https://go.dev/blog/pipelines)
- [Share Memory By Communicating](https://go.dev/blog/share-memory-by-communicating)
- [Effective Go](https://go.dev/doc/effective_go)
- [The Go Programming Language Specification](https://go.dev/ref/spec)
- [Go Code Review Comments](https://go.dev/wiki/CodeReviewComments)
- [LoopvarExperiment](https://go.dev/wiki/LoopvarExperiment)
- [Introducing the Go Race Detector](https://go.dev/blog/race-detector)
- [Data Race Detector](https://go.dev/doc/articles/race_detector)
- [Go 1.22 release notes](https://go.dev/doc/go1.22)
- [Go 1.23 release notes](https://go.dev/doc/go1.23)
- [Go 1.26 release notes](https://go.dev/doc/go1.26)
- [Go 1.27 release notes](https://go.dev/doc/go1.27)
- [Google Go Style Guide — best practices](https://google.github.io/styleguide/go/best-practices)

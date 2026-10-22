# Profiling and diagnostics

How to find out why a Go program is slow, large or stuck, using the tools the toolchain ships:
the pprof profiles, `go tool trace`, escape analysis, `benchstat`, profile-guided optimization
and the two GC knobs. It closes with how to read a goroutine dump and a triage list for the
three hangs that look alike.

Measure first, change one thing, measure again. A guessed optimisation (a cache, a
`sync.Pool`, a hand-unrolled loop) is the usual wrong answer; the profile names the cost.
`[community]` — [Go Diagnostics](https://go.dev/doc/diagnostics),
[Profiling Go Programs](https://go.dev/blog/pprof)

## Pick the tool by the symptom

| Symptom | First tool | Section |
| --- | --- | --- |
| CPU is high, or a request is slow and the time is spent computing | CPU profile | [Profiles](#profiles) |
| Memory grows, or the GC runs constantly | heap and allocs profiles | [Profiles](#profiles) |
| Latency is high but the CPU is idle | block and mutex profiles, then `go tool trace` | [Profiles](#profiles), [Execution traces](#execution-traces-with-go-tool-trace) |
| The goroutine count only rises | goroutine and `goroutineleak` profiles | [Goroutine leaks](#the-go-127-goroutineleak-profile) |
| The process hangs or stops answering | goroutine dump | [Reading a goroutine dump](#reading-a-goroutine-dump) |
| One function allocates more than expected | `-gcflags=-m`, then a benchmark | [Escape analysis](#escape-analysis-with--gcflags-m) |
| Did my change help? | `benchstat` | [Benchmarks and benchstat](#benchmarks-and-benchstat) |

`[community]` — this routing is the skill's synthesis of the symptom-to-tool mapping in
[Go Diagnostics](https://go.dev/doc/diagnostics).

## Profiles

- The Go diagnostics guide names the profile kinds: **cpu** (where the CPU time goes),
  **heap** (sampled allocations of live memory), **threadcreate**, **goroutine** (stack
  traces of all current goroutines), **block** (where goroutines wait on synchronization
  primitives) and **mutex** (lock contention). `[official]` —
  [Go Diagnostics §Profiling](https://go.dev/doc/diagnostics#profiling)
- `runtime/pprof` also provides **allocs**, which is the heap profile with a different default
  sample index: `heap` defaults to live (in-use) space, `allocs` to all space allocated since
  the program started. Pick the view with `-sample_index=inuse_space`, `inuse_objects`,
  `alloc_space` or `alloc_objects`. `[official]` —
  [pkg.go.dev/runtime/pprof](https://pkg.go.dev/runtime/pprof)
- Use `inuse_*` to find what is holding memory now (a leak or an oversized cache); use
  `alloc_*` to find what churns the GC, because short-lived garbage never shows up as in-use.
  `[community]` — [Profiling Go Programs](https://go.dev/blog/pprof)
- The block and mutex profiles are off by default and record nothing until enabled:
  `runtime.SetBlockProfileRate(rate)` and `runtime.SetMutexProfileFraction(n)`. Enable them in
  the process under investigation, not unconditionally in production. `[official]` —
  [Go Diagnostics §Profiling](https://go.dev/doc/diagnostics#profiling),
  [pkg.go.dev/runtime](https://pkg.go.dev/runtime#SetBlockProfileRate)
- Profilers can distort each other: the diagnostics guide warns that profiling tools may
  interfere, for example that precise memory profiling skews a CPU profile. Collect one kind
  at a time when the numbers matter. `[official]` —
  [Go Diagnostics §Profiling](https://go.dev/doc/diagnostics#profiling)
- From a test or benchmark, `go test -cpuprofile=cpu.out -memprofile=mem.out -blockprofile=block.out -mutexprofile=mutex.out`
  writes the files; combine with `-bench` to profile a benchmark rather than a whole test run.
  `[official]` — [go help testflag](https://pkg.go.dev/cmd/go#hdr-Testing_flags)
- Read a profile with `go tool pprof`: `-top` for the heaviest functions, `-list <func>` for
  per-line cost, `-http=:8080` for the interactive web UI with a flame graph, and
  `-diff_base=old.prof new.prof` to see what a change moved. `[official]` —
  [pkg.go.dev/cmd/pprof](https://pkg.go.dev/cmd/pprof)
- "Flat" is the time spent in the function itself, "cum" includes its callees. Start from the
  highest cumulative entry in your own code and descend; a hot flat entry in the runtime
  (`runtime.mallocgc`, `runtime.gcBgMarkWorker`) means allocation or GC pressure, so switch to
  the allocs profile. `[community]` — [Profiling Go Programs](https://go.dev/blog/pprof)

### `net/http/pprof` on a separate admin port

- Importing `net/http/pprof` for its side effect registers its handlers under `/debug/pprof/`
  on `http.DefaultServeMux`. A service that serves its public API from the default mux then
  publishes its profiles to the public. `[official]` —
  [pkg.go.dev/net/http/pprof](https://pkg.go.dev/net/http/pprof)
- Do not import it for the side effect in a service. Register the handlers on a dedicated mux
  and serve that on a separate listener bound to loopback or an internal interface, so the
  profiles are never reachable on the public port. The profiles expose the command line,
  symbol names and heap contents. `[community]` —
  [pkg.go.dev/net/http/pprof](https://pkg.go.dev/net/http/pprof)

  ```go
  func adminHandler() http.Handler {
      mux := http.NewServeMux()
      mux.HandleFunc("/debug/pprof/", pprof.Index)
      mux.HandleFunc("/debug/pprof/cmdline", pprof.Cmdline)
      mux.HandleFunc("/debug/pprof/profile", pprof.Profile)
      mux.HandleFunc("/debug/pprof/symbol", pprof.Symbol)
      mux.HandleFunc("/debug/pprof/trace", pprof.Trace)
      return mux
  }

  admin := &http.Server{
      Addr:              "127.0.0.1:6060",
      Handler:           adminHandler(),
      ReadHeaderTimeout: 5 * time.Second,
  }
  ```

- The admin server needs the same timeout and shutdown discipline as the public one (see
  [http-and-api.md](http-and-api.md#server-timeouts-and-hardening)), with one exception:
  `/debug/pprof/profile?seconds=30` and `/debug/pprof/trace?seconds=5` run for the requested
  duration, so a `WriteTimeout` shorter than that makes them fail. Leave `WriteTimeout` unset
  on the admin server or set it above the longest capture. `[official]` —
  [net/http/pprof source](https://go.dev/src/net/http/pprof/pprof.go)
- Fetch a profile from a running service with `go tool pprof http://127.0.0.1:6060/debug/pprof/profile?seconds=30`
  (CPU), `.../heap`, `.../allocs`, `.../block`, `.../mutex` or `.../goroutine`. Capture CPU
  and trace profiles while the service is under the load that shows the problem; an idle
  profile is empty. `[official]` — [Go Diagnostics §Profiling](https://go.dev/doc/diagnostics#profiling)
- A command-line tool or batch job has no server; write the profile with
  `pprof.StartCPUProfile(f)` and `defer pprof.StopCPUProfile()`, or
  `pprof.Lookup("heap").WriteTo(f, 0)` after a `runtime.GC()` for an up-to-date heap.
  `[official]` — [pkg.go.dev/runtime/pprof](https://pkg.go.dev/runtime/pprof)

### The Go 1.27 `goroutineleak` profile

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
- It complements the plain `goroutine` profile: a rising count in `goroutine` says something
  accumulates, and `goroutineleak` says which of those goroutines can never resume. The
  rules for giving every goroutine an exit are in
  [concurrency.md](concurrency.md#give-every-goroutine-an-exit). `[community]` —
  [Go 1.27 release notes §Runtime](https://go.dev/doc/go1.27)

## Execution traces with `go tool trace`

- A profile aggregates; an execution trace is a timeline. The Go diagnostics guide says a trace
  is for understanding latency and what goroutines do over time, including how they are
  scheduled and where they block on syscalls, the network, synchronization and the GC, none of
  which a CPU profile shows. Reach for it when a profile says the program is mostly waiting, not computing.
  `[official]` — [Go Diagnostics §Tracing](https://go.dev/doc/diagnostics#tracing),
  [More powerful Go execution traces](https://go.dev/blog/execution-traces-2024)
- Capture it from a test with `go test -trace=trace.out`, from a service with
  `curl -o trace.out 'http://127.0.0.1:6060/debug/pprof/trace?seconds=5'`, or in code with
  `runtime/trace`'s `trace.Start(f)` and `defer trace.Stop()`. Open it with
  `go tool trace trace.out`. Keep captures short, a few seconds. `[official]` —
  [pkg.go.dev/runtime/trace](https://pkg.go.dev/runtime/trace),
  [pkg.go.dev/cmd/trace](https://pkg.go.dev/cmd/trace)
- `go tool trace -pprof=net|sync|syscall|sched trace.out` converts a trace into a pprof-format
  profile of network blocking, synchronization blocking, syscall blocking or scheduler latency,
  which `go tool pprof` then reads. `[official]` —
  [pkg.go.dev/cmd/trace](https://pkg.go.dev/cmd/trace)
- Mark the work you want to see with `trace.NewTask(ctx, name)`, `trace.WithRegion(ctx, name, fn)`
  and `trace.Log`; the viewer groups goroutine activity by task, which turns a trace of a busy
  server into one request's story. `[official]` —
  [pkg.go.dev/runtime/trace](https://pkg.go.dev/runtime/trace)
- Tracing overhead is low enough for short production captures: the Go team reports it dropped
  to about 1 to 2 percent of CPU in recent releases. `[official]` —
  [More powerful Go execution traces](https://go.dev/blog/execution-traces-2024)
- For a failure that is gone before anyone can start a capture, the flight recorder
  (`runtime/trace.FlightRecorder`, Go 1.25) keeps the last moments of the trace in a ring buffer
  in memory, to be written out with `WriteTo` when the program notices the problem, such as a
  request that exceeds its deadline. `[official]` —
  [Flight recorder in Go 1.25](https://go.dev/blog/flight-recorder),
  [pkg.go.dev/runtime/trace §FlightRecorder](https://pkg.go.dev/runtime/trace#FlightRecorder)

## Escape analysis with `-gcflags=-m`

- Whether a value lives on the stack or the heap is the compiler's decision, not the
  programmer's. `go build -gcflags=-m` prints the decisions: `escapes to heap`, `moved to heap: x`,
  `does not escape` and `can inline`; `-m -m` adds the reason. `[official]` —
  [Go FAQ §How do I know whether a variable is allocated on the heap or the stack?](https://go.dev/doc/faq#stack_or_heap),
  [pkg.go.dev/cmd/compile](https://pkg.go.dev/cmd/compile)
- The FAQ's rule: "if the compiler cannot prove that the variable is not referenced after the
  function returns, then the compiler must allocate the variable on the garbage-collected
  heap". Common causes are returning a pointer to a local, storing it in an interface or
  a long-lived structure, capturing it in a closure that outlives the call, and sending it on a
  channel. `[official]` —
  [Go FAQ §stack or heap](https://go.dev/doc/faq#stack_or_heap)
- Use it to explain an allocation the allocs profile or `-benchmem` already showed, never to
  hunt for allocations speculatively: `go build -gcflags='-m' ./path/to/pkg 2>&1 | grep file.go`
  on the one hot package. A heap allocation is not a bug; remove it only where a benchmark
  shows it costs something. `[community]` — [Performance](https://go.dev/wiki/Performance)
- Related, and also profile-driven: preallocate with `make([]T, 0, n)`, avoid converting a
  concrete value to `any` in a hot path, and keep a small struct by value; the aliasing and
  copying traps are in [performance-and-pitfalls.md](performance-and-pitfalls.md). `[community]` —
  [Performance](https://go.dev/wiki/Performance)

## Benchmarks and benchstat

- A single benchmark run is noise. Run each side several times and compare the distributions
  with `benchstat`, which reports the delta only where it is statistically significant and
  prints `~` where it is not. Install it with `go install golang.org/x/perf/cmd/benchstat@latest`.
  `[official]` — [pkg.go.dev/golang.org/x/perf/cmd/benchstat](https://pkg.go.dev/golang.org/x/perf/cmd/benchstat)
- The workflow:

  ```sh
  go test -run='^$' -bench=BenchmarkParse -benchmem -count=10 ./parser > old.txt
  # make exactly one change
  go test -run='^$' -bench=BenchmarkParse -benchmem -count=10 ./parser > new.txt
  benchstat old.txt new.txt
  ```

  `-run='^$'` skips the unit tests, `-benchmem` adds bytes and allocations per operation, and
  `-count=10` gives `benchstat` enough samples to compute a confidence interval; the benchstat
  documentation uses ten. `[official]` —
  [pkg.go.dev/golang.org/x/perf/cmd/benchstat](https://pkg.go.dev/golang.org/x/perf/cmd/benchstat),
  [go help testflag](https://pkg.go.dev/cmd/go#hdr-Testing_flags)
- Run both sides on the same machine, idle, with the same toolchain and power settings; a
  laptop on battery or a noisy CI runner produces differences that are not in the code. If the
  variation inside one side is large, fix the environment before reading the delta.
  `[community]` — [pkg.go.dev/golang.org/x/perf/cmd/benchstat](https://pkg.go.dev/golang.org/x/perf/cmd/benchstat)
- Write the benchmark body with `b.Loop()` where the module is on `go 1.24` or later, so setup
  runs once and the compiler cannot optimise the measured call away; see
  [testing.md](testing.md#benchmarks-and-testingbloop). `[official]` —
  [Go 1.24 release notes](https://go.dev/doc/go1.24)
- Compare across commits by stashing the old numbers in a file, not by remembering them; keep
  the `old.txt`/`new.txt` pair with the change that justified it. A micro-benchmark win that
  a CPU profile of the real workload does not show is not a win. `[community]` —
  [Profiling Go Programs](https://go.dev/blog/pprof)

## Profile-guided optimization

- PGO feeds a CPU profile from a real run back into the compiler, which uses it to inline hot
  call sites more aggressively and to devirtualize hot interface calls. The Go team reports
  gains of a few percent up to low double digits for typical servers. `[official]` —
  [Profile-guided optimization](https://go.dev/doc/pgo)
- A profile named `default.pgo` in the main package's directory is picked up automatically:
  `go build` defaults to `-pgo=auto` (Go 1.21 and later). `-pgo=off` disables it and
  `-pgo=path/to/profile` selects another file. The profile applies to the whole binary, not
  only the main package. `[official]` — [Profile-guided optimization](https://go.dev/doc/pgo)
- Collect the profile from production, not from a benchmark: use the CPU profile from the
  admin endpoint above, under representative load. Merge several with
  `go tool pprof -proto a.pprof b.pprof > merged.pprof`, and commit the result as
  `default.pgo` so every build, local and CI, is reproducible. `[official]` —
  [Profile-guided optimization §Collecting profiles](https://go.dev/doc/pgo)
- Treat the profile as a build input: refresh it periodically, and measure with `benchstat`
  that the PGO build actually helps before keeping it, because PGO increases build time and
  binary size and the gain depends on how representative the profile is. `[official]` —
  [Profile-guided optimization §Frequently Asked Questions](https://go.dev/doc/pgo)

## `GOGC` and `GOMEMLIMIT`

- `GOGC` sets the garbage collector's target heap growth: the default 100 lets the heap reach
  twice the live heap after a collection. A higher value trades memory for less GC CPU; a
  lower one the reverse. `GOGC=off` disables the collector. `[official]` —
  [A Guide to the Go Garbage Collector](https://go.dev/doc/gc-guide)
- `GOMEMLIMIT` (or `debug.SetMemoryLimit`, Go 1.19) sets a soft limit on the memory the Go
  runtime may use, in bytes with an optional `B`, `KiB`, `MiB`, `GiB` or `TiB` suffix. The
  collector works harder as the heap approaches it. The limit is soft: the runtime caps the GC
  at roughly 50 percent of CPU time to avoid a death spiral, so a live heap above the limit
  still grows. `[official]` — [A Guide to the Go Garbage Collector](https://go.dev/doc/gc-guide)
- In a container, set `GOMEMLIMIT` a little under the container's memory limit, leaving room
  for what the limit does not count, such as cgo and mapped memory outside the Go heap; the
  guide suggests leaving 5 to 10 percent of headroom. It is not a substitute for finding a
  leak. `[official]` — [A Guide to the Go Garbage Collector §Suggested uses](https://go.dev/doc/gc-guide)
- `GOGC=off` together with a `GOMEMLIMIT` is only for a program with a known, bounded
  live heap in a dedicated container, where the collector should run only when memory is
  about to run out. Do not combine them for a service whose heap can grow. `[official]` —
  [A Guide to the Go Garbage Collector §Suggested uses](https://go.dev/doc/gc-guide)
- `GODEBUG=gctrace=1` prints one line per collection to stderr (heap before, after and live,
  pause and CPU time), which is the cheapest way to see whether the GC is the problem before
  touching either knob. `[official]` — [pkg.go.dev/runtime §Environment Variables](https://pkg.go.dev/runtime#hdr-Environment_Variables)
- `GOMAXPROCS` defaults to the number of CPUs; since Go 1.25 the runtime also respects a
  container's CPU limit and adjusts as it changes, so the old `automaxprocs` workaround is
  not needed on a module built with Go 1.25 or later. `[official]` —
  [Go 1.25 release notes §Runtime](https://go.dev/doc/go1.25)
- Change one knob at a time and compare with the metrics (`runtime/metrics`) or `gctrace`
  rather than by feel; a tuned setting copied from another service is a guess.
  `[community]` — [A Guide to the Go Garbage Collector](https://go.dev/doc/gc-guide)

## Reading a goroutine dump

- Get one three ways: `kill -QUIT <pid>` (the process prints all goroutine stacks to stderr and
  exits), `curl 'http://127.0.0.1:6060/debug/pprof/goroutine?debug=2'` from a live service
  without stopping it, or `GOTRACEBACK=all` so a crash prints every goroutine instead of only
  the failing one. `debug=1` groups goroutines with identical stacks and a count, which is
  the view for a service with thousands of them. `[official]` —
  [pkg.go.dev/runtime §Environment Variables](https://pkg.go.dev/runtime#hdr-Environment_Variables),
  [pkg.go.dev/net/http/pprof](https://pkg.go.dev/net/http/pprof)
- Each entry starts `goroutine 42 [chan receive, 7 minutes]:`: the goroutine id, its state and,
  once a goroutine has waited a minute or more, how long. Below it the stack runs from the
  blocking call up to the function that started the goroutine, and a final
  `created by main.start in goroutine 1` line names who spawned it. The state is the
  diagnosis. `[official]` — [pkg.go.dev/runtime §Environment Variables](https://pkg.go.dev/runtime#hdr-Environment_Variables)
- The states you will meet:

  | State | Meaning | Usual cause |
  | --- | --- | --- |
  | `running`, `runnable` | on a CPU or waiting for one | CPU-bound work; look at the CPU profile |
  | `chan send`, `chan receive` | blocked on a channel | nobody receives or sends, or nobody closes |
  | `select`, `select (no cases)` | blocked in `select` | no case becomes ready; `select {}` is deliberate |
  | `sync.Mutex.Lock`, `sync.RWMutex.RLock` | waiting for a lock | contention, or a deadlock |
  | `sync.WaitGroup.Wait` | waiting for the counter to reach zero | a missed `Done`, or an `Add` after `Wait` |
  | `IO wait` | parked on the network poller | a peer that never answers; no deadline set |
  | `syscall` | inside a blocking system call | slow disk or a stuck file system |
  | `sleep` | in `time.Sleep` | a retry or poll loop |

  `[community]` — this table is the skill's synthesis of the wait reasons the runtime prints;
  the exact strings vary between releases, so trust the stack over the label.
  [pkg.go.dev/runtime §Environment Variables](https://pkg.go.dev/runtime#hdr-Environment_Variables)
- Read a dump by counting, not scanning: many goroutines with the same state and the same top
  frames is the finding. A thousand goroutines in `chan send` at one line is a leak at that
  line; a hundred in `IO wait` in the same client call is a missing timeout. Then follow
  `created by` to the code that spawns them. `[community]` —
  [Go Diagnostics](https://go.dev/doc/diagnostics)
- The runtime reports `fatal error: all goroutines are asleep - deadlock!` only when every
  goroutine is blocked. In a server something is always alive (the listener, a timer), so a
  deadlocked subset goes unreported and shows up only in a dump. `[community]` — the runtime
  check is `checkdead` in [runtime/proc.go](https://go.dev/src/runtime/proc.go); the
  consequence for servers is this skill's inference.

## Triage list for hangs

Work these in order for a service that has stopped making progress or slowed to a crawl.
`[community]` — the list is this skill's synthesis; each step names the evidence that decides
it.

1. Take a goroutine dump before restarting: a restart destroys the only evidence. Save the
   `debug=2` output and, if the service still answers, a 30-second CPU profile too.
2. **Deadlock.** Evidence: goroutines in `sync.Mutex.Lock`, `chan send` or `chan receive`
   with large wait times, none of them running, and the CPU near idle. Find the cycle: two
   goroutines each holding a lock the other wants, or a goroutine that locks a mutex it
   already holds (Go mutexes are not reentrant). Fix by fixing lock order, narrowing the
   critical section, or never holding a lock across a channel operation or a call out of the
   package. Enable the mutex profile to see contention that is not yet a deadlock.
3. **Goroutine leak.** Evidence: the goroutine count rises with traffic and never falls, and a
   `goroutineleak` or `debug=1` profile shows one stack growing. Fix the missing exit; see
   [concurrency.md](concurrency.md#give-every-goroutine-an-exit).
4. **Thundering herd.** Evidence: a spike in goroutines and in downstream load at the same
   instant, all with the same stack, typically after a cache expiry, a restart or a retry
   storm; and recovery that does not come, because the retries keep the dependency down. Fix
   by collapsing identical in-flight work with `golang.org/x/sync/singleflight`, adding
   jitter to expiry and to retry backoff, and bounding concurrency toward the dependency.
5. **Stuck I/O.** Evidence: goroutines in `IO wait` or `syscall` for minutes, in the same
   client call. The cause is nearly always a missing deadline: an `http.Client` with no
   `Timeout`, a request without a context, a `net.Conn` without `SetDeadline`, or a server
   without `ReadHeaderTimeout`. Fix with timeouts and context propagation; see
   [http-and-api.md](http-and-api.md#server-timeouts-and-hardening).
6. **Not blocked, just busy.** Evidence: goroutines `running` or `runnable`, CPU high. That
   is a CPU profile question, or a GC question: check `gctrace` and the allocs profile.
7. **Only then change code.** Change one thing, reproduce the load, and compare the profile
   or benchmark before and after, as in the workflows above.

## Sources

- [Go Diagnostics](https://go.dev/doc/diagnostics)
- [Profiling Go Programs](https://go.dev/blog/pprof)
- [pkg.go.dev/runtime/pprof](https://pkg.go.dev/runtime/pprof)
- [pkg.go.dev/net/http/pprof](https://pkg.go.dev/net/http/pprof)
- [pkg.go.dev/cmd/pprof](https://pkg.go.dev/cmd/pprof)
- [pkg.go.dev/runtime/trace](https://pkg.go.dev/runtime/trace)
- [pkg.go.dev/cmd/trace](https://pkg.go.dev/cmd/trace)
- [More powerful Go execution traces](https://go.dev/blog/execution-traces-2024)
- [Flight recorder in Go 1.25](https://go.dev/blog/flight-recorder)
- [pkg.go.dev/cmd/compile](https://pkg.go.dev/cmd/compile)
- [pkg.go.dev/golang.org/x/perf/cmd/benchstat](https://pkg.go.dev/golang.org/x/perf/cmd/benchstat)
- [Profile-guided optimization](https://go.dev/doc/pgo)
- [A Guide to the Go Garbage Collector](https://go.dev/doc/gc-guide)
- [pkg.go.dev/runtime](https://pkg.go.dev/runtime)
- [Go FAQ](https://go.dev/doc/faq)
- [runtime/proc.go](https://go.dev/src/runtime/proc.go)
- [net/http/pprof source](https://go.dev/src/net/http/pprof/pprof.go)
- [Performance](https://go.dev/wiki/Performance)
- [Go 1.27 release notes](https://go.dev/doc/go1.27)
- [Go 1.26 release notes](https://go.dev/doc/go1.26)
- [Go 1.25 release notes](https://go.dev/doc/go1.25)
- [Go 1.24 release notes](https://go.dev/doc/go1.24)

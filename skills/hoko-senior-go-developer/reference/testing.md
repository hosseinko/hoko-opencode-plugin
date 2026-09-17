# Testing

How Go tests are organised and run: table-driven subtests, helpers, cleanup and
parallelism, external test packages, test doubles, the standard-library test servers,
fuzzing, benchmarks, examples, golden files, coverage and the fake-clock package.

The standard-library docs cited here render at `go1.27.1`. The version-gated items are
`B.Loop` and `T.Context`/`T.Chdir` and `B.Context` (1.24), `testing/synctest` (1.25) and
`httptest.NewTestServer` (1.27); each applies only when the module's `go` directive is at
least that version. `[official]` — [pkg.go.dev/testing](https://pkg.go.dev/testing)

Go-team authority for testing is the standard-library package docs, the release notes and
the `cmd/go` docs. The `go.dev/wiki` testing pages are community supplements and the Google
Go style guide is Google-internal. Golden files, the `-update` convention, coverage as a
floor and the choice of mock generator are community convention; each is labelled that way
below. `[community]` — [go.dev/wiki/TestComments](https://go.dev/wiki/TestComments),
[Google Go style guide §Decisions](https://google.github.io/styleguide/go/decisions)

## Table-driven tests and subtests

- Table-driven tests with `t.Run` are the idiomatic shape for many cases that share
  assertions; the Go team's *Testing Techniques* talk presents them first, and the `testing`
  package names them as the motivating use of `Run`. `[official]` —
  [Testing Techniques](https://go.dev/talks/2014/testing.slide),
  [pkg.go.dev/testing](https://pkg.go.dev/testing)
- `Run` gives each case a slash-joined name, so `go test -run 'TestFoo/case'` selects one
  case. `Run` blocks until the subtest returns or calls `t.Parallel`, and does not return
  until parallel subtests have completed, which is how a group subtest cleans up after its
  parallel children. `[official]` — [pkg.go.dev/testing](https://pkg.go.dev/testing)
- Stop using one table when cases need different logic. The wiki says to write multiple test
  functions "when some test cases need to be checked using different logic", and the Google
  style guide says table tests should not be used when subtests need complex or conditional
  logic. `[community]` — [go.dev/wiki/TestComments](https://go.dev/wiki/TestComments),
  [Google Go style guide §Decisions](https://google.github.io/styleguide/go/decisions)
- Since the loop variable is per-iteration from Go 1.22, the old `test := test` copy before
  `t.Run` is inert on a module whose `go` directive is 1.22 or higher. `[official]` —
  [Go 1.22 release notes](https://go.dev/doc/go1.22)

  ```go
  func TestAdd(t *testing.T) {
      tests := []struct {
          name string
          a, b int
          want int
      }{
          {"positive", 1, 2, 3},
          {"zero", 0, 0, 0},
      }
      for _, tt := range tests {
          t.Run(tt.name, func(t *testing.T) {
              if got := Add(tt.a, tt.b); got != tt.want {
                  t.Errorf("Add(%d, %d) = %d, want %d", tt.a, tt.b, got, tt.want)
              }
          })
      }
  }
  ```

## Helpers, cleanup, parallelism, environment

- `t.Helper` marks the calling function as a test helper so a failure is attributed to the
  caller's file and line. It may be called concurrently. Do not build an assertion library
  out of it; the wiki's "Assert Libraries" section advises against assertion helpers that
  hide the test's logic. `[official]` — [pkg.go.dev/testing](https://pkg.go.dev/testing),
  `[community]` — [go.dev/wiki/TestComments](https://go.dev/wiki/TestComments)
- `t.Cleanup` runs when the test and all its subtests complete, in last-added-first-called
  order, and therefore runs after parallel subtests finish. A `defer` in the test body fires
  when the body returns. Reach for `t.Cleanup` when teardown must survive parallel children;
  `defer` is fine for a body-local resource. `[official]` —
  [pkg.go.dev/testing](https://pkg.go.dev/testing)
- The "prefer `t.Cleanup` over `defer` with `t.Parallel`" rule is community lint
  (golangci-lint's `tparallel`), not a sentence in the `testing` docs, though it follows
  from the documented ordering. `[community]` —
  [golangci-lint linters](https://golangci-lint.run/docs/linters/),
  [pkg.go.dev/testing](https://pkg.go.dev/testing)
- `t.Parallel` marks a test to run in parallel with other parallel tests and pauses it until
  the non-parallel tests have finished. It does not give each test its own process, so
  shared globals and mutated package state still race. `[official]` —
  [pkg.go.dev/testing](https://pkg.go.dev/testing)
- `t.Setenv` and `t.Chdir` cannot be used in parallel tests or tests with parallel
  ancestors, because both mutate process-wide state. `[official]` —
  [pkg.go.dev/testing](https://pkg.go.dev/testing)
- `t.TempDir` returns a unique directory, removed when the test and all subtests complete,
  fails the test if creation fails, and honors `GOTMPDIR`. `[official]` —
  [pkg.go.dev/testing](https://pkg.go.dev/testing)
- `T.Context` and `B.Context` (Go 1.24) return a context cancelled just before the
  `Cleanup` functions are called. Prefer it to `context.Background()` in tests.
  `[official]` — [pkg.go.dev/testing](https://pkg.go.dev/testing),
  [Go 1.24 release notes](https://go.dev/doc/go1.24); the preference for `Context()` is
  Google style `[community]` —
  [Google Go style guide §Decisions](https://google.github.io/styleguide/go/decisions)
- `T.Chdir` (Go 1.24) changes the working directory for the test and restores it through
  `Cleanup`; it cannot be used in parallel tests. `[official]` —
  [pkg.go.dev/testing](https://pkg.go.dev/testing)

## External test packages and layout

- A test file in `package foo_test` is a black-box test: it may use only the exported API and
  must import the package under test. A file in `package foo` is an internal test and can
  reach unexported identifiers. `[official]` — [pkg.go.dev/testing](https://pkg.go.dev/testing)
- The reason to go external is to break an import cycle. `testing` imports `fmt`, so `fmt`'s
  tests must live in `fmt_test`. `[official]` —
  [Testing Techniques](https://go.dev/talks/2014/testing.slide)
- Files ending in `_test.go` are excluded from normal builds and included by `go test`.
  `[official]` — [pkg.go.dev/cmd/go](https://pkg.go.dev/cmd/go)
- `testdata/` is reserved: the go tool ignores it, `./...` skips it, and it holds test
  fixtures. Fuzz seeds and regression inputs live under `testdata/fuzz/<Name>`.
  `[official]` — [pkg.go.dev/cmd/go](https://pkg.go.dev/cmd/go)

## Test doubles: fakes versus generated mocks — contested

The Go-team position is to avoid doubles by depending on narrow interfaces. The only direct
statement is Andrew Gerrand's: "Go eschews mocks and fakes in favor of writing code that
takes broad interfaces." The example replaces a function taking `*os.File` with one taking
`io.Reader`, because `*os.File`, `bytes.Buffer` and `strings.Reader` all satisfy it.
`[official]` — [Testing Techniques](https://go.dev/talks/2014/testing.slide)

The standard library itself uses hand-written fakes rather than a mock framework:
`httptest.ResponseRecorder`, `net.Pipe`, `testing/fstest.MapFS`. `[official]` —
[pkg.go.dev/testing/fstest](https://pkg.go.dev/testing/fstest)

Generated mocks exist because wide interfaces make hand-writing every method boilerplate.
The community options: `stretchr/testify/mock` (`v1.12.1`), `go.uber.org/mock/gomock`
(`v0.6.0`, with `mockgen`), `vektra/mockery` (v3, generates testify mocks), and
`maxbrunsfeld/counterfeiter/v6` (`v6.12.2`, self-contained type-safe doubles).
`[community]` — [testify/mock](https://pkg.go.dev/github.com/stretchr/testify/mock),
[gomock](https://pkg.go.dev/go.uber.org/mock/gomock),
[mockery](https://github.com/vektra/mockery),
[counterfeiter](https://pkg.go.dev/github.com/maxbrunsfeld/counterfeiter/v6)

**This skill takes hand-written fakes by default.** testify `assert`/`require` are accepted;
`testify/mock` and mockery are reserved for wide generated surfaces (a large SDK or gRPC
interface) where hand-writing every method is worse than the codegen. That threshold is
community judgment, not a Go-team rule. Generated doubles also earn their place for strict
call-order, argument and call-count verification, and for third-party interfaces you cannot
narrow. `[contested]` —
[Testing Techniques](https://go.dev/talks/2014/testing.slide),
[gomock](https://pkg.go.dev/go.uber.org/mock/gomock)

The FAQ's rejection of assertion libraries and third-party test frameworks is a separate
Go-team position: it is about mini-languages, not about test doubles.
`[official]` — [FAQ §Testing framework](https://go.dev/doc/faq#testing_framework),
[FAQ §Assertions](https://go.dev/doc/faq#assertions)

## `httptest`

- `NewServer(handler)` starts a loopback server the test must `Close`; `NewTLSServer` is the
  TLS variant; `NewUnstartedServer` defers `Start` so the server can be configured first.
  `Server.Client()` returns a client that trusts the test certificate and closes idle
  connections on `Close`. `[official]` —
  [pkg.go.dev/net/http/httptest](https://pkg.go.dev/net/http/httptest)
- `NewRecorder` returns a `*ResponseRecorder` implementing `http.ResponseWriter`; inspect
  `Code`/`Body`, or call `Result()`. Call `Result()` only after the handler returns, and do
  not `DeepEqual` the whole response. `[official]` —
  [pkg.go.dev/net/http/httptest](https://pkg.go.dev/net/http/httptest)
- Go 1.27 adds `NewTestServer(t, handler)`, which runs on an in-memory fake network, fails
  the test if the handler panics (except with `ErrAbortHandler`), and registers `Close` via
  `Cleanup`. It is suitable for `testing/synctest`, and the docs now say most tests should
  create a server with it and that most users should prefer it to `NewServer`. Its client
  diverts all HTTP and HTTPS requests to the server regardless of host, so `server.URL` is
  not needed. `[official]` —
  [pkg.go.dev/net/http/httptest](https://pkg.go.dev/net/http/httptest)

  ```go
  func TestHandler(t *testing.T) {
      srv := httptest.NewTestServer(t, NewMux())
      res, err := srv.Client().Get("http://example.com/items/42")
      if err != nil {
          t.Fatal(err)
      }
      defer res.Body.Close()
      // ...
  }
  ```

## Fuzzing

- A fuzz target is `FuzzXxx(f *testing.F)` in a `_test.go` file. Call `f.Add` to seed and
  `f.Fuzz(func(t *testing.T, ...))` for the body. `go test` without `-fuzz` runs only the
  seed corpus and any regressions under `testdata/fuzz/<Name>`; `go test -fuzz=FuzzXxx`
  mutates seeds under coverage instrumentation and writes new failures to that directory.
  `[official]` — [pkg.go.dev/testing](https://pkg.go.dev/testing)
- `-fuzztime` bounds a fuzz run. Without it, fuzzing runs until it finds a failing input or
  forever; the tutorial's bounded example is `go test -fuzz=FuzzXxx -fuzztime 30s`.
  `-parallel` caps the number of workers. Coverage instrumentation is available only on
  amd64 and arm64. `[official]` — [Fuzzing tutorial](https://go.dev/doc/tutorial/fuzz)
- Run fuzzing in CI as a bounded `-fuzztime` job rather than an unbounded one. No Go-team
  page prescribes a duration or a CI policy; this is the skill's recommendation on top of
  the documented `-fuzztime` flag. `[community]` —
  [Fuzzing tutorial](https://go.dev/doc/tutorial/fuzz)
- Native fuzzing shipped in Go 1.18; the June 2021 announcement was the beta on tip.
  `[official]` — [Fuzzing is beta ready](https://go.dev/blog/fuzz-beta)

## Benchmarks and `testing.B.Loop`

- `B.Loop` (Go 1.24) returns true while the benchmark should run: `for b.Loop() { ... }`. It
  resets the timer on the first call and stops it when it returns false, so setup before the
  loop and cleanup after it are not measured. `[official]` —
  [pkg.go.dev/testing](https://pkg.go.dev/testing)
- The 1.24 release notes give the two reasons it replaces `for i := 0; i < b.N; i++`: the
  benchmark function executes exactly once per `-count` so expensive setup runs once, and
  call parameters and results are kept alive so the compiler cannot optimize away the loop
  body. `[official]` — [Go 1.24 release notes](https://go.dev/doc/go1.24)
- The package docs say new benchmarks should prefer `B.Loop`; `B.RunParallel` remains for
  parallel throughput benchmarks. `[official]` — [pkg.go.dev/testing](https://pkg.go.dev/testing)

## Testable examples

- An `Example` function with a concluding `// Output:` comment is compiled and its stdout
  compared, ignoring leading and trailing space; `// Unordered output:` matches any line
  order. An example without an output comment is compiled but not executed. Names encode
  scope: `Example`, `ExampleF`, `ExampleT`, `ExampleT_M`, with an optional lower-case
  suffix. `[official]` — [pkg.go.dev/testing](https://pkg.go.dev/testing)

## Golden files and `-update`

- There is no `-update` flag in `go test` itself and no Go-team guidance for golden files.
  The convention is that the package registers its own `flag.Bool("update", ...)` and, when
  true, rewrites the expected output under `testdata/`, which the go tool ignores.
  `[community]` — [gotest.tools/v3/golden](https://pkg.go.dev/gotest.tools/v3/golden),
  [goldie](https://pkg.go.dev/github.com/sebdah/goldie),
  [tenntenn/golden](https://pkg.go.dev/github.com/tenntenn/golden)
- The one Go-team-guaranteed part is that `testdata/` is invisible to the go tool.
  `[official]` — [pkg.go.dev/cmd/go](https://pkg.go.dev/cmd/go)

  ```go
  var update = flag.Bool("update", false, "rewrite golden files")

  func TestRender(t *testing.T) {
      got := Render(input)
      golden := filepath.Join("testdata", "render.golden")
      if *update {
          if err := os.WriteFile(golden, got, 0o644); err != nil {
              t.Fatal(err)
          }
      }
      want, err := os.ReadFile(golden)
      if err != nil {
          t.Fatal(err)
      }
      if !bytes.Equal(got, want) {
          t.Errorf("Render mismatch; run go test -update to refresh")
      }
  }
  ```

## Coverage

- `go test -coverprofile=cover.out` also enables coverage. `-covermode` is `set` by default,
  or `atomic` when `-race` is on (atomic is significantly more expensive); `count` counts
  executions. `go tool cover -func=cover.out` prints per-function percentages and `-html`
  annotates the source. `[official]` — [pkg.go.dev/cmd/go](https://pkg.go.dev/cmd/go)
- Coverage is statement and basic-block level, not branch or condition level. Rob Pike's
  *The cover story* is explicit that it is inexact: `f() && g()` cannot be counted
  separately and closing braces are attributed confusingly. `go test -cover` reports
  "coverage: N% of statements". `[official]` — [The cover story](https://go.dev/blog/cover)
- **A coverage percentage is a floor, not a target.** It records that a statement executed,
  not that any assertion checked it, so an uncovered behaviour is a fact while a covered one
  proves nothing. No Go-team document sets a target; this reading is an engineering
  conclusion from the mechanics above, not a Go-team rule. `[community]` —
  [The cover story](https://go.dev/blog/cover)

## `testing/synctest`

- `testing/synctest` reached general availability in Go 1.25 after the 1.24 `GOEXPERIMENT`.
  `synctest.Test(t, func(t *testing.T) { ... })` runs goroutines in an isolated bubble with
  a fake clock that advances only when every goroutine in the bubble is durably blocked;
  `synctest.Wait()` blocks until all other bubble goroutines are durably blocked.
  `[official]` — [pkg.go.dev/testing/synctest](https://pkg.go.dev/testing/synctest),
  [Go 1.25 release notes](https://go.dev/doc/go1.25)
- Goroutines blocked on real I/O, syscalls or external channels are not durably blocked, so
  a bubble test must avoid the real network and use a fake. `[official]` —
  [pkg.go.dev/testing/synctest](https://pkg.go.dev/testing/synctest)
- Inside `synctest.Test`, the provided `*testing.T` must not have `T.Run`, `T.Parallel` or
  `T.Deadline` called. `T.Cleanup` runs inside the bubble and `T.Context` is tied to it.
  `[official]` — [pkg.go.dev/testing/synctest](https://pkg.go.dev/testing/synctest)
- Go 1.27 adds `synctest.Sleep(d)`, exactly `time.Sleep(d)` followed by `synctest.Wait()`,
  so a test that sleeps the same duration as the code under test does not race it. Pair it
  with `httptest.NewTestServer` for HTTP code under a bubble. `[official]` —
  [Go 1.27 release notes](https://go.dev/doc/go1.27)

## Sources

- [pkg.go.dev/testing](https://pkg.go.dev/testing)
- [pkg.go.dev/testing/synctest](https://pkg.go.dev/testing/synctest)
- [pkg.go.dev/testing/fstest](https://pkg.go.dev/testing/fstest)
- [pkg.go.dev/net/http/httptest](https://pkg.go.dev/net/http/httptest)
- [pkg.go.dev/cmd/go](https://pkg.go.dev/cmd/go)
- [Go 1.22 release notes](https://go.dev/doc/go1.22)
- [Go 1.24 release notes](https://go.dev/doc/go1.24)
- [Go 1.25 release notes](https://go.dev/doc/go1.25)
- [Go 1.27 release notes](https://go.dev/doc/go1.27)
- [Andrew Gerrand, Testing Techniques](https://go.dev/talks/2014/testing.slide)
- [Fuzzing tutorial](https://go.dev/doc/tutorial/fuzz)
- [Fuzzing is beta ready](https://go.dev/blog/fuzz-beta)
- [The cover story](https://go.dev/blog/cover)
- [Go FAQ §Testing framework](https://go.dev/doc/faq#testing_framework)
- [Go FAQ §Assertions](https://go.dev/doc/faq#assertions)
- [go.dev/wiki/TestComments](https://go.dev/wiki/TestComments)
- [Google Go style guide — decisions](https://google.github.io/styleguide/go/decisions)
- [gotest.tools/v3/golden](https://pkg.go.dev/gotest.tools/v3/golden)
- [goldie](https://pkg.go.dev/github.com/sebdah/goldie)
- [tenntenn/golden](https://pkg.go.dev/github.com/tenntenn/golden)
- [stretchr/testify/mock](https://pkg.go.dev/github.com/stretchr/testify/mock)
- [go.uber.org/mock/gomock](https://pkg.go.dev/go.uber.org/mock/gomock)
- [vektra/mockery](https://github.com/vektra/mockery)
- [counterfeiter/v6](https://pkg.go.dev/github.com/maxbrunsfeld/counterfeiter/v6)

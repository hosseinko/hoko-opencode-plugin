# Modern idioms

A catalogue of the idioms to write, keyed by the Go version that introduced them, so new code
does not fall back to the older pattern that dominates training data.

Models lean on the older form for two reasons: features newer than their training data are
unknown to them, and the older pattern is simply more frequent in what they learned (more
`for i := 0; i < n; i++` than `for i := range n`). The tables below name the old shape, the
modern replacement and the version it needs. `[community]` —
[JetBrains go-modern-guidelines README](https://github.com/JetBrains/go-modern-guidelines#motivation)

## How to use the catalogue

- Read the module's `go` directive first (see [current-go.md](current-go.md#version-gated-behaviour)).
  Apply a row only when its **Min version** is at or below the directive; a row above it
  stays unused, because the directive is what the module promises its consumers and its CI
  toolchain. `[official]` —
  [Go release notes](https://go.dev/doc/devel/release)
- **Covered by `go fix`** says whether the Go team's modernizers can rewrite the old shape
  for you (see [tooling-and-ci.md](tooling-and-ci.md#go-fix-modernizers)). `yes` means a
  mechanical rewrite exists, so run `go fix` and review the diff; `no` means write the modern
  form by hand. A `yes` still depends on the toolchain carrying the analyzer, which the
  cells note where a specific release matters. `[official]` —
  [Go 1.26 release notes](https://go.dev/doc/go1.26),
  [Go 1.27 release notes](https://go.dev/doc/go1.27)
- Each row carries two citations: the release notes that introduced the API `[official]`, and
  the JetBrains guideline that recommends it as the idiom to write `[community]`.
- Some rows are not mechanical: the notes after the tables list the cases where the modern
  form changes behaviour or is the wrong choice. Read them before applying a row.

## The catalogue

### Before 1.18

Available on every supported module; still the most common thing to get wrong.

| Old | Modern | Min version | Covered by `go fix` | Source |
| --- | --- | --- | --- | --- |
| `err == target` | `errors.Is(err, target)` | 1.13 | no | `[official]` [1.13 notes](https://go.dev/doc/go1.13#error_wrapping) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#errors_is) |
| `deadline.Sub(time.Now())` | `time.Until(deadline)` | 1.8 | no | `[official]` [1.8 notes](https://go.dev/doc/go1.8) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#time_until) |
| `time.Now().Sub(start)` | `time.Since(start)` | 1.0 | no | `[official]` [pkg.go.dev/time](https://pkg.go.dev/time#Since) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#time_since) |

### Go 1.18

| Old | Modern | Min version | Covered by `go fix` | Source |
| --- | --- | --- | --- | --- |
| `interface{}` | `any` | 1.18 | yes | `[official]` [1.18 notes](https://go.dev/doc/go1.18) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#any) |
| `strings.Index` plus manual slicing | `before, after, found := strings.Cut(s, sep)` | 1.18 | yes | `[official]` [1.18 notes](https://go.dev/doc/go1.18) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#strings_cut) |
| `bytes.Index` plus manual slicing | `before, after, found := bytes.Cut(b, sep)` | 1.18 | yes | `[official]` [1.18 notes](https://go.dev/doc/go1.18) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#bytes_cut) |
| `string([]byte(s))` to detach a substring from a large backing string | `strings.Clone(s)` | 1.18 | no | `[official]` [1.18 notes](https://go.dev/doc/go1.18) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#strings_clone) |

### Go 1.19

| Old | Modern | Min version | Covered by `go fix` | Source |
| --- | --- | --- | --- | --- |
| `atomic.LoadInt32(&x)`, `atomic.StoreInt32(&x, 1)` on a raw field | `atomic.Bool`, `atomic.Int64`, `atomic.Pointer[T]` and their methods | 1.19 | yes, from the 1.27 toolchain (`atomictypes`) | `[official]` [1.19 notes](https://go.dev/doc/go1.19) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#atomic_types) |
| `append(buf, []byte(fmt.Sprintf(...))...)` | `fmt.Appendf(buf, ...)` | 1.19 | yes on 1.26 only: the `fmtappendf` analyzer was removed in 1.27 | `[official]` [1.19 notes](https://go.dev/doc/go1.19) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#fmt_appendf) |

### Go 1.20

| Old | Modern | Min version | Covered by `go fix` | Source |
| --- | --- | --- | --- | --- |
| `strings.HasPrefix` then `strings.TrimPrefix` (and the suffix pair) | `rest, ok := strings.CutPrefix(s, p)`, `strings.CutSuffix` | 1.20 | yes | `[official]` [1.20 notes](https://go.dev/doc/go1.20) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#strings_cut_prefix_suffix) |
| `append([]byte(nil), b...)` | `bytes.Clone(b)` | 1.20 | yes | `[official]` [1.20 notes](https://go.dev/doc/go1.20) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#bytes_clone) |
| `fmt.Errorf("%v; %w", e1, e2)` or a hand-rolled multi-error type | `errors.Join(e1, e2)` | 1.20 | no | `[official]` [1.20 notes](https://go.dev/doc/go1.20) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#errors_join) |
| `context.WithCancel` when callers need the reason | `context.WithCancelCause`, read with `context.Cause(ctx)` | 1.20 | no | `[official]` [1.20 notes](https://go.dev/doc/go1.20) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#context_cancel_cause) |

### Go 1.21

| Old | Modern | Min version | Covered by `go fix` | Source |
| --- | --- | --- | --- | --- |
| `if b > a { a = b }` | `a = max(a, b)`, `min(a, b)` | 1.21 | yes | `[official]` [1.21 notes](https://go.dev/doc/go1.21) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#min_max) |
| `for k := range m { delete(m, k) }` | `clear(m)`; `clear(s)` zeroes a slice | 1.21 | no | `[official]` [1.21 notes](https://go.dev/doc/go1.21) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#clear) |
| A search loop that only sets `found` | `slices.Contains(items, x)` | 1.21 | yes | `[official]` [1.21 notes](https://go.dev/doc/go1.21) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#slices_contains) |
| A search loop that only records an index | `slices.Index(items, x)` | 1.21 | no | `[official]` [1.21 notes](https://go.dev/doc/go1.21) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#slices_index) |
| A predicate search loop for an index | `slices.IndexFunc(items, pred)` | 1.21 | no | `[official]` [1.21 notes](https://go.dev/doc/go1.21) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#slices_index_func) |
| `sort.Slice(s, func(i, j int) bool {...})` | `slices.SortFunc(s, func(a, b T) int { return cmp.Compare(a.X, b.X) })`; `sort.SliceStable` becomes `slices.SortStableFunc` | 1.21 | no | `[official]` [1.21 notes](https://go.dev/doc/go1.21) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#slices_sort_func) |
| `sort.Ints(v)`, `sort.Strings(v)` | `slices.Sort(v)` | 1.21 | yes | `[official]` [1.21 notes](https://go.dev/doc/go1.21) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#slices_sort) |
| A max or min scan loop over ordered values | `slices.Max(v)`, `slices.Min(v)` | 1.21 | no | `[official]` [1.21 notes](https://go.dev/doc/go1.21) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#slices_max_min) |
| A swap loop over `i, j` | `slices.Reverse(s)` | 1.21 | no | `[official]` [1.21 notes](https://go.dev/doc/go1.21) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#slices_reverse) |
| A loop dropping consecutive duplicates | `slices.Compact(s)` | 1.21 | no | `[official]` [1.21 notes](https://go.dev/doc/go1.21) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#slices_compact) |
| `s[:len(s):len(s)]` | `slices.Clip(s)` | 1.21 | yes | `[official]` [1.21 notes](https://go.dev/doc/go1.21) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#slices_clip) |
| `append([]T(nil), s...)` | `slices.Clone(s)` | 1.21 | yes | `[official]` [1.21 notes](https://go.dev/doc/go1.21) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#slices_clone) |
| `make` plus a copy loop over a map | `maps.Clone(m)` | 1.21 | no | `[official]` [1.21 notes](https://go.dev/doc/go1.21) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#maps_clone) |
| A loop that only assigns `dst[k] = v` | `maps.Copy(dst, src)` | 1.21 | yes | `[official]` [1.21 notes](https://go.dev/doc/go1.21) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#maps_copy) |
| A loop deleting map entries that match a condition | `maps.DeleteFunc(m, pred)` | 1.21 | no | `[official]` [1.21 notes](https://go.dev/doc/go1.21) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#maps_delete_func) |
| `sync.Once` plus a wrapper closure | `sync.OnceFunc(f)` | 1.21 | no | `[official]` [1.21 notes](https://go.dev/doc/go1.21) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#sync_once_func) |
| `sync.Once` plus a result variable and getter | `sync.OnceValue(f)`, `sync.OnceValues(f)` | 1.21 | no | `[official]` [1.21 notes](https://go.dev/doc/go1.21) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#sync_once_value) |
| `go func() { <-ctx.Done(); cleanup() }()` | `stop := context.AfterFunc(ctx, cleanup)` | 1.21 | no | `[official]` [1.21 notes](https://go.dev/doc/go1.21) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#context_after_func) |
| `context.WithTimeout` when callers need the reason | `context.WithTimeoutCause`, `context.WithDeadlineCause` | 1.21 | no | `[official]` [1.21 notes](https://go.dev/doc/go1.21) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#context_timeout_deadline_cause) |

### Go 1.22

| Old | Modern | Min version | Covered by `go fix` | Source |
| --- | --- | --- | --- | --- |
| `for i := 0; i < n; i++` | `for i := range n` | 1.22 | yes | `[official]` [1.22 notes](https://go.dev/doc/go1.22) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#range_over_int) |
| `item := item` before a closure, goroutine or `&item` | no copy; each iteration has its own variable | 1.22 | yes | `[official]` [1.22 notes](https://go.dev/doc/go1.22) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#loopvar_capture) |
| `if v == "" { v = def }` fallback chains | `cmp.Or(a, b, def)` | 1.22 | no | `[official]` [1.22 notes](https://go.dev/doc/go1.22) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#cmp_or) |
| `reflect.TypeOf((*T)(nil)).Elem()` | `reflect.TypeFor[T]()` | 1.22 | yes | `[official]` [1.22 notes](https://go.dev/doc/go1.22) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#reflect_type_for) |
| `mux.HandleFunc("/api/", ...)` with a method check and `strings.TrimPrefix` | `mux.HandleFunc("GET /api/{id}", ...)` and `r.PathValue("id")` | 1.22 | no | `[official]` [1.22 notes](https://go.dev/doc/go1.22) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#http_servemux_patterns) |

### Go 1.23

| Old | Modern | Min version | Covered by `go fix` | Source |
| --- | --- | --- | --- | --- |
| `for k := range m` when the key sequence is passed on | `maps.Keys(m)`, `maps.Values(m)` as iterators | 1.23 | no | `[official]` [1.23 notes](https://go.dev/doc/go1.23) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#maps_keys_values_iter) |
| `make` plus an append loop over a sequence | `slices.Collect(seq)` | 1.23 | no | `[official]` [1.23 notes](https://go.dev/doc/go1.23) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#slices_collect) |
| Collect map keys, then `slices.Sort` | `slices.Sorted(maps.Keys(m))` | 1.23 | no | `[official]` [1.23 notes](https://go.dev/doc/go1.23) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#slices_sorted) |
| `time.NewTicker` plus `defer Stop()` for a forever loop | `time.Tick(d)`; keep `NewTicker` when `Stop` or `Reset` is needed | 1.23 | no | `[official]` [1.23 notes](https://go.dev/doc/go1.23) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#time_tick_gc) |

### Go 1.24

| Old | Modern | Min version | Covered by `go fix` | Source |
| --- | --- | --- | --- | --- |
| `for _, p := range strings.Split(s, sep)` | `for p := range strings.SplitSeq(s, sep)`; `FieldsSeq` for `Fields`; the `bytes` equivalents | 1.24 | yes | `[official]` [1.24 notes](https://go.dev/doc/go1.24) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#strings_split_seq) |
| `for i := 0; i < b.N; i++` in a benchmark | `for b.Loop()` | 1.24 | yes | `[official]` [1.24 notes](https://go.dev/doc/go1.24) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#testing_b_loop) |
| `context.WithCancel(context.Background())` in a test | `t.Context()` | 1.24 | yes | `[official]` [1.24 notes](https://go.dev/doc/go1.24) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#testing_t_context) |
| `json:",omitempty"` on a bool, number, struct or `time.Time` | `json:",omitzero"` | 1.24 | yes | `[official]` [1.24 notes](https://go.dev/doc/go1.24) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#json_omitzero) |

### Go 1.25

| Old | Modern | Min version | Covered by `go fix` | Source |
| --- | --- | --- | --- | --- |
| `wg.Add(1)`, `go func() { defer wg.Done(); ... }()` | `wg.Go(func() { ... })` | 1.25 | yes (`waitgroupgo`) | `[official]` [1.25 notes](https://go.dev/doc/go1.25) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#sync_waitgroup_go) |

### Go 1.26

| Old | Modern | Min version | Covered by `go fix` | Source |
| --- | --- | --- | --- | --- |
| A pointer helper `func Ptr[T any](v T) *T`, or a temporary for `&v` | `new(v)`; `new(30 * time.Second)`, `new(int32(30))` | 1.26 | yes | `[official]` [1.26 notes](https://go.dev/doc/go1.26) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#new_expression) |
| `var t *T; errors.As(err, &t)` | `t, ok := errors.AsType[*T](err)` | 1.26 | yes | `[official]` [1.26 notes](https://go.dev/doc/go1.26) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#errors_as_type) |

### Go 1.27

| Old | Modern | Min version | Covered by `go fix` | Source |
| --- | --- | --- | --- | --- |
| `encoding/json` in new code | `encoding/json/v2`; see [json/v2](#jsonv2) | 1.27 | no | `[official]` [1.27 notes](https://go.dev/doc/go1.27#jsonv2) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#json_v2) |
| A package-level generic helper that belongs to one receiver type | a generic method: `func (s Set[T]) Map[U any](f func(T) U) []U` | 1.27 | no | `[official]` [1.27 notes](https://go.dev/doc/go1.27) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#generic_methods) |
| `Document{AuditInfo: AuditInfo{CreatedBy: x}}` only to set promoted fields | `Document{CreatedBy: x}` | 1.27 | yes (`embedlit`) | `[official]` [1.27 notes](https://go.dev/doc/go1.27) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#promoted_field_literals) |
| `LastIndex` plus manual slicing | `strings.CutLast`, `bytes.CutLast` | 1.27 | yes per JetBrains; not among the analyzers the 1.27 notes name | `[official]` [1.27 notes](https://go.dev/doc/go1.27) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#strings_bytes_cut_last) |
| A third-party UUID package | the standard `uuid` package | 1.27 | no | `[official]` [1.27 notes](https://go.dev/doc/go1.27) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#stdlib_uuid) |
| Hand-copying a `url.URL` or `url.Values` | `u.Clone()`, `v.Clone()` | 1.27 | no | `[official]` [1.27 notes](https://go.dev/doc/go1.27) · `[community]` [JetBrains](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#url_clone) |


## Notes on the rows

Where the modern form is not a drop-in, the row's rule has an exception. Keep these in mind
when applying the table.

- `range n`: keep the three-clause `for` when the loop starts above zero, steps by more than
  one, or changes its bound inside the body. `[community]` —
  [JetBrains: range_over_int](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#range_over_int)
- Loop-variable copies: remove `v := v` only when it exists solely to work around the
  pre-1.22 semantics; keep a copy that serves another purpose. To point at the slice element
  rather than the per-iteration copy, take `&slice[i]`. `[official]` —
  [Go 1.22 release notes](https://go.dev/doc/go1.22);
  `[community]` — [JetBrains: loopvar_capture](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#loopvar_capture)
- `cmp.Or` evaluates every argument before the call, so it is the wrong choice when a later
  fallback is expensive or has side effects, and when a zero value such as `false` or `0` is a
  legitimate result rather than "missing". `[community]` —
  [JetBrains: cmp_or](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#cmp_or)
- `slices.SortFunc` is not stable. Code that used `sort.SliceStable` needs
  `slices.SortStableFunc` to keep equal elements in their original order. `[official]` —
  [pkg.go.dev/slices](https://pkg.go.dev/slices#SortFunc)
- `slices.Max` and `slices.Min` panic on an empty slice, and `slices.Compact` removes only
  consecutive duplicates, so sort first to remove all of them. Keep explicit code where the
  empty case or a custom comparison needs special handling. `[official]` —
  [pkg.go.dev/slices](https://pkg.go.dev/slices)
- `new(v)` takes the default type of an untyped constant: `new(30)` is `*int`, which does not
  fit a `*time.Duration` or `*int32` field. Write `new(30 * time.Second)` or `new(int32(30))`.
  Keep a pointer helper only when it adds behaviour. `[official]` —
  [Go 1.26 release notes](https://go.dev/doc/go1.26)
- `b.Loop()`: `b.N` is final only after `b.Loop` returns false, so a benchmark that sizes a
  fixture from `b.N` must be restructured, not mechanically rewritten. `[official]` —
  [Go 1.24 release notes](https://go.dev/doc/go1.24);
  `[community]` — [JetBrains: testing_b_loop](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#testing_b_loop)
- `t.Context()` is already cancelled when `t.Cleanup` functions run, so cleanup that needs a
  live context builds its own. `[official]` — [Go 1.24 release notes](https://go.dev/doc/go1.24)
- `omitzero` is for fields whose Go zero value means absent (`false`, `0`, a zero
  `time.Time`, a zero struct); keep `omitempty` for empty strings, slices and maps.
  `[official]` — [Go 1.24 release notes](https://go.dev/doc/go1.24);
  `[community]` — [JetBrains: json_omitzero](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#json_omitzero)
- Typed atomics: use them in new code. Replacing a raw `int64` or `unsafe.Pointer` field in an
  existing type changes its layout and size, and `atomic.Value` differs from
  `atomic.Pointer[T]` in nil and type handling, so migrate a type deliberately rather than
  call by call. `[community]` —
  [JetBrains: atomic_types](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#atomic_types)
- `wg.Go` fits when the goroutine's lifetime is exactly what the `WaitGroup` should track.
  `[community]` — [JetBrains: sync_waitgroup_go](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#sync_waitgroup_go)
- `time.Tick` is acceptable from 1.23 because an unreferenced ticker is now collectable
  without `Stop`; keep `time.NewTicker` when the loop needs `Stop` or `Reset`. `[official]` —
  [Go 1.23 release notes](https://go.dev/doc/go1.23#timer-changes)
- Generic methods: keep package-level generic helpers for operations that do not belong to
  one receiver type; interface methods still cannot declare type parameters. `[official]` —
  [Go 1.27 release notes](https://go.dev/doc/go1.27);
  `[community]` — [JetBrains: generic_methods](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#generic_methods)
- Promoted-field literals: do not mix a promoted field with the embedded field that promotes
  it, and pointer-embedded paths are not supported. `[community]` —
  [JetBrains: promoted_field_literals](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#promoted_field_literals)
- Standard `uuid`: keep a third-party package only when targeting a module below 1.27 or
  needing behaviour the standard API lacks. `[community]` —
  [JetBrains: stdlib_uuid](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#stdlib_uuid)

## json/v2

Go 1.27 adds `encoding/json/v2` and `encoding/json/jsontext`; `encoding/json` (v1) now runs
on the v2 implementation, with behaviour preserved except for the text of error messages.
`[official]` — [Go 1.27 release notes](https://go.dev/doc/go1.27#jsonv2)

- Use `encoding/json/v2` in new JSON code on a module at `go 1.27` or later. Its defaults
  are stricter and more interoperable: it rejects invalid UTF-8 and duplicate object names,
  and encodes `nil` slices and maps as `[]` and `{}`. `[official]` —
  [Go 1.27 release notes](https://go.dev/doc/go1.27#jsonv2);
  `[community]` — [JetBrains: json_v2](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#json_v2)
- Leave existing `encoding/json` code on v1 unless a migration is explicitly requested. Even
  a compiling import swap can change what goes on the wire, and the Go team states the v1 API
  stays supported and no one is required to migrate. `[official]` —
  [Go 1.27 release notes](https://go.dev/doc/go1.27#jsonv2)
- When migrating, start from v1's behaviour: pass `jsonv1.DefaultOptionsV1()` to every v2
  call, test the serialized output and the accepted input, then remove or override
  compatibility options one at a time. Later options take precedence over earlier ones.
  `[community]` — [JetBrains: json_v2](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#json_v2);
  `[official]` — [pkg.go.dev/encoding/json](https://pkg.go.dev/encoding/json#DefaultOptionsV1)

```go
import (
	jsonv1 "encoding/json"
	json "encoding/json/v2"
)

// still {"Nicknames":null}
body, err := json.Marshal(pet, jsonv1.DefaultOptionsV1())
// now {"Nicknames":[]}
body, err = json.Marshal(pet, jsonv1.DefaultOptionsV1(), json.FormatNilSliceAsNull(false))
```

- Do not write tag options from earlier v2 drafts. The `format` and `unknown` tag options, the
  `DiscardUnknownMembers` option and the `SkipFunc` sentinel were removed, and the `inline`
  tag option is now `embed`. `[official]` — [Go 1.27 release notes](https://go.dev/doc/go1.27#jsonv2)
- `GOEXPERIMENT=nojsonv2` restores the original v1 implementation as a stopgap and is expected
  to be removed; use it to diagnose a regression, not as a configuration. `[official]` —
  [Go 1.27 release notes](https://go.dev/doc/go1.27#jsonv2)

## Iterators

Range-over-func and the `iter` package arrive at Go 1.23, so this section applies to a module
whose `go` directive is 1.23 or later. `[official]` — [Go 1.23 release notes](https://go.dev/doc/go1.23)

- An iterator is a function that passes successive elements to a callback conventionally named
  `yield` and stops when the sequence ends or `yield` returns `false`. `iter.Seq[V]` and
  `iter.Seq2[K, V]` are the standard shapes for one and two values per element; `yield`
  panics if it is called after returning `false`, so the iterator must return as soon as it
  sees `false`. `[official]` — [pkg.go.dev/iter](https://pkg.go.dev/iter)
- Accept and return `iter.Seq` and `iter.Seq2`, not a bespoke function type, so the value
  works in a `range` loop and with the standard adapters. `[official]` —
  [pkg.go.dev/iter](https://pkg.go.dev/iter)
- Write a producer by checking `yield` on every element, and consume it with `range`, not by
  calling the function with a hand-written callback. `[official]` —
  [Range Over Function Types](https://go.dev/blog/range-functions)

```go
func (s *Set[V]) All() iter.Seq[V] {
	return func(yield func(V) bool) {
		for v := range s.items {
			if !yield(v) {
				return
			}
		}
	}
}

for v := range set.All() {
	process(v)
}
```

- Name an iterator method for the sequence it walks: `All` for every element of a collection,
  a specific noun such as `Cities` or `Languages` when a type has several sequences, and
  `Backward` for the reverse order. Document a single-use iterator, such as one reading from a
  stream, as single-use. `[official]` — [pkg.go.dev/iter](https://pkg.go.dev/iter)
- Range over `maps.Keys(m)` and `maps.Values(m)` directly when a slice is not needed; that
  avoids a temporary collection. Materialize only when a slice is required: `slices.Collect(seq)`
  for the elements, `slices.Sorted(maps.Keys(m))` for a deterministic order from an unordered
  source. `[community]` —
  [JetBrains: maps_keys_values_iter](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#maps_keys_values_iter),
  [slices_collect](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#slices_collect),
  [slices_sorted](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#slices_sorted)
- Iterate split results with `strings.SplitSeq`, `strings.FieldsSeq` and the `bytes`
  equivalents (1.24) instead of `strings.Split` and `strings.Fields`: they stream the parts
  instead of allocating a slice of all of them. `[official]` —
  [Go 1.24 release notes](https://go.dev/doc/go1.24);
  `[community]` — [JetBrains: strings_split_seq](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md#strings_split_seq)
- `iter.Pull` turns a push iterator into a pull one when a `range` loop does not fit; always
  `defer stop()`, because a caller that does not consume the sequence to completion must call
  `stop` to let the iterator finish. `[official]` — [pkg.go.dev/iter](https://pkg.go.dev/iter)

## Sources

- [JetBrains go-modern-guidelines](https://github.com/JetBrains/go-modern-guidelines)
- [JetBrains FEATURES.md](https://github.com/JetBrains/go-modern-guidelines/blob/main/FEATURES.md)
- [pkg.go.dev/iter](https://pkg.go.dev/iter)
- [pkg.go.dev/slices](https://pkg.go.dev/slices)
- [pkg.go.dev/encoding/json](https://pkg.go.dev/encoding/json)
- [Range Over Function Types](https://go.dev/blog/range-functions)
- [Go 1.18 release notes](https://go.dev/doc/go1.18)
- [Go 1.19 release notes](https://go.dev/doc/go1.19)
- [Go 1.20 release notes](https://go.dev/doc/go1.20)
- [Go 1.21 release notes](https://go.dev/doc/go1.21)
- [Go 1.22 release notes](https://go.dev/doc/go1.22)
- [Go 1.23 release notes](https://go.dev/doc/go1.23)
- [Go 1.24 release notes](https://go.dev/doc/go1.24)
- [Go 1.25 release notes](https://go.dev/doc/go1.25)
- [Go 1.26 release notes](https://go.dev/doc/go1.26)
- [Go 1.27 release notes](https://go.dev/doc/go1.27)

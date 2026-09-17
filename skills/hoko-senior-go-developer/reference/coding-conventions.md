# Coding conventions

Naming, package design and the interface boundary, receiver choice, zero values, embedding,
and when a type parameter earns its place.

There is no single Go-team style guide. Effective Go announces that it "was written for Go's
release in 2009 and is not actively updated… it does not cover significant changes to the
language (generics), ecosystem (modules), or libraries added since", and Go Code Review
Comments calls itself "a laundry list of common style issues, not a comprehensive style
guide". Read "the Go team's convention" below as: the spec for facts, Effective Go and the
Code Review Comments wiki for conventions, and the Go blog and release notes for newer
features. `[official]` — [Effective Go](https://go.dev/doc/effective_go),
[Code Review Comments](https://go.dev/wiki/CodeReviewComments)

## Naming

- Package names are short, lowercase, single-word, with no underscores or mixedCaps, and are
  the base name of the directory. Avoid `util`, `common`, `misc`, `api` and `types`.
  `[official]` — [Effective Go §Package names](https://go.dev/doc/effective_go#package-names),
  [Code Review Comments §Package Names](https://go.dev/wiki/CodeReviewComments#package-names)
- Omit the package name from exported identifiers, so the call site does not stutter:
  `bufio.Reader`, not `BufReader`; `ring.New`, not `ring.NewRing`. `[official]` —
  [Effective Go §Package names](https://go.dev/doc/effective_go#package-names)
- Identifiers use MixedCaps or mixedCaps, never underscores: `maxLength` and `MaxLength`, not
  `MAX_LENGTH` or `max_length`. `[official]` —
  [Effective Go §MixedCaps](https://go.dev/doc/effective_go#mixed-caps)
- Initialisms keep one case throughout: `URL`/`url`, never `Url`; `ServeHTTP`, not
  `ServeHttp`; `appID`, not `appId`; a name may hold several, as in `xmlHTTPRequest`.
  Protocol-buffer-generated code is exempt. `[official]` —
  [Code Review Comments §Initialisms](https://go.dev/wiki/CodeReviewComments#initialisms)
- Go's style guide adds nuance for initialisms that begin with a lowercase word, such as `iOS`,
  `gRPC` and `DDoS`, and an explicit correct/incorrect table. `[community]` —
  [Google Go decisions §Initialisms](https://google.github.io/styleguide/go/decisions#initialisms)
- Receiver names are one or two letters abbreviating the type and are consistent across every
  method of that type; never `this`, `self` or `me`, and never `_`. Omitting the name is
  correct when it is unused. `[official]` —
  [Code Review Comments §Receiver Names](https://go.dev/wiki/CodeReviewComments#receiver-names)
- Getters do not take a `Get` prefix: a field `owner` gets `Owner()` and a setter
  `SetOwner()`. `[official]` — [Effective Go §Getters](https://go.dev/doc/effective_go#getters)
  The exception is a concept that genuinely uses the word "get" (HTTP GET); for an expensive
  or remote retrieval prefer `Compute` or `Fetch`. `[community]` —
  [Google Go decisions §Getters](https://google.github.io/styleguide/go/decisions#getters)
- Test, benchmark and example function names may contain underscores, for example
  `TestMyFunction_WhatIsBeingTested`; this is the documented exception to MixedCaps, along
  with packages imported only by generated code and OS/cgo interop. `[community]` —
  [Google Go decisions §Underscores](https://google.github.io/styleguide/go/decisions#underscores),
  [Uber Go §Function Names](https://github.com/uber-go/guide/blob/master/style.md#function-names)
- An identifier is exported when its first character is an upper-case letter. Unexported
  names have no documentation obligation unless the type or function is non-trivial.
  `[official]` — [Go spec §Declarations and scope](https://go.dev/ref/spec#Declarations_and_scope)
- Since Go 1.18 `any` is a predeclared alias for `interface{}`; prefer `any` in new code.
  `[official]` — [Go spec §Predeclared identifiers](https://go.dev/ref/spec#Predeclared_identifiers)

## Package design and the interface boundary

"Accept interfaces, return structs" is community coinage, not Go-team language: Jack
Lindamood wrote it in two 2016 articles, and Dave Cheney quoted it verbatim while calling it
"tweet sized… lacks nuance". The originals could not be re-read for this doc (both returned
HTTP 403); the wording is verified through Cheney's quotation, not the primary article.
`[community]` — [Dave Cheney, SOLID Go Design](https://dave.cheney.net/2016/08/20/solid-go-design)

The Go team's own, adjacent rule is in Code Review Comments §Interfaces:

> Go interfaces generally belong in the package that uses values of the interface type, not
> the package that implements those values. The implementing package should return concrete
> (usually pointer or struct) types: that way, new methods can be added to implementations
> without requiring extensive refactoring.

`[official]` — [Code Review Comments §Interfaces](https://go.dev/wiki/CodeReviewComments#interfaces)

- The consumer owns the interface: the function depends only on the behaviour it calls, so the
  caller's package declares the minimal interface. The producer returns a concrete type, so
  callers keep the full method set and the producer can still grow it. `[official]` —
  [Code Review Comments §Interfaces](https://go.dev/wiki/CodeReviewComments#interfaces)
- Do not define an interface on the implementor's side so it can be mocked, and do not define
  one before something uses it. `[official]` —
  [Code Review Comments §Interfaces](https://go.dev/wiki/CodeReviewComments#interfaces)
- "Return structs" is a default, not a law. If a type exists only to implement an interface
  and will never have exported methods beyond it, do not export the type; the constructor
  should return the interface value instead (`crc32.NewIEEE` and `adler32.New` return
  `hash.Hash32`). `[official]` —
  [Effective Go §Generality](https://go.dev/doc/effective_go#generality)
- Google formalises three more sanctioned returns of an interface: encapsulation (`error`),
  factory / strategy / chaining patterns that return one of several types, and breaking an
  import cycle. `[community]` —
  [Google Go best practices §Interfaces](https://google.github.io/styleguide/go/best-practices#interfaces)

## Receivers: value or pointer

- A method must use a pointer receiver to mutate the receiver, to avoid copying a value that
  holds a `sync.Mutex`-like field, or when the struct or array is large. `[official]` —
  [Code Review Comments §Receiver Type](https://go.dev/wiki/CodeReviewComments#receiver-type)
- Map, func and chan receivers are never pointers; a slice receiver is a pointer only if the
  method reslices or reallocates. A value receiver suits a small, naturally-value type with no
  mutable state, such as `time.Time`, `int` or `string`, but choose it for allocation reasons
  only after profiling. `[official]` —
  [Code Review Comments §Receiver Type](https://go.dev/wiki/CodeReviewComments#receiver-type)
- A type whose method has a pointer receiver satisfies an interface as `*T` but not as `T`,
  and values stored in maps are not addressable, so pointer methods cannot be called on them.
  This is why mixing receiver types on one type is a smell: the method set changes and
  interface satisfaction becomes surprising. `[official]` —
  [Effective Go §Pointers vs. Values](https://go.dev/doc/effective_go#pointers_vs_values),
  `[community]` —
  [Uber Go §Receivers and Interfaces](https://github.com/uber-go/guide/blob/master/style.md#receivers-and-interfaces)
- Do not mix receiver types on one type, and when in doubt use a pointer receiver.
  `[official]` — [Code Review Comments §Receiver Type](https://go.dev/wiki/CodeReviewComments#receiver-type)

## Zero values and constructors

- Design types so the zero value is usable without further initialization; `bytes.Buffer` and
  `sync.Mutex` need no `Init`, and the property holds through embedded fields. `[official]` —
  [Effective Go §Allocation with new](https://go.dev/doc/effective_go#allocation_new)
- A constructor is for when the zero value is not good enough (`os.NewFile`). Constructors
  should use composite literals, and `new(T)` and `&T{}` are equivalent. `[official]` —
  [Effective Go §Constructors and composite literals](https://go.dev/doc/effective_go#composite_literals)
- Constructor names take their context from the package: `ring.New` for the package's main
  type, `NewThing` when the package exports several. `[official]` —
  [Effective Go §Package names](https://go.dev/doc/effective_go#package-names)
- Google adds: declare a value with the zero value when you want an empty value that is ready
  for later use (`var coords Point` before `json.Unmarshal`), and use `new(pb.Bar)` or
  `&pb.Bar{}` for a pointer to a zero value. `[community]` —
  [Google Go best practices §Declaring variables with zero values](https://google.github.io/styleguide/go/best-practices#declaring-variables-with-zero-values)

## Composition and embedding

- Embedding borrows an implementation; it is not subclassing. Embedding an interface composes
  method sets (`io.ReadWriter` embeds `Reader` and `Writer`), and embedding a struct or
  `*struct` promotes its methods, but the invoked method's receiver is the inner type, not the
  outer. `[official]` — [Effective Go §Embedding](https://go.dev/doc/effective_go#embedding)
- An embedded field must be a type name `T` or a pointer to a non-interface type `*T`; `T` may
  not itself be a pointer or a type parameter. Only interfaces may be embedded in interfaces.
  Promoted methods join the method set according to the receiver rules, and a name conflict
  resolves by depth before it becomes an error. `[official]` —
  [Go spec §Struct types](https://go.dev/ref/spec#Struct_types),
  [Go spec §Embedded interfaces](https://go.dev/ref/spec#Embedded_interfaces)
- Embedding an interface into a struct is how a type borrows a method set it does not want to
  implement, as `io.WriteCloser` is embedded in the standard library's counting wrapper.
  `[official]` — [Effective Go §Embedding](https://go.dev/doc/effective_go#embedding)
- Uber diverges from the Go team here: it says embedding must give a tangible benefit, never
  embed a mutex, and avoid embedding types in public structs because embedding leaks
  implementation details and inhibits type evolution. Effective Go presents embedding more
  positively as an inheritance substitute; treat the divergence as contested. `[contested]` —
  [Uber Go §Embedding in Structs](https://github.com/uber-go/guide/blob/master/style.md#embedding-in-structs),
  [Uber Go §Avoid Embedding Types in Public Structs](https://github.com/uber-go/guide/blob/master/style.md#avoid-embedding-types-in-public-structs)

## Generics — contested

The Go team's rule is to write code, not to define types: "avoid type parameters until you
notice that you are about to write the exact same code multiple times." Type parameters earn
their place for functions over language containers (slices, maps, channels), for
general-purpose data structures (list, tree), and for a method whose implementation is
identical across types. Do not replace an interface with a type parameter
(`func ReadSome[T io.Reader]` is worse than `func ReadSome(r io.Reader)` and no faster), do
not use type parameters when the per-type implementations differ, and prefer functions to
methods when a constraint like comparison is involved. `[official]` —
[When to use generics](https://go.dev/blog/when-generics)

- Google is stricter: be wary of premature use, start concrete if only one type is
  instantiated, do not build DSLs or error frameworks with generics, and prefer a unifying
  interface when several types already share one. `[community]` —
  [Google Go decisions §Generics](https://google.github.io/styleguide/go/decisions#generics)
- How eagerly to reach for generics remains genuinely contested: the Go team and Google both
  counsel starting concrete, while much of the community reaches for generics sooner for
  containers and functional helpers. **This skill takes the Go-team side: a type parameter is
  earned by removing real duplication, not applied speculatively.** `[contested]` —
  [When to use generics](https://go.dev/blog/when-generics)
- Go 1.27 adds generic methods: a method declaration may declare its own type parameters, and
  like a generic function it "must be instantiated before it can be called or used as a
  value". The standard library gains `math/rand/v2`'s `(*Rand).N[Int intType](Int) Int`.
  `[official]` — [Go 1.27 release notes](https://go.dev/doc/go1.27),
  [Go spec §Method declarations](https://go.dev/ref/spec#Method_declarations)

  ```go
  type List[T any] []T

  func (l List[T]) Map[U any](f func(T) U) []U {
      out := make([]U, len(l))
      for i, v := range l {
          out[i] = f(v)
      }
      return out
  }
  ```

- The restriction is one-sided: interface methods may not declare type parameters, and a
  generic method cannot satisfy an interface method. A generic method can still be turned
  into a function through a method expression such as `List[int].Map[int]`. `[official]` —
  [Generic methods](https://go.dev/blog/generic-methods)
- The Go team excluded generic interface methods because an interface value may hold any
  implementing type compiled separately, so the compiler would have to instantiate the method
  for every possible type argument at the declaration site; the blog calls the limitation
  "for now". `[official]` — [Generic methods](https://go.dev/blog/generic-methods)

## Exported surface and `internal/`

- Visibility is capitalisation: an identifier is exported if its first character is an
  upper-case letter. There is no `public` keyword. `[official]` —
  [Effective Go §Names](https://go.dev/doc/effective_go#names)
- Keep anything not meant for importers under `internal/`; the compiler enforces the boundary,
  which is why it is not optional decoration. The mechanics are in
  [project-layout.md](project-layout.md#internal-is-the-enforced-boundary). `[official]` —
  [Go 1.4 release notes §Internal packages](https://go.dev/doc/go1.4#internalpackages)

## Sources

- [Effective Go](https://go.dev/doc/effective_go)
- [Go Code Review Comments](https://go.dev/wiki/CodeReviewComments)
- [The Go Programming Language Specification](https://go.dev/ref/spec)
- [When to use generics](https://go.dev/blog/when-generics)
- [Generic methods](https://go.dev/blog/generic-methods)
- [Go 1.27 release notes](https://go.dev/doc/go1.27)
- [Go 1.4 release notes](https://go.dev/doc/go1.4)
- [Google Go Style Guide — decisions](https://google.github.io/styleguide/go/decisions)
- [Google Go Style Guide — best practices](https://google.github.io/styleguide/go/best-practices)
- [Uber Go Style Guide](https://github.com/uber-go/guide/blob/master/style.md)
- [Dave Cheney, SOLID Go Design](https://dave.cheney.net/2016/08/20/solid-go-design)

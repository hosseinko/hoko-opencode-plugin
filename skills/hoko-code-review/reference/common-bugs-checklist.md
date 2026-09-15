# Common Bugs Checklist

Language-specific bugs and issues to watch for during code review.

## Universal Issues

### Logic Errors
- [ ] Off-by-one errors in loops and array access
- [ ] Incorrect boolean logic (De Morgan's law violations)
- [ ] Missing null/undefined checks
- [ ] Race conditions in concurrent code
- [ ] Incorrect comparison operators (== vs ===, = vs ==)
- [ ] Integer overflow/underflow
- [ ] Floating point comparison issues

### Resource Management
- [ ] Memory leaks (unclosed connections, listeners)
- [ ] File handles not closed
- [ ] Database connections not released
- [ ] Event listeners not removed
- [ ] Timers/intervals not cleared

### Error Handling
- [ ] Swallowed exceptions (empty catch blocks)
- [ ] Generic exception handling hiding specific errors
- [ ] Missing error propagation
- [ ] Incorrect error types thrown
- [ ] Missing finally/cleanup blocks

### Silent Failures

A silent failure is worse than a crash: the run goes green, the data is wrong, and the
bug surfaces three layers downstream with no stack trace pointing home. Treat every one
of these as a finding, not a style note.

**Swallowed errors**
- [ ] `catch {}`, `except: pass`, `if err != nil {}` — the error is caught and dropped
- [ ] Error converted to `null`, `[]`, `0` or `false` with no record that it happened
- [ ] `.catch(() => [])` / `->catch(fn () => [])` — a failed fetch and an empty result
      are now indistinguishable to every caller

**Dangerous fallbacks**
- [ ] A default value substituted for a failed lookup, so the caller cannot tell a real
      zero from a missing one
- [ ] Retry or degrade paths that succeed silently — the degraded mode must be visible
      in the response or the logs, not just in the code
- [ ] Partial results returned as if complete (a batch where some items failed)

**Log-and-forget**
- [ ] Logged at the wrong severity — a dropped record logged at `debug` or `info`
- [ ] Logged without the identifiers needed to find the row again (id, key, batch,
      source)
- [ ] Logged and then execution continues as if nothing happened, where the correct
      behaviour is to fail the operation

**Lost propagation**
- [ ] Stack trace discarded by rethrowing a new error without wrapping the original
      (`raise NewError()` instead of `raise NewError() from e`; no `previous` argument;
      no `%w` / `.context()`)
- [ ] Generic rethrow that flattens several distinct failures into one type
- [ ] Async errors never awaited, so the rejection is unhandled or invisible

**Missing handling entirely**
- [ ] Network, file or database call with no timeout — it hangs instead of failing
- [ ] Transactional work with no rollback on the failure path
- [ ] A loop that continues past a failed iteration with no count of what was skipped

For each finding report: location, severity, what fails silently, what the downstream
impact is, and the fix.

## TypeScript/JavaScript

### Type Issues
```typescript
// ❌ Using any defeats type safety
function process(data: any) { return data.value; }

// ✅ Use proper types
interface Data { value: string; }
function process(data: Data) { return data.value; }
```

### Async/Await Pitfalls
```typescript
// ❌ Missing await
async function fetch() {
  const data = fetchData();  // Missing await!
  return data.json();
}

// ❌ Unhandled promise rejection
async function risky() {
  const result = await fetchData();  // No try-catch
  return result;
}

// ✅ Proper error handling
async function safe() {
  try {
    const result = await fetchData();
    return result;
  } catch (error) {
    console.error('Fetch failed:', error);
    throw error;
  }
}
```

### React Specific

#### Hooks Rules Violations
```tsx
// ❌ Conditional Hooks call — violates Rules of Hooks
function BadComponent({ show }) {
  if (show) {
    const [value, setValue] = useState(0);  // Error!
  }
  return <div>...</div>;
}

// ✅ Hooks must be called unconditionally at the top level
function GoodComponent({ show }) {
  const [value, setValue] = useState(0);
  if (!show) return null;
  return <div>{value}</div>;
}

// ❌ Hooks called inside a loop
function BadLoop({ items }) {
  items.forEach(item => {
    const [selected, setSelected] = useState(false);  // Error!
  });
}

// ✅ Lift state up or use a different data structure
function GoodLoop({ items }) {
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  return items.map(item => (
    <Item key={item.id} selected={selectedIds.has(item.id)} />
  ));
}
```

#### Common useEffect Mistakes
```tsx
// ❌ Incomplete dependency array — stale closure
function StaleClosureExample({ userId, onSuccess }) {
  const [data, setData] = useState(null);
  useEffect(() => {
    fetchData(userId).then(result => {
      setData(result);
      onSuccess(result);  // onSuccess may be stale!
    });
  }, [userId]);  // missing onSuccess dependency
}

// ✅ Complete dependency array
useEffect(() => {
  fetchData(userId).then(result => {
    setData(result);
    onSuccess(result);
  });
}, [userId, onSuccess]);

// ❌ Infinite loop — updating a dependency inside the effect
function InfiniteLoop() {
  const [count, setCount] = useState(0);
  useEffect(() => {
    setCount(count + 1);  // triggers re-render, which triggers the effect again
  }, [count]);  // infinite loop!
}

// ❌ Missing cleanup function — memory leak
function MemoryLeak({ userId }) {
  const [user, setUser] = useState(null);
  useEffect(() => {
    fetchUser(userId).then(setUser);  // setUser called even after component unmounts
  }, [userId]);
}

// ✅ Correct cleanup
function NoLeak({ userId }) {
  const [user, setUser] = useState(null);
  useEffect(() => {
    let cancelled = false;
    fetchUser(userId).then(data => {
      if (!cancelled) setUser(data);
    });
    return () => { cancelled = true; };
  }, [userId]);
}

// ❌ useEffect for derived state (anti-pattern)
function BadDerived({ items }) {
  const [total, setTotal] = useState(0);
  useEffect(() => {
    setTotal(items.reduce((a, b) => a + b.price, 0));
  }, [items]);  // unnecessary effect + extra render
}

// ✅ Calculate directly or use useMemo
function GoodDerived({ items }) {
  const total = useMemo(
    () => items.reduce((a, b) => a + b.price, 0),
    [items]
  );
}

// ❌ useEffect for event responses
function BadEvent() {
  const [query, setQuery] = useState('');
  useEffect(() => {
    if (query) logSearch(query);  // should be in the event handler
  }, [query]);
}

// ✅ Side effects in event handlers
function GoodEvent() {
  const handleSearch = (q: string) => {
    setQuery(q);
    logSearch(q);
  };
}
```

#### useMemo / useCallback Misuse
```tsx
// ❌ Over-optimization — constants don't need memo
function OverOptimized() {
  const config = useMemo(() => ({ api: '/v1' }), []);  // pointless
  const noop = useCallback(() => {}, []);  // pointless
}

// ❌ useMemo with empty deps (may hide a bug)
function EmptyDeps({ user }) {
  const greeting = useMemo(() => `Hello ${user.name}`, []);
  // greeting won't update when user changes!
}

// ❌ useCallback with dependencies that always change
function UselessCallback({ data }) {
  const process = useCallback(() => {
    return data.map(transform);
  }, [data]);  // completely ineffective if data is a new reference every render
}

// ❌ useMemo/useCallback without React.memo
function Parent() {
  const data = useMemo(() => compute(), []);
  const handler = useCallback(() => {}, []);
  return <Child data={data} onClick={handler} />;
  // Child is not wrapped in React.memo, so these optimizations are meaningless
}

// ✅ Correct optimization combination
const MemoChild = React.memo(function Child({ data, onClick }) {
  return <button onClick={onClick}>{data}</button>;
});

function Parent() {
  const data = useMemo(() => expensiveCompute(), [dep]);
  const handler = useCallback(() => {}, []);
  return <MemoChild data={data} onClick={handler} />;
}
```

#### Component Design Issues
```tsx
// ❌ Defining a component inside another component
function Parent() {
  // Creates a new Child function on every render, causing a full remount
  const Child = () => <div>child</div>;
  return <Child />;
}

// ✅ Define components outside
const Child = () => <div>child</div>;
function Parent() {
  return <Child />;
}

// ❌ Props are always new references — defeats memo
function BadProps() {
  return (
    <MemoComponent
      style={{ color: 'red' }}      // new object on every render
      onClick={() => handle()}       // new function on every render
      items={data.filter(x => x)}    // new array on every render
    />
  );
}

// ❌ Mutating props directly
function MutateProps({ user }) {
  user.name = 'Changed';  // never do this!
  return <div>{user.name}</div>;
}
```

#### Server Components Mistakes (React 19+)
```tsx
// ❌ Using client-side APIs in a Server Component
// app/page.tsx (Server Component by default)
export default function Page() {
  const [count, setCount] = useState(0);  // Error!
  useEffect(() => {}, []);  // Error!
  return <button onClick={() => {}}>Click</button>;  // Error!
}

// ✅ Move interactive logic to a Client Component
// app/counter.tsx
'use client';
export function Counter() {
  const [count, setCount] = useState(0);
  return <button onClick={() => setCount(c => c + 1)}>{count}</button>;
}

// app/page.tsx
import { Counter } from './counter';
export default async function Page() {
  const data = await fetchData();  // Server Components can await directly
  return <Counter initialCount={data.count} />;
}

// ❌ 'use client' on a parent component makes the entire tree client-side
// layout.tsx
'use client';  // bad idea! all child components become client components
export default function Layout({ children }) { ... }
```

#### Common Testing Mistakes
```tsx
// ❌ Using container queries
const { container } = render(<Component />);
const button = container.querySelector('button');  // not recommended

// ✅ Use screen and semantic queries
render(<Component />);
const button = screen.getByRole('button', { name: /submit/i });

// ❌ Using fireEvent
fireEvent.click(button);

// ✅ Using userEvent
await userEvent.click(button);

// ❌ Testing implementation details
expect(component.state.isOpen).toBe(true);

// ✅ Testing behavior
expect(screen.getByRole('dialog')).toBeVisible();

// ❌ Awaiting a synchronous query
await screen.getByText('Hello');  // getBy is synchronous

// ✅ Use findBy for async
await screen.findByText('Hello');  // findBy waits
```

### React Common Mistakes Checklist
- [ ] Hooks not called at the top level (inside conditions/loops)
- [ ] useEffect dependency array is incomplete
- [ ] useEffect missing cleanup function
- [ ] useEffect used to compute derived state
- [ ] useMemo/useCallback over-used
- [ ] useMemo/useCallback not paired with React.memo
- [ ] Child components defined inside parent components
- [ ] Props are new object/function references (when passed to memo components)
- [ ] Props mutated directly
- [ ] Lists missing key or using index as key
- [ ] Server Components using client-side APIs
- [ ] 'use client' on a parent causing the entire tree to become client-side
- [ ] Tests using container queries instead of screen
- [ ] Tests asserting implementation details instead of behavior

### React 19 Actions & Forms Mistakes

```tsx
// === useActionState mistakes ===

// ❌ Calling setState directly inside an Action instead of returning state
const [state, action] = useActionState(async (prev, formData) => {
  setSomeState(newValue);  // wrong! should return the new state
}, initialState);

// ✅ Return the new state
const [state, action] = useActionState(async (prev, formData) => {
  const result = await submitForm(formData);
  return { ...prev, data: result };  // return new state
}, initialState);

// ❌ Forgetting to handle isPending
const [state, action] = useActionState(submitAction, null);
return <button>Submit</button>;  // user can click multiple times

// ✅ Use isPending to disable the button
const [state, action, isPending] = useActionState(submitAction, null);
return <button disabled={isPending}>Submit</button>;

// === useFormStatus mistakes ===

// ❌ Calling useFormStatus at the same level as the form
function Form() {
  const { pending } = useFormStatus();  // always undefined here!
  return <form><button disabled={pending}>Submit</button></form>;
}

// ✅ Call it inside a child component
function SubmitButton() {
  const { pending } = useFormStatus();
  return <button disabled={pending}>Submit</button>;
}
function Form() {
  return <form><SubmitButton /></form>;
}

// === useOptimistic mistakes ===

// ❌ Used for critical business operations
function PaymentButton() {
  const [optimisticPaid, setPaid] = useOptimistic(false);
  const handlePay = async () => {
    setPaid(true);  // dangerous: shows as paid but may fail
    await processPayment();
  };
}

// ❌ Not handling the UI state after rollback
const [optimisticLikes, addLike] = useOptimistic(likes);
// On failure the UI rolls back, but the user may be confused why the like disappeared

// ✅ Provide failure feedback
const handleLike = async () => {
  addLike(1);
  try {
    await likePost();
  } catch {
    toast.error('Like failed, please try again');  // notify the user
  }
};
```

### React 19 Forms Checklist
- [ ] useActionState returns new state instead of calling setState
- [ ] useActionState correctly uses isPending to disable submission
- [ ] useFormStatus called inside a child component of the form
- [ ] useOptimistic not used for critical business operations (payments, deletions, etc.)
- [ ] useOptimistic provides user feedback on failure
- [ ] Server Actions correctly marked with 'use server'

### Suspense & Streaming Mistakes

```tsx
// === Suspense boundary mistakes ===

// ❌ Entire page in one Suspense — slow content blocks fast content
function BadPage() {
  return (
    <Suspense fallback={<FullPageLoader />}>
      <FastHeader />      {/* fast */}
      <SlowMainContent /> {/* slow — blocks the whole page */}
      <FastFooter />      {/* fast */}
    </Suspense>
  );
}

// ✅ Independent boundaries — nothing blocks anything else
function GoodPage() {
  return (
    <>
      <FastHeader />
      <Suspense fallback={<ContentSkeleton />}>
        <SlowMainContent />
      </Suspense>
      <FastFooter />
    </>
  );
}

// ❌ No Error Boundary
function NoErrorHandling() {
  return (
    <Suspense fallback={<Loading />}>
      <DataFetcher />  {/* an error causes a blank screen */}
    </Suspense>
  );
}

// ✅ Error Boundary + Suspense
function WithErrorHandling() {
  return (
    <ErrorBoundary fallback={<ErrorFallback />}>
      <Suspense fallback={<Loading />}>
        <DataFetcher />
      </Suspense>
    </ErrorBoundary>
  );
}

// === use() Hook mistakes ===

// ❌ Creating a Promise inside the component (new Promise on every render)
function BadUse() {
  const data = use(fetchData());  // creates a new Promise on every render!
  return <div>{data}</div>;
}

// ✅ Create in a parent and pass via props
function Parent() {
  const dataPromise = useMemo(() => fetchData(), []);
  return <Child dataPromise={dataPromise} />;
}
function Child({ dataPromise }) {
  const data = use(dataPromise);
  return <div>{data}</div>;
}

// === Next.js Streaming mistakes ===

// ❌ Awaiting slow data in layout.tsx — blocks all child pages
// app/layout.tsx
export default async function Layout({ children }) {
  const config = await fetchSlowConfig();  // blocks the entire application!
  return <ConfigProvider value={config}>{children}</ConfigProvider>;
}

// ✅ Move slow data to the page level or use Suspense
// app/layout.tsx
export default function Layout({ children }) {
  return (
    <Suspense fallback={<ConfigSkeleton />}>
      <ConfigProvider>{children}</ConfigProvider>
    </Suspense>
  );
}
```

### Suspense Checklist
- [ ] Slow content has its own independent Suspense boundary
- [ ] Each Suspense has a corresponding Error Boundary
- [ ] Fallback is a meaningful skeleton (not just a spinner)
- [ ] Promises passed to use() are not created during render
- [ ] Slow data is not awaited inside layout
- [ ] Nesting does not exceed 3 levels

### TanStack Query Mistakes

```tsx
// === Query configuration mistakes ===

// ❌ queryKey doesn't include query parameters
function BadQuery({ userId, filters }) {
  const { data } = useQuery({
    queryKey: ['users'],  // missing userId and filters!
    queryFn: () => fetchUsers(userId, filters),
  });
  // data won't update when userId or filters change
}

// ✅ queryKey includes all parameters that affect the data
function GoodQuery({ userId, filters }) {
  const { data } = useQuery({
    queryKey: ['users', userId, filters],
    queryFn: () => fetchUsers(userId, filters),
  });
}

// ❌ staleTime: 0 causes excessive requests
const { data } = useQuery({
  queryKey: ['data'],
  queryFn: fetchData,
  // default staleTime: 0 — refetches on every mount/window focus
});

// ✅ Set a reasonable staleTime
const { data } = useQuery({
  queryKey: ['data'],
  queryFn: fetchData,
  staleTime: 5 * 60 * 1000,  // won't auto-refetch within 5 minutes
});

// === useSuspenseQuery mistakes ===

// ❌ useSuspenseQuery + enabled (not supported)
const { data } = useSuspenseQuery({
  queryKey: ['user', userId],
  queryFn: () => fetchUser(userId),
  enabled: !!userId,  // wrong! useSuspenseQuery does not support enabled
});

// ✅ Use conditional rendering instead
function UserQuery({ userId }) {
  const { data } = useSuspenseQuery({
    queryKey: ['user', userId],
    queryFn: () => fetchUser(userId),
  });
  return <UserProfile user={data} />;
}

function Parent({ userId }) {
  if (!userId) return <SelectUser />;
  return (
    <Suspense fallback={<UserSkeleton />}>
      <UserQuery userId={userId} />
    </Suspense>
  );
}

// === Mutation mistakes ===

// ❌ Not invalidating queries after a successful mutation
const mutation = useMutation({
  mutationFn: updateUser,
  // forgot to invalidate — UI shows stale data
});

// ✅ Invalidate related queries on success
const mutation = useMutation({
  mutationFn: updateUser,
  onSuccess: () => {
    queryClient.invalidateQueries({ queryKey: ['users'] });
  },
});

// ❌ Optimistic update without rollback handling
const mutation = useMutation({
  mutationFn: updateTodo,
  onMutate: async (newTodo) => {
    queryClient.setQueryData(['todos'], (old) => [...old, newTodo]);
    // previous data not saved — cannot roll back on failure!
  },
});

// ✅ Complete optimistic update with rollback
const mutation = useMutation({
  mutationFn: updateTodo,
  onMutate: async (newTodo) => {
    await queryClient.cancelQueries({ queryKey: ['todos'] });
    const previous = queryClient.getQueryData(['todos']);
    queryClient.setQueryData(['todos'], (old) => [...old, newTodo]);
    return { previous };
  },
  onError: (err, newTodo, context) => {
    queryClient.setQueryData(['todos'], context.previous);
  },
  onSettled: () => {
    queryClient.invalidateQueries({ queryKey: ['todos'] });
  },
});

// === v5 migration mistakes ===

// ❌ Using deprecated API
const { data, isLoading } = useQuery(['key'], fetchFn);  // v4 syntax

// ✅ v5 single object argument
const { data, isPending } = useQuery({
  queryKey: ['key'],
  queryFn: fetchFn,
});

// ❌ Confusing isPending and isLoading
if (isLoading) return <Spinner />;
// In v5: isLoading = isPending && isFetching

// ✅ Choose based on intent
if (isPending) return <Spinner />;  // no cached data
// or
if (isFetching) return <Refreshing />;  // background refresh in progress
```

### TanStack Query Checklist
- [ ] queryKey includes all parameters that affect the data
- [ ] A reasonable staleTime is set (not the default 0)
- [ ] useSuspenseQuery does not use enabled
- [ ] Related queries invalidated after a successful mutation
- [ ] Optimistic updates have complete rollback logic
- [ ] v5 uses single object argument syntax
- [ ] Understands isPending vs isLoading vs isFetching

### TypeScript/JavaScript Common Mistakes
- [ ] `==` instead of `===`
- [ ] Modifying array/object during iteration
- [ ] `this` context lost in callbacks
- [ ] Missing `key` prop in lists
- [ ] Closure capturing loop variable
- [ ] parseInt without radix parameter

## Vue 3

### Reactivity Loss
```vue
<!-- ❌ Destructuring reactive loses reactivity -->
<script setup>
const state = reactive({ count: 0 })
const { count } = state  // count is not reactive!
</script>

<!-- ✅ Use toRefs -->
<script setup>
const state = reactive({ count: 0 })
const { count } = toRefs(state)  // count.value is reactive
</script>
```

### Passing Reactive Props to Composables
```vue
<!-- ❌ Passing a prop value to a composable loses reactivity -->
<script setup>
const props = defineProps<{ id: string }>()
const { data } = useFetch(props.id)  // won't re-fetch when id changes!
</script>

<!-- ✅ Use toRef or a getter -->
<script setup>
const props = defineProps<{ id: string }>()
const { data } = useFetch(() => props.id)  // getter preserves reactivity
// or
const { data } = useFetch(toRef(props, 'id'))
</script>
```

### Watch Cleanup
```vue
<!-- ❌ Async watch without cleanup causes race conditions -->
<script setup>
watch(id, async (newId) => {
  const data = await fetchData(newId)
  result.value = data  // an older request may overwrite a newer result!
})
</script>

<!-- ✅ Use onCleanup to cancel stale requests -->
<script setup>
watch(id, async (newId, _, onCleanup) => {
  const controller = new AbortController()
  onCleanup(() => controller.abort())

  const data = await fetchData(newId, controller.signal)
  result.value = data
})
</script>
```

### Computed Side Effects
```vue
<!-- ❌ Modifying other state inside computed -->
<script setup>
const total = computed(() => {
  sideEffect.value++  // side effect! runs on every access
  return items.value.reduce((a, b) => a + b, 0)
})
</script>

<!-- ✅ Computed should be pure -->
<script setup>
const total = computed(() => {
  return items.value.reduce((a, b) => a + b, 0)
})
// Put side effects in watch
watch(total, () => { sideEffect.value++ })
</script>
```

### Template Common Mistakes
```vue
<!-- ❌ Using v-if and v-for together (v-if has higher priority) -->
<template>
  <div v-for="item in items" v-if="item.visible" :key="item.id">
    {{ item.name }}
  </div>
</template>

<!-- ✅ Use computed or wrap with template -->
<template>
  <template v-for="item in items" :key="item.id">
    <div v-if="item.visible">{{ item.name }}</div>
  </template>
</template>
```

### Common Mistakes
- [ ] Destructuring a reactive object loses reactivity
- [ ] Props passed to composables without maintaining reactivity
- [ ] Async watch callbacks missing cleanup function
- [ ] Side effects inside computed
- [ ] v-for uses index as key (when the list may be reordered)
- [ ] v-if and v-for on the same element
- [ ] defineProps without TypeScript type declarations
- [ ] withDefaults object defaults not using factory functions
- [ ] Mutating props directly (instead of emit)
- [ ] watchEffect dependencies unclear, causing over-triggering

## Python

### Mutable Default Arguments
```python
# ❌ Bug: List shared across all calls
def add_item(item, items=[]):
    items.append(item)
    return items

# ✅ Correct
def add_item(item, items=None):
    if items is None:
        items = []
    items.append(item)
    return items
```

### Exception Handling
```python
# ❌ Catching everything, including KeyboardInterrupt
try:
    risky_operation()
except:
    pass

# ✅ Catch specific exceptions
try:
    risky_operation()
except ValueError as e:
    logger.error(f"Invalid value: {e}")
    raise
```

### Class Attributes
```python
# ❌ Shared mutable class attribute
class User:
    permissions = []  # Shared across all instances!

# ✅ Initialize in __init__
class User:
    def __init__(self):
        self.permissions = []
```

### Common Mistakes
- [ ] Using `is` instead of `==` for value comparison
- [ ] Forgetting `self` parameter in methods
- [ ] Modifying list while iterating
- [ ] String concatenation in loops (use join)
- [ ] Not closing files (use `with` statement)

## Rust

### Ownership and Borrowing

```rust
// ❌ Use after move
let s = String::from("hello");
let s2 = s;
println!("{}", s);  // Error: s was moved

// ✅ Clone if needed (but consider if clone is necessary)
let s = String::from("hello");
let s2 = s.clone();
println!("{}", s);  // OK

// ❌ Using clone() to work around the borrow checker (anti-pattern)
fn process(data: &Data) {
    let owned = data.clone();  // unnecessary clone
    do_something(owned);
}

// ✅ Use borrowing correctly
fn process(data: &Data) {
    do_something(data);  // pass a reference
}

// ❌ Storing borrows in a struct (usually a bad idea)
struct Parser<'a> {
    input: &'a str,  // complicates lifetimes
    position: usize,
}

// ✅ Use owned data
struct Parser {
    input: String,  // owns the data, simplifies lifetimes
    position: usize,
}

// ❌ Modifying a collection while iterating it
let mut vec = vec![1, 2, 3];
for item in &vec {
    vec.push(*item);  // Error: cannot borrow as mutable
}

// ✅ Collect into a new collection
let vec = vec![1, 2, 3];
let new_vec: Vec<_> = vec.iter().map(|x| x * 2).collect();
```

### Unsafe Code Review

```rust
// ❌ unsafe without a safety comment
unsafe {
    ptr::write(dest, value);
}

// ✅ Must have a SAFETY comment explaining the invariants
// SAFETY: dest pointer is obtained from Vec::as_mut_ptr(), guaranteeing:
// 1. The pointer is valid and properly aligned
// 2. The target memory is not borrowed by any other reference
// 3. The write does not exceed the allocated capacity
unsafe {
    ptr::write(dest, value);
}

// ❌ unsafe fn without # Safety documentation
pub unsafe fn from_raw_parts(ptr: *mut T, len: usize) -> Self { ... }

// ✅ Must document the safety contract
/// Creates a new instance from raw parts.
///
/// # Safety
///
/// - `ptr` must have been allocated via `GlobalAlloc`
/// - `len` must be less than or equal to the allocated capacity
/// - The caller must ensure no other references to the memory exist
pub unsafe fn from_raw_parts(ptr: *mut T, len: usize) -> Self { ... }

// ❌ Cross-module unsafe invariants
mod a {
    pub fn set_flag() { FLAG = true; }  // safe code affects unsafe behavior
}
mod b {
    pub unsafe fn do_thing() {
        if FLAG { /* assumes FLAG means something */ }
    }
}

// ✅ Encapsulate unsafe boundaries within a single module
mod safe_wrapper {
    // All unsafe logic is in one module
    // Exposes a safe public API
}
```

### Async / Concurrency

```rust
// ❌ Blocking inside an async context
async fn bad_fetch(url: &str) -> Result<String> {
    let resp = reqwest::blocking::get(url)?;  // blocks the entire runtime!
    Ok(resp.text()?)
}

// ✅ Use the async version
async fn good_fetch(url: &str) -> Result<String> {
    let resp = reqwest::get(url).await?;
    Ok(resp.text().await?)
}

// ❌ Holding a Mutex across .await
async fn bad_lock(mutex: &Mutex<Data>) {
    let guard = mutex.lock().unwrap();
    some_async_op().await;  // holding the lock across await!
    drop(guard);
}

// ✅ Minimize the lock scope
async fn good_lock(mutex: &Mutex<Data>) {
    let data = {
        let guard = mutex.lock().unwrap();
        guard.clone()  // release the lock immediately after getting the data
    };
    some_async_op().await;
    // use data
}

// ❌ Using std::sync::Mutex inside an async function
async fn bad_async_mutex(mutex: &std::sync::Mutex<Data>) {
    let _guard = mutex.lock().unwrap();  // potential deadlock
    tokio::time::sleep(Duration::from_secs(1)).await;
}

// ✅ Use tokio::sync::Mutex (if it must be held across .await)
async fn good_async_mutex(mutex: &tokio::sync::Mutex<Data>) {
    let _guard = mutex.lock().await;
    tokio::time::sleep(Duration::from_secs(1)).await;
}

// ❌ Forgetting that Futures are lazy
fn bad_spawn() {
    let future = async_operation();  // not executing!
    // future is dropped, nothing happens
}

// ✅ Must be awaited or spawned
async fn good_spawn() {
    async_operation().await;  // executes
    // or
    tokio::spawn(async_operation());  // runs in the background
}

// ❌ Spawned task missing 'static bound
async fn bad_spawn_lifetime(data: &str) {
    tokio::spawn(async {
        println!("{}", data);  // Error: data is not 'static
    });
}

// ✅ Use move or Arc
async fn good_spawn_lifetime(data: String) {
    tokio::spawn(async move {
        println!("{}", data);  // OK: owns the data
    });
}
```

### Error Handling

```rust
// ❌ Using unwrap/expect in production code
fn bad_parse(input: &str) -> i32 {
    input.parse().unwrap()  // panics!
}

// ✅ Propagate the error correctly
fn good_parse(input: &str) -> Result<i32, ParseIntError> {
    input.parse()
}

// ❌ Swallowing the error message
fn bad_error_handling() -> Result<()> {
    match operation() {
        Ok(v) => Ok(v),
        Err(_) => Err(anyhow!("operation failed"))  // original error is lost
    }
}

// ✅ Use context to add context
fn good_error_handling() -> Result<()> {
    operation().context("failed to perform operation")?;
    Ok(())
}

// ❌ Library code using anyhow (should use thiserror)
// lib.rs
pub fn parse_config(path: &str) -> anyhow::Result<Config> {
    // callers cannot distinguish between error types
}

// ✅ Library code uses thiserror to define error types
#[derive(Debug, thiserror::Error)]
pub enum ConfigError {
    #[error("failed to read config file: {0}")]
    Io(#[from] std::io::Error),
    #[error("invalid config format: {0}")]
    Parse(#[from] serde_json::Error),
}

pub fn parse_config(path: &str) -> Result<Config, ConfigError> {
    // callers can match on different error variants
}

// ❌ Ignoring must_use return values
fn bad_ignore_result() {
    some_fallible_operation();  // warning: unused Result
}

// ✅ Explicitly handle or mark as intentionally ignored
fn good_handle_result() {
    let _ = some_fallible_operation();  // explicitly ignored
    // or
    some_fallible_operation().ok();  // convert to Option
}
```

### Performance Pitfalls

```rust
// ❌ Unnecessary collect
fn bad_process(items: &[i32]) -> i32 {
    items.iter()
        .filter(|x| **x > 0)
        .collect::<Vec<_>>()  // unnecessary allocation
        .iter()
        .sum()
}

// ✅ Lazy iteration
fn good_process(items: &[i32]) -> i32 {
    items.iter()
        .filter(|x| **x > 0)
        .sum()
}

// ❌ Repeated allocations in a loop
fn bad_loop() -> String {
    let mut result = String::new();
    for i in 0..1000 {
        result = result + &i.to_string();  // re-allocates on every iteration!
    }
    result
}

// ✅ Pre-allocate or use push_str
fn good_loop() -> String {
    let mut result = String::with_capacity(4000);  // pre-allocate
    for i in 0..1000 {
        write!(result, "{}", i).unwrap();  // append in place
    }
    result
}

// ❌ Excessive cloning
fn bad_clone(data: &HashMap<String, Vec<u8>>) -> Vec<u8> {
    data.get("key").cloned().unwrap_or_default()
}

// ✅ Return a reference or use Cow
fn good_ref(data: &HashMap<String, Vec<u8>>) -> &[u8] {
    data.get("key").map(|v| v.as_slice()).unwrap_or(&[])
}

// ❌ Large structs passed by value
fn bad_pass(data: LargeStruct) { ... }  // copies the entire struct

// ✅ Pass by reference
fn good_pass(data: &LargeStruct) { ... }

// ❌ Box<dyn Trait> for small, known types
fn bad_trait_object() -> Box<dyn Iterator<Item = i32>> {
    Box::new(vec![1, 2, 3].into_iter())
}

// ✅ Use impl Trait
fn good_impl_trait() -> impl Iterator<Item = i32> {
    vec![1, 2, 3].into_iter()
}
```

### Lifetimes and References

```rust
// ❌ Returning a reference to a local variable
fn bad_return_ref() -> &str {
    let s = String::from("hello");
    &s  // Error: s will be dropped
}

// ✅ Return owned data or a static reference
fn good_return_owned() -> String {
    String::from("hello")
}

// ❌ Over-generalized lifetimes
fn bad_lifetime<'a, 'b>(x: &'a str, y: &'b str) -> &'a str {
    x  // 'b is unused
}

// ✅ Simplified lifetimes
fn good_lifetime(x: &str, _y: &str) -> &str {
    x  // compiler infers lifetimes automatically
}

// ❌ Struct holding multiple related references with independent lifetimes
struct Bad<'a, 'b> {
    name: &'a str,
    data: &'b [u8],  // usually should be the same lifetime
}

// ✅ Related data uses the same lifetime
struct Good<'a> {
    name: &'a str,
    data: &'a [u8],
}
```

### Rust Review Checklist

**Ownership and Borrowing**
- [ ] clone() is intentional, not a borrow checker workaround
- [ ] Avoid storing borrows in structs (unless necessary)
- [ ] Rc/Arc usage is justified; no hidden unnecessary shared state
- [ ] No unnecessary RefCell (runtime checks vs compile-time)

**Unsafe Code**
- [ ] Every unsafe block has a SAFETY comment
- [ ] Every unsafe fn has # Safety documentation
- [ ] Safety invariants are clearly documented
- [ ] Unsafe boundary is as small as possible

**Async / Concurrency**
- [ ] No blocking calls inside async contexts
- [ ] No std::sync locks held across .await
- [ ] Spawned tasks satisfy the 'static constraint
- [ ] Futures are correctly awaited or spawned
- [ ] Lock acquisition order is consistent (avoid deadlocks)

**Error Handling**
- [ ] Library code uses thiserror; application code uses anyhow
- [ ] Errors have sufficient context information
- [ ] No unwrap/expect in production code
- [ ] must_use return values are correctly handled

**Performance**
- [ ] Unnecessary collect() avoided
- [ ] Large data structures passed by reference
- [ ] String concatenation uses String::with_capacity or write!
- [ ] impl Trait preferred over Box<dyn Trait> (where possible)

**Type System**
- [ ] newtype pattern used to increase type safety where appropriate
- [ ] Enum matches are exhaustive (no `_` wildcard hiding new variants)
- [ ] Lifetimes are as simple as possible

## SQL

### Injection Vulnerabilities
```sql
-- ❌ String concatenation (SQL injection risk)
query = "SELECT * FROM users WHERE id = " + user_id

-- ✅ Parameterized queries
query = "SELECT * FROM users WHERE id = ?"
cursor.execute(query, (user_id,))
```

### Performance Issues
- [ ] Missing indexes on filtered/joined columns
- [ ] SELECT * instead of specific columns
- [ ] N+1 query patterns
- [ ] Missing LIMIT on large tables
- [ ] Inefficient subqueries vs JOINs

### Common Mistakes
- [ ] Not handling NULL comparisons correctly
- [ ] Missing transactions for related operations
- [ ] Incorrect JOIN types
- [ ] Case sensitivity issues
- [ ] Date/timezone handling errors

## API Design

### REST Issues
- [ ] Inconsistent resource naming
- [ ] Wrong HTTP methods (POST for idempotent operations)
- [ ] Missing pagination for list endpoints
- [ ] Incorrect status codes
- [ ] Missing rate limiting

### Data Validation
- [ ] Missing input validation
- [ ] Incorrect data type validation
- [ ] Missing length/range checks
- [ ] Not sanitizing user input
- [ ] Trusting client-side validation

## Testing

### Test Quality Issues
- [ ] Testing implementation details instead of behavior
- [ ] Missing edge case tests
- [ ] Flaky tests (non-deterministic)
- [ ] Tests with external dependencies
- [ ] Missing negative tests (error cases)
- [ ] Overly complex test setup

# Performance Review Guide

A performance review guide covering frontend, backend, database, algorithmic complexity, and API performance.

## Table of Contents

- [Frontend Performance (Core Web Vitals)](#frontend-performance-core-web-vitals)
- [JavaScript Performance](#javascript-performance)
- [Memory Management](#memory-management)
- [Database Performance](#database-performance)
- [API Performance](#api-performance)
- [Algorithmic Complexity](#algorithmic-complexity)
- [Performance Review Checklist](#performance-review-checklist)

---

## Frontend Performance (Core Web Vitals)

### 2024 Core Metrics

| Metric | Full Name | Target | Meaning |
|---|---|---|---|
| **LCP** | Largest Contentful Paint | ≤ 2.5s | Time to render the largest visible content |
| **INP** | Interaction to Next Paint | ≤ 200ms | Interaction response time (replaced FID in 2024) |
| **CLS** | Cumulative Layout Shift | ≤ 0.1 | Cumulative layout instability |
| **FCP** | First Contentful Paint | ≤ 1.8s | Time to first visible content |
| **TBT** | Total Blocking Time | ≤ 200ms | Main thread blocking time |

### LCP Optimization Check

```javascript
// ❌ Lazy-loading the LCP image — delays critical content
<img src="hero.jpg" loading="lazy" />

// ✅ Load the LCP image immediately
<img src="hero.jpg" fetchpriority="high" />

// ❌ Unoptimized image format
<img src="hero.png" />  // PNG file is too large

// ✅ Modern image formats + responsive
<picture>
  <source srcset="hero.avif" type="image/avif" />
  <source srcset="hero.webp" type="image/webp" />
  <img src="hero.jpg" alt="Hero" />
</picture>
```

**Review points:**
- [ ] Is the LCP element given `fetchpriority="high"`?
- [ ] Are WebP/AVIF formats used?
- [ ] Is server-side rendering or static generation in use?
- [ ] Is the CDN configured correctly?

### FCP Optimization Check

```html
<!-- ❌ Render-blocking CSS -->
<link rel="stylesheet" href="all-styles.css" />

<!-- ✅ Inline critical CSS + async-load the rest -->
<style>/* above-the-fold critical styles */</style>
<link rel="preload" href="styles.css" as="style" onload="this.onload=null;this.rel='stylesheet'" />

<!-- ❌ Render-blocking fonts -->
@font-face {
  font-family: 'CustomFont';
  src: url('font.woff2');
}

<!-- ✅ Optimized font display -->
@font-face {
  font-family: 'CustomFont';
  src: url('font.woff2');
  font-display: swap;  /* Use system font first, switch when loaded */
}
```

### INP Optimization Check

```javascript
// ❌ Long task blocking the main thread
button.addEventListener('click', () => {
  // 500ms synchronous operation
  processLargeData(data);
  updateUI();
});

// ✅ Split the long task
button.addEventListener('click', async () => {
  // Yield to the main thread
  await scheduler.yield?.() ?? new Promise(r => setTimeout(r, 0));

  // Process in chunks
  for (const chunk of chunks) {
    processChunk(chunk);
    await scheduler.yield?.();
  }
  updateUI();
});

// ✅ Use a Web Worker for heavy computation
const worker = new Worker('heavy-computation.js');
worker.postMessage(data);
worker.onmessage = (e) => updateUI(e.data);
```

### CLS Optimization Check

```css
/* ❌ Media without specified dimensions */
img { width: 100%; }

/* ✅ Reserve space */
img {
  width: 100%;
  aspect-ratio: 16 / 9;
}

/* ❌ Dynamically inserted content causes layout shift */
.ad-container { }

/* ✅ Reserve a fixed height */
.ad-container {
  min-height: 250px;
}
```

**CLS review checklist:**
- [ ] Do images/videos have width/height or aspect-ratio?
- [ ] Do font loads use `font-display: swap`?
- [ ] Is space reserved for dynamic content?
- [ ] Is inserting content above existing content avoided?

---

## JavaScript Performance

### Code Splitting and Lazy Loading

```javascript
// ❌ Load all code at once
import { HeavyChart } from './charts';
import { PDFExporter } from './pdf';
import { AdminPanel } from './admin';

// ✅ Load on demand
const HeavyChart = lazy(() => import('./charts'));
const PDFExporter = lazy(() => import('./pdf'));

// ✅ Route-level code splitting
const routes = [
  {
    path: '/dashboard',
    component: lazy(() => import('./pages/Dashboard')),
  },
  {
    path: '/admin',
    component: lazy(() => import('./pages/Admin')),
  },
];
```

### Bundle Size Optimization

```javascript
// ❌ Importing the entire library
import _ from 'lodash';
import moment from 'moment';

// ✅ Import only what's needed
import debounce from 'lodash/debounce';
import { format } from 'date-fns';

// ❌ Not leveraging Tree Shaking
export default {
  fn1() {},
  fn2() {},  // unused but still bundled
};

// ✅ Named exports support Tree Shaking
export function fn1() {}
export function fn2() {}
```

**Bundle review checklist:**
- [ ] Is dynamic `import()` used for code splitting?
- [ ] Are large libraries imported selectively?
- [ ] Has bundle size been analyzed? (webpack-bundle-analyzer)
- [ ] Are there any unused dependencies?

### List Rendering Optimization

```javascript
// ❌ Rendering a large list
function List({ items }) {
  return (
    <ul>
      {items.map(item => <li key={item.id}>{item.name}</li>)}
    </ul>
  );  // 10,000 items = 10,000 DOM nodes
}

// ✅ Virtual list — only render visible items
import { FixedSizeList } from 'react-window';

function VirtualList({ items }) {
  return (
    <FixedSizeList
      height={400}
      itemCount={items.length}
      itemSize={35}
    >
      {({ index, style }) => (
        <div style={style}>{items[index].name}</div>
      )}
    </FixedSizeList>
  );
}
```

**Large data review points:**
- [ ] Does a list with more than 100 items use virtual scrolling?
- [ ] Does the table support pagination or virtualization?
- [ ] Are there any unnecessary full re-renders?

---

## Memory Management

### Common Memory Leaks

#### 1. Uncleaned Event Listeners

```javascript
// ❌ Event still listening after component unmounts
useEffect(() => {
  window.addEventListener('resize', handleResize);
}, []);

// ✅ Clean up the event listener
useEffect(() => {
  window.addEventListener('resize', handleResize);
  return () => window.removeEventListener('resize', handleResize);
}, []);
```

#### 2. Uncleaned Timers

```javascript
// ❌ Timer not cleaned up
useEffect(() => {
  setInterval(fetchData, 5000);
}, []);

// ✅ Clean up the timer
useEffect(() => {
  const timer = setInterval(fetchData, 5000);
  return () => clearInterval(timer);
}, []);
```

#### 3. Closure References

```javascript
// ❌ Closure holds a reference to a large object
function createHandler() {
  const largeData = new Array(1000000).fill('x');

  return function handler() {
    // largeData is held by the closure and cannot be GC'd
    console.log(largeData.length);
  };
}

// ✅ Keep only the necessary data
function createHandler() {
  const largeData = new Array(1000000).fill('x');
  const length = largeData.length;  // only store what's needed

  return function handler() {
    console.log(length);
  };
}
```

#### 4. Uncleaned Subscriptions

```javascript
// ❌ WebSocket/EventSource not closed
useEffect(() => {
  const ws = new WebSocket('wss://...');
  ws.onmessage = handleMessage;
}, []);

// ✅ Clean up the connection
useEffect(() => {
  const ws = new WebSocket('wss://...');
  ws.onmessage = handleMessage;
  return () => ws.close();
}, []);
```

### Memory Review Checklist

```markdown
- [ ] Do all useEffects have cleanup functions?
- [ ] Are event listeners removed when the component unmounts?
- [ ] Are timers cleaned up?
- [ ] Are WebSocket/SSE connections closed?
- [ ] Are large objects released promptly?
- [ ] Are there global variables accumulating data?
```

### Detection Tools

| Tool | Purpose |
|---|---|
| Chrome DevTools Memory | Heap snapshot analysis |
| MemLab (Meta) | Automated memory leak detection |
| Performance Monitor | Real-time memory monitoring |

---

## Database Performance

### N+1 Query Problem

```python
# ❌ N+1 problem — 1 + N queries
users = User.objects.all()  # 1 query
for user in users:
    print(user.profile.bio)  # N queries (one per user)

# ✅ Eager Loading — 2 queries
users = User.objects.select_related('profile').all()
for user in users:
    print(user.profile.bio)  # no extra queries

# ✅ Many-to-many relationships use prefetch_related
posts = Post.objects.prefetch_related('tags').all()
```

```javascript
// TypeORM example
// ❌ N+1 problem
const users = await userRepository.find();
for (const user of users) {
  const posts = await user.posts;  // queries on every iteration
}

// ✅ Eager Loading
const users = await userRepository.find({
  relations: ['posts'],
});
```

### Index Optimization

```sql
-- ❌ Full table scan
SELECT * FROM orders WHERE status = 'pending';

-- ✅ Add an index
CREATE INDEX idx_orders_status ON orders(status);

-- ❌ Index invalidated by function call
SELECT * FROM users WHERE YEAR(created_at) = 2024;

-- ✅ Range query can use the index
SELECT * FROM users
WHERE created_at >= '2024-01-01' AND created_at < '2025-01-01';

-- ❌ Index invalidated by leading wildcard in LIKE
SELECT * FROM products WHERE name LIKE '%phone%';

-- ✅ Prefix match can use the index
SELECT * FROM products WHERE name LIKE 'phone%';
```

### Query Optimization

```sql
-- ❌ SELECT * fetches unneeded columns
SELECT * FROM users WHERE id = 1;

-- ✅ Select only needed columns
SELECT id, name, email FROM users WHERE id = 1;

-- ❌ Large table without LIMIT
SELECT * FROM logs WHERE type = 'error';

-- ✅ Paginated query
SELECT * FROM logs WHERE type = 'error' LIMIT 100 OFFSET 0;

-- ❌ Queries inside a loop
for id in user_ids:
    cursor.execute("SELECT * FROM users WHERE id = %s", (id,))

-- ✅ Batch query
cursor.execute("SELECT * FROM users WHERE id IN %s", (tuple(user_ids),))
```

### Database Review Checklist

```markdown
🔴 Must check:
- [ ] Are there N+1 queries?
- [ ] Do columns in WHERE clauses have indexes?
- [ ] Is SELECT * avoided?
- [ ] Do large table queries have LIMIT?

🟡 Should check:
- [ ] Has EXPLAIN been used to analyze query plans?
- [ ] Is the column order in composite indexes correct?
- [ ] Are there unused indexes?
- [ ] Is slow query logging monitored?
```

---

## API Performance

### Pagination

```javascript
// ❌ Return all data
app.get('/users', async (req, res) => {
  const users = await User.findAll();  // may return 100,000 records
  res.json(users);
});

// ✅ Pagination + enforce max limit
app.get('/users', async (req, res) => {
  const page = parseInt(req.query.page) || 1;
  const limit = Math.min(parseInt(req.query.limit) || 20, 100);  // max 100
  const offset = (page - 1) * limit;

  const { rows, count } = await User.findAndCountAll({
    limit,
    offset,
    order: [['id', 'ASC']],
  });

  res.json({
    data: rows,
    pagination: {
      page,
      limit,
      total: count,
      totalPages: Math.ceil(count / limit),
    },
  });
});
```

### Caching Strategy

```javascript
// ✅ Redis caching example
async function getUser(id) {
  const cacheKey = `user:${id}`;

  // 1. Check cache
  const cached = await redis.get(cacheKey);
  if (cached) {
    return JSON.parse(cached);
  }

  // 2. Query the database
  const user = await db.users.findById(id);

  // 3. Write to cache (with expiry)
  await redis.setex(cacheKey, 3600, JSON.stringify(user));

  return user;
}

// ✅ HTTP cache headers
app.get('/static-data', (req, res) => {
  res.set({
    'Cache-Control': 'public, max-age=86400',  // 24 hours
    'ETag': 'abc123',
  });
  res.json(data);
});
```

### Response Compression

```javascript
// ✅ Enable Gzip/Brotli compression
const compression = require('compression');
app.use(compression());

// ✅ Return only necessary fields
// Request: GET /users?fields=id,name,email
app.get('/users', async (req, res) => {
  const fields = req.query.fields?.split(',') || ['id', 'name'];
  const users = await User.findAll({
    attributes: fields,
  });
  res.json(users);
});
```

### Rate Limiting

```javascript
// ✅ Rate limiting
const rateLimit = require('express-rate-limit');

const limiter = rateLimit({
  windowMs: 60 * 1000,  // 1 minute
  max: 100,             // max 100 requests
  message: { error: 'Too many requests, please try again later.' },
});

app.use('/api/', limiter);
```

### API Review Checklist

```markdown
- [ ] Do list endpoints support pagination?
- [ ] Is a max page size enforced?
- [ ] Are hot data paths cached?
- [ ] Is response compression enabled?
- [ ] Is rate limiting in place?
- [ ] Are only necessary fields returned?
```

---

## Algorithmic Complexity

### Common Complexity Comparison

| Complexity | Name | 10 items | 1,000 items | 1M items | Example |
|---|---|---|---|---|---|
| O(1) | Constant | 1 | 1 | 1 | Hash lookup |
| O(log n) | Logarithmic | 3 | 10 | 20 | Binary search |
| O(n) | Linear | 10 | 1,000 | 1M | Array traversal |
| O(n log n) | Linearithmic | 33 | 10,000 | 20M | Quicksort |
| O(n²) | Quadratic | 100 | 1M | 1 trillion | Nested loops |
| O(2ⁿ) | Exponential | 1,024 | ∞ | ∞ | Recursive Fibonacci |

### Identifying Issues in Code Review

```javascript
// ❌ O(n²) — nested loops
function findDuplicates(arr) {
  const duplicates = [];
  for (let i = 0; i < arr.length; i++) {
    for (let j = i + 1; j < arr.length; j++) {
      if (arr[i] === arr[j]) {
        duplicates.push(arr[i]);
      }
    }
  }
  return duplicates;
}

// ✅ O(n) — using a Set
function findDuplicates(arr) {
  const seen = new Set();
  const duplicates = new Set();
  for (const item of arr) {
    if (seen.has(item)) {
      duplicates.add(item);
    }
    seen.add(item);
  }
  return [...duplicates];
}
```

```javascript
// ❌ O(n²) — calling includes inside a loop
function removeDuplicates(arr) {
  const result = [];
  for (const item of arr) {
    if (!result.includes(item)) {  // includes is O(n)
      result.push(item);
    }
  }
  return result;
}

// ✅ O(n) — using a Set
function removeDuplicates(arr) {
  return [...new Set(arr)];
}
```

```javascript
// ❌ O(n) lookup — iterating every time
const users = [{ id: 1, name: 'A' }, { id: 2, name: 'B' }, ...];

function getUser(id) {
  return users.find(u => u.id === id);  // O(n)
}

// ✅ O(1) lookup — using a Map
const userMap = new Map(users.map(u => [u.id, u]));

function getUser(id) {
  return userMap.get(id);  // O(1)
}
```

### Space Complexity Considerations

```javascript
// ⚠️ O(n) space — creates a new array
const doubled = arr.map(x => x * 2);

// ✅ O(1) space — in-place modification (if allowed)
for (let i = 0; i < arr.length; i++) {
  arr[i] *= 2;
}

// ⚠️ Deep recursion may cause a stack overflow
function factorial(n) {
  if (n <= 1) return 1;
  return n * factorial(n - 1);  // O(n) stack space
}

// ✅ Iterative version — O(1) space
function factorial(n) {
  let result = 1;
  for (let i = 2; i <= n; i++) {
    result *= i;
  }
  return result;
}
```

### Complexity Review Comments

```markdown
💡 "This nested loop has O(n²) complexity — will be a problem at scale"
🔴 "Array.includes() is used inside a loop, making this O(n²) overall — use a Set instead"
🟡 "This recursion depth could cause a stack overflow — consider iterative or tail-recursive approach"
```

---

## Performance Review Checklist

### 🔴 Must Check (Blocking)

**Frontend:**
- [ ] Is the LCP image lazy-loaded? (it shouldn't be)
- [ ] Is `transition: all` used?
- [ ] Are width/height/top/left being animated?
- [ ] Are lists with >100 items virtualized?

**Backend:**
- [ ] Are there N+1 queries?
- [ ] Do list endpoints have pagination?
- [ ] Is SELECT * used on large tables?

**General:**
- [ ] Are there O(n²) or worse nested loops?
- [ ] Do useEffects/event listeners have cleanup?

### 🟡 Should Check (Important)

**Frontend:**
- [ ] Is code splitting used?
- [ ] Are large libraries imported selectively?
- [ ] Are images in WebP/AVIF format?
- [ ] Are there unused dependencies?

**Backend:**
- [ ] Is hot data cached?
- [ ] Do WHERE clause columns have indexes?
- [ ] Is slow query monitoring in place?

**API:**
- [ ] Is response compression enabled?
- [ ] Is rate limiting in place?
- [ ] Are only necessary fields returned?

### 🟢 Optimization Suggestions

- [ ] Has bundle size been analyzed?
- [ ] Is a CDN being used?
- [ ] Is performance monitoring in place?
- [ ] Have performance benchmarks been run?

---

## Performance Measurement Thresholds

### Frontend Metrics

| Metric | Good | Needs Improvement | Poor |
|---|---|---|---|
| LCP | ≤ 2.5s | 2.5–4s | > 4s |
| INP | ≤ 200ms | 200–500ms | > 500ms |
| CLS | ≤ 0.1 | 0.1–0.25 | > 0.25 |
| FCP | ≤ 1.8s | 1.8–3s | > 3s |
| Bundle Size (JS) | < 200KB | 200–500KB | > 500KB |

### Backend Metrics

| Metric | Good | Needs Improvement | Poor |
|---|---|---|---|
| API response time | < 100ms | 100–500ms | > 500ms |
| Database query | < 50ms | 50–200ms | > 200ms |
| Page load | < 3s | 3–5s | > 5s |
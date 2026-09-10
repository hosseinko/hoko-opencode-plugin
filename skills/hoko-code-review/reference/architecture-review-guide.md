# Architecture Review Guide

A guide for reviewing architectural design, helping evaluate whether code architecture is sound and design is appropriate.

## SOLID Principles Checklist

### S - Single Responsibility Principle (SRP)

**Key checks:**
- Does this class/module have only one reason to change?
- Do all methods in the class serve the same purpose?
- Can this class be described in one sentence to a non-technical person?

**Warning signals in code review:**
```
⚠️ Class name contains generic terms like "And", "Manager", "Handler", "Processor"
⚠️ A class exceeds 200-300 lines of code
⚠️ A class has more than 5-7 public methods
⚠️ Different methods operate on completely different data
```

**Review questions:**
- "What responsibilities does this class have? Can it be split?"
- "If requirement X changes, which methods need to change? What about requirement Y?"

### O - Open/Closed Principle (OCP)

**Key checks:**
- Does adding new functionality require modifying existing code?
- Can new behavior be added through extension (inheritance, composition)?
- Are there large chains of if/else or switch statements handling different types?

**Warning signals in code review:**
```
⚠️ switch/if-else chains handling different types
⚠️ Adding new features requires modifying core classes
⚠️ Type checks (instanceof, typeof) scattered throughout the code
```

**Review questions:**
- "If we add a new type X, which files need to be modified?"
- "Will this switch statement grow as new types are added?"

### L - Liskov Substitution Principle (LSP)

**Key checks:**
- Can subclasses fully substitute parent classes?
- Do subclasses change the expected behavior of parent class methods?
- Do subclasses throw exceptions not declared by the parent class?

**Warning signals in code review:**
```
⚠️ Explicit type casting
⚠️ Subclass methods throw NotImplementedException
⚠️ Subclass methods are empty or only contain return
⚠️ Code using the base class needs to check concrete types
```

**Review questions:**
- "If we replace the parent class with a subclass, does caller code need to change?"
- "Does this method's behavior in the subclass comply with the parent class contract?"

### I - Interface Segregation Principle (ISP)

**Key checks:**
- Are interfaces small and focused enough?
- Are implementing classes forced to implement methods they don't need?
- Do clients depend on methods they don't use?

**Warning signals in code review:**
```
⚠️ Interface has more than 5-7 methods
⚠️ Implementing classes have empty methods or throw NotImplementedException
⚠️ Interface names are too broad (IManager, IService)
⚠️ Different clients only use a subset of the interface's methods
```

**Review questions:**
- "Are all methods in this interface used by every implementing class?"
- "Can this large interface be split into smaller, specialized interfaces?"

### D - Dependency Inversion Principle (DIP)

**Key checks:**
- Do high-level modules depend on abstractions rather than concrete implementations?
- Is dependency injection used instead of direct `new` instantiation?
- Are abstractions defined by high-level modules rather than low-level ones?

**Warning signals in code review:**
```
⚠️ High-level modules directly instantiate concrete low-level classes
⚠️ Importing concrete implementation classes instead of interfaces/abstract classes
⚠️ Configuration and connection strings hardcoded in business logic
⚠️ Difficult to write unit tests for a class
```

**Review questions:**
- "Can this class's dependencies be replaced with mocks in tests?"
- "If we need to swap the database/API implementation, how many places need to change?"

---

## Architecture Anti-Pattern Recognition

### Critical Anti-Patterns

| Anti-Pattern | Warning Signals | Impact |
|---|---|---|
| **Big Ball of Mud** | No clear module boundaries; any code can call any other code | Hard to understand, modify, and test |
| **God Object** | A single class takes on too many responsibilities, knows too much, does too much | High coupling, hard to reuse and test |
| **Spaghetti Code** | Chaotic control flow, goto or deep nesting, hard to trace execution paths | Hard to understand and maintain |
| **Lava Flow** | Ancient code nobody dares to touch, lacking documentation and tests | Accumulating technical debt |

### Design Anti-Patterns

| Anti-Pattern | Warning Signals | Recommendation |
|---|---|---|
| **Golden Hammer** | Using the same technology/pattern for every problem | Choose the right solution for the problem |
| **Over-Engineering (Gas Factory)** | Solving simple problems with complex solutions, abusing design patterns | YAGNI principle — start simple, add complexity as needed |
| **Boat Anchor** | Unused code written for "future possible needs" | Delete unused code; write it when needed |
| **Copy-Paste Programming** | Same logic appearing in multiple places | Extract into a shared method or module |

### Review Comment Examples

```markdown
🔴 [blocking] "This class has 2000 lines of code; recommend splitting into multiple focused classes"
🟡 [important] "This logic is duplicated in 3 places; consider extracting it into a shared method?"
💡 [suggestion] "This switch statement could be replaced with the Strategy pattern for easier extensibility"
```

---

## Coupling and Cohesion Assessment

### Types of Coupling (best to worst)

| Type | Description | Example |
|---|---|---|
| **Message coupling** ✅ | Data passed via parameters | `calculate(price, quantity)` |
| **Data coupling** ✅ | Sharing simple data structures | `processOrder(orderDTO)` |
| **Stamp coupling** ⚠️ | Sharing complex data structures but using only part of them | Passing full User object but only using name |
| **Control coupling** ⚠️ | Passing control flags that affect behavior | `process(data, isAdmin=true)` |
| **Common coupling** ❌ | Sharing global variables | Multiple modules reading/writing the same global state |
| **Content coupling** ❌ | Directly accessing another module's internals | Directly manipulating another class's private attributes |

### Types of Cohesion (best to worst)

| Type | Description | Quality |
|---|---|---|
| **Functional cohesion** | All elements complete a single task | ✅ Best |
| **Sequential cohesion** | Output of one step is input to the next | ✅ Good |
| **Communicational cohesion** | Operate on the same data | ⚠️ Acceptable |
| **Temporal cohesion** | Tasks that execute at the same time | ⚠️ Poor |
| **Logical cohesion** | Logically related but functionally different | ❌ Bad |
| **Coincidental cohesion** | No obvious relationship | ❌ Worst |

### Reference Metrics

```yaml
Coupling Metrics:
  CBO (Coupling Between Objects):
    Good: < 5
    Warning: 5-10
    Danger: > 10

  Ce (Efferent Coupling):
    Description: How many external classes this class depends on
    Good: < 7

  Ca (Afferent Coupling):
    Description: How many classes depend on this class
    High value means: Changes have broad impact; needs to be stable

Cohesion Metrics:
  LCOM4 (Lack of Cohesion in Methods):
    1: Single responsibility ✅
    2-3: May need splitting ⚠️
    >3: Should be split ❌
```

### Review Questions

- "How many other modules does this module depend on? Can it be reduced?"
- "How many other places will be affected by changing this class?"
- "Do all methods in this class operate on the same data?"

---

## Layered Architecture Review

### Clean Architecture Layer Check

```
┌─────────────────────────────────────┐
│         Frameworks & Drivers        │ ← Outermost: Web, DB, UI
├─────────────────────────────────────┤
│         Interface Adapters          │ ← Controllers, Gateways, Presenters
├─────────────────────────────────────┤
│          Application Layer          │ ← Use Cases, Application Services
├─────────────────────────────────────┤
│            Domain Layer             │ ← Entities, Domain Services
└─────────────────────────────────────┘
          ↑ Dependencies point inward only ↑
```

### Dependency Rule Check

**Core rule: Source code dependencies can only point inward**

```typescript
// ❌ Violates dependency rule: Domain layer depends on Infrastructure
// domain/User.ts
import { MySQLConnection } from '../infrastructure/database';

// ✅ Correct: Domain layer defines interface, Infrastructure implements it
// domain/UserRepository.ts (interface)
interface UserRepository {
  findById(id: string): Promise<User>;
}

// infrastructure/MySQLUserRepository.ts (implementation)
class MySQLUserRepository implements UserRepository {
  findById(id: string): Promise<User> { /* ... */ }
}
```

### Review Checklist

**Layer boundary checks:**
- [ ] Does the Domain layer have external dependencies (database, HTTP, file system)?
- [ ] Does the Application layer directly access the database or call external APIs?
- [ ] Does the Controller contain business logic?
- [ ] Are there cross-layer calls (UI directly calling Repository)?

**Separation of concerns checks:**
- [ ] Is business logic separated from presentation logic?
- [ ] Is data access encapsulated in a dedicated layer?
- [ ] Is configuration and environment-specific code centrally managed?

### Review Comment Examples

```markdown
🔴 [blocking] "Domain entity directly imports a database connection, violating the dependency rule"
🟡 [important] "Controller contains business calculation logic; recommend moving it to the Service layer"
💡 [suggestion] "Consider using dependency injection to decouple these components"
```

---

## Design Pattern Usage Assessment

### When to Use Design Patterns

| Pattern | Use Case | When NOT to Use |
|---|---|---|
| **Factory** | Need to create different types of objects; type determined at runtime | Only one type, or types are fixed |
| **Strategy** | Algorithm needs to switch at runtime; multiple interchangeable behaviors | Only one algorithm, or it never changes |
| **Observer** | One-to-many dependency; state change needs to notify multiple objects | Simple direct calls satisfy the requirement |
| **Singleton** | Truly need a globally unique instance, e.g. configuration management | Objects that can be passed via dependency injection |
| **Decorator** | Need to dynamically add responsibilities; avoid inheritance explosion | Responsibilities are fixed; no dynamic composition needed |

### Over-Engineering Warning Signals

```
⚠️ Patternitis warning signals:

1. Simple if/else replaced by Strategy + Factory + Registry
2. Interfaces with only one implementation
3. Abstraction layers added for "possible future needs"
4. Line count significantly increases due to pattern application
5. New team members take a long time to understand the code structure
```

### Review Principles

```markdown
✅ Correct pattern usage:
- Solves a real extensibility problem
- Code is easier to understand and test
- Adding new features becomes simpler

❌ Overuse of patterns:
- Used for the sake of using a pattern
- Adds unnecessary complexity
- Violates the YAGNI principle
```

### Review Questions

- "What specific problem does this pattern solve?"
- "What would be wrong with the code without this pattern?"
- "Does the value of this abstraction layer outweigh its complexity cost?"

---

## Scalability Assessment

### Scalability Checklist

**Feature scalability:**
- [ ] Does adding new features require modifying core code?
- [ ] Are extension points provided (hooks, plugins, events)?
- [ ] Is configuration externalized (config files, environment variables)?

**Data scalability:**
- [ ] Does the data model support adding new fields?
- [ ] Is data volume growth accounted for?
- [ ] Do queries have appropriate indexes?

**Load scalability:**
- [ ] Can the system scale horizontally (adding more instances)?
- [ ] Are there state dependencies (sessions, local caches)?
- [ ] Do database connections use connection pooling?

### Extension Point Design Check

```typescript
// ✅ Good extensible design: using events/hooks
class OrderService {
  private hooks: OrderHooks;

  async createOrder(order: Order) {
    await this.hooks.beforeCreate?.(order);
    const result = await this.save(order);
    await this.hooks.afterCreate?.(result);
    return result;
  }
}

// ❌ Poor extensible design: hardcoded behavior
class OrderService {
  async createOrder(order: Order) {
    await this.sendEmail(order);        // hardcoded
    await this.updateInventory(order);  // hardcoded
    await this.notifyWarehouse(order);  // hardcoded
    return await this.save(order);
  }
}
```

### Review Comment Examples

```markdown
💡 [suggestion] "If support for a new payment method is needed in the future, is this design easy to extend?"
🟡 [important] "This logic is hardcoded; consider using configuration or the Strategy pattern?"
📚 [learning] "Event-driven architecture could make this feature much easier to extend"
```

---

## Code Structure Best Practices

### Directory Organization

**Organized by feature/domain (recommended):**
```
src/
├── user/
│   ├── User.ts           (entity)
│   ├── UserService.ts    (service)
│   ├── UserRepository.ts (data access)
│   └── UserController.ts (API)
├── order/
│   ├── Order.ts
│   ├── OrderService.ts
│   └── ...
└── shared/
    ├── utils/
    └── types/
```

**Organized by technical layer (not recommended):**
```
src/
├── controllers/     ← different domains mixed together
│   ├── UserController.ts
│   └── OrderController.ts
├── services/
├── repositories/
└── models/
```

### Naming Convention Check

| Type | Convention | Example |
|---|---|---|
| Class name | PascalCase, noun | `UserService`, `OrderRepository` |
| Method name | camelCase, verb | `createUser`, `findOrderById` |
| Constant | UPPER_SNAKE_CASE | `MAX_RETRY_COUNT` |
| Private attribute | Underscore prefix or none | `_cache` or `#cache` |

### File Size Guidelines

```yaml
Recommended limits:
  Single file: < 300 lines
  Single function: < 50 lines
  Single class: < 200 lines
  Function parameters: < 4
  Nesting depth: < 4 levels

When limits are exceeded:
  - Consider splitting into smaller units
  - Use composition over inheritance
  - Extract helper functions or classes
```

### Review Comment Examples

```markdown
🟢 [nit] "This 500-line file could be split by responsibility"
🟡 [important] "Recommend organizing directory structure by feature domain rather than technical layer"
💡 [suggestion] "Function name `process` is unclear; consider renaming to `calculateOrderTotal`?"
```

---

## Quick Reference Checklist

### 5-Minute Architecture Review

```markdown
□ Are dependencies pointing in the correct direction? (outer layers depend on inner layers)
□ Are there any circular dependencies?
□ Is core business logic decoupled from frameworks/UI/databases?
□ Are SOLID principles followed?
□ Are there any obvious anti-patterns?
```

### Red Flags (Must Address)

```markdown
🔴 God Object — single class exceeds 1000 lines
🔴 Circular dependency — A → B → C → A
🔴 Domain layer contains framework dependencies
🔴 Hardcoded configuration and secrets
🔴 External service calls without interfaces
```

### Yellow Flags (Should Address)

```markdown
🟡 Coupling Between Objects (CBO) > 10
🟡 Method has more than 5 parameters
🟡 Nesting depth exceeds 4 levels
🟡 Duplicate code blocks > 10 lines
🟡 Interfaces with only one implementation
```
# PHP Code Review Guide

> A PHP code review guide.

## Table of Contents

- [Data Modeling](#data-modeling)
- [PHP Review Checklist](#php-review-checklist)

---

## Data Modeling

Prefer typed models (value objects, DTOs, `JsonSerializable` responses) over associative arrays for domain data; reserve arrays for transient, internal projections.

### Return Models, Not Arrays

```php
// ❌ Untyped contract — a phpdoc shape the type system never enforces
/** @return array<string, list<array{id: int, label: ?string}>> */
public function getCatalog(): array

// ✅ A model — the constructor enforces the type, callers get a real API
public function getCatalog(): Catalog;
```

### Dynamic-Keyed Responses

```php
// ❌ Runtime keys in a plain array — no contract, and an empty result
//    serializes as [] instead of {}
public function groupByCategory(): array

// ✅ A model owns the shape and its serialization (empty → {})
final class CategoryGroups implements JsonSerializable
{
    private stdClass $groups;
    public function jsonSerialize(): stdClass { return $this->groups; }
}
```

### When a Typed Array Is Acceptable

```php
// ✅ Transient projection consumed by the very next method
/** @return list<array{name: string, id: int}> */
private function fetchRows(): array

// ✅ Simple lookup map
/** @return array<int, string> */   // id => name

// ❌ Bare array with no shape — always specify array{...} / list<...>
public function getThings(): array
```

## PHP Review Checklist

- [ ] Public methods return models / value objects / DTOs, not associative arrays
- [ ] Dynamic-keyed responses use a model (empty → `{}`, not `[]`)
- [ ] Serialization owned by the model, not patched at the call site
- [ ] No `array` return type without a precise `array{...}` / `list<...>` shape
- [ ] Typed arrays only for transient projections / lookup maps

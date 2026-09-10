# CSS / Less / Sass Review Guide

A guide for reviewing CSS and preprocessor code, covering performance, maintainability, responsive design, and browser compatibility.

## CSS Variables vs. Hard-Coded Values

### When to Use Variables

```css
/* ❌ Hard-coded — difficult to maintain */
.button {
  background: #3b82f6;
  border-radius: 8px;
}
.card {
  border: 1px solid #3b82f6;
  border-radius: 8px;
}

/* ✅ Use CSS variables */
:root {
  --color-primary: #3b82f6;
  --radius-md: 8px;
}
.button {
  background: var(--color-primary);
  border-radius: var(--radius-md);
}
.card {
  border: 1px solid var(--color-primary);
  border-radius: var(--radius-md);
}
```

### Variable Naming Conventions

```css
/* Recommended variable categories */
:root {
  /* Colors */
  --color-primary: #3b82f6;
  --color-primary-hover: #2563eb;
  --color-text: #1f2937;
  --color-text-muted: #6b7280;
  --color-bg: #ffffff;
  --color-border: #e5e7eb;

  /* Spacing */
  --spacing-xs: 4px;
  --spacing-sm: 8px;
  --spacing-md: 16px;
  --spacing-lg: 24px;
  --spacing-xl: 32px;

  /* Typography */
  --font-size-sm: 14px;
  --font-size-base: 16px;
  --font-size-lg: 18px;
  --font-weight-normal: 400;
  --font-weight-bold: 700;

  /* Border radius */
  --radius-sm: 4px;
  --radius-md: 8px;
  --radius-lg: 12px;
  --radius-full: 9999px;

  /* Shadows */
  --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.05);
  --shadow-md: 0 4px 6px rgba(0, 0, 0, 0.1);

  /* Transitions */
  --transition-fast: 150ms ease;
  --transition-normal: 300ms ease;
}
```

### Variable Scope Recommendations

```css
/* ✅ Component-level variables — reduce global pollution */
.card {
  --card-padding: var(--spacing-md);
  --card-radius: var(--radius-md);

  padding: var(--card-padding);
  border-radius: var(--card-radius);
}

/* ⚠️ Avoid frequent JS-driven dynamic variable updates — impacts performance */
```

### Review Checklist

- [ ] Are color values using variables?
- [ ] Does spacing come from a design system?
- [ ] Are repeated values extracted into variables?
- [ ] Are variable names semantically meaningful?

---

## !important Usage Rules

### When It's Acceptable

```css
/* ✅ Utility classes — intentional override */
.hidden { display: none !important; }
.sr-only { position: absolute !important; }

/* ✅ Overriding third-party library styles (when source is inaccessible) */
.third-party-modal {
  z-index: 9999 !important;
}

/* ✅ Print styles */
@media print {
  .no-print { display: none !important; }
}
```

### When It's Prohibited

```css
/* ❌ Fixing specificity issues — refactor the selector instead */
.button {
  background: blue !important;  /* Why is !important needed here? */
}

/* ❌ Overriding your own styles */
.card { padding: 20px; }
.card { padding: 30px !important; }  /* Just modify the original rule */

/* ❌ Inside component styles */
.my-component .title {
  font-size: 24px !important;  /* Breaks component encapsulation */
}
```

### Alternatives

```css
/* Problem: need to override .btn styles */

/* ❌ Using !important */
.my-btn {
  background: red !important;
}

/* ✅ Increase specificity */
button.my-btn {
  background: red;
}

/* ✅ Use a more specific selector */
.container .my-btn {
  background: red;
}

/* ✅ Use :where() to lower the specificity of the style being overridden */
:where(.btn) {
  background: blue;  /* Specificity is 0 */
}
.my-btn {
  background: red;   /* Can override normally */
}
```

### Review Comments

```markdown
🔴 [blocking] "Found 15 uses of !important — please justify each one"
🟡 [important] "This !important can be resolved by adjusting selector specificity"
💡 [suggestion] "Consider using CSS Layers (@layer) to manage style priority"
```

---

## Performance Considerations

### 🔴 High-Risk Performance Issues

#### 1. `transition: all`

```css
/* ❌ Performance killer — browser checks every animatable property */
.button {
  transition: all 0.3s ease;
}

/* ✅ Specify properties explicitly */
.button {
  transition: background-color 0.3s ease, transform 0.3s ease;
}

/* ✅ Use variables for multiple properties */
.button {
  --transition-duration: 0.3s;
  transition:
    background-color var(--transition-duration) ease,
    box-shadow var(--transition-duration) ease,
    transform var(--transition-duration) ease;
}
```

#### 2. Animating box-shadow

```css
/* ❌ Triggers a repaint every frame — seriously impacts performance */
.card {
  box-shadow: 0 2px 4px rgba(0,0,0,0.1);
  transition: box-shadow 0.3s ease;
}
.card:hover {
  box-shadow: 0 8px 16px rgba(0,0,0,0.2);
}

/* ✅ Use pseudo-element + opacity instead */
.card {
  position: relative;
}
.card::after {
  content: '';
  position: absolute;
  inset: 0;
  box-shadow: 0 8px 16px rgba(0,0,0,0.2);
  opacity: 0;
  transition: opacity 0.3s ease;
  pointer-events: none;
  border-radius: inherit;
}
.card:hover::after {
  opacity: 1;
}
```

#### 3. Layout-Triggering Properties (Reflow)

```css
/* ❌ Animating these properties triggers layout recalculation */
.bad-animation {
  transition: width 0.3s, height 0.3s, top 0.3s, left 0.3s, margin 0.3s;
}

/* ✅ Only animate transform and opacity (compositor-only) */
.good-animation {
  transition: transform 0.3s, opacity 0.3s;
}

/* Use translate instead of top/left */
.move {
  transform: translateX(100px);  /* ✅ */
  /* left: 100px; */             /* ❌ */
}

/* Use scale instead of width/height */
.grow {
  transform: scale(1.1);  /* ✅ */
  /* width: 110%; */       /* ❌ */
}
```

### 🟡 Moderate Performance Issues

#### Complex Selectors

```css
/* ❌ Deep nesting — slow selector matching */
.page .container .content .article .section .paragraph span {
  color: red;
}

/* ✅ Flatten it */
.article-text {
  color: red;
}

/* ❌ Wildcard selectors */
* { box-sizing: border-box; }           /* Affects every element */
[class*="icon-"] { display: inline; }   /* Attribute selectors are slower */

/* ✅ Limit the scope */
.icon-box * { box-sizing: border-box; }
```

#### Heavy Shadows and Filters

```css
/* ⚠️ Complex shadows impact rendering performance */
.heavy-shadow {
  box-shadow:
    0 1px 2px rgba(0,0,0,0.1),
    0 2px 4px rgba(0,0,0,0.1),
    0 4px 8px rgba(0,0,0,0.1),
    0 8px 16px rgba(0,0,0,0.1),
    0 16px 32px rgba(0,0,0,0.1);  /* 5 layers of shadow */
}

/* ⚠️ Filters consume GPU resources */
.blur-heavy {
  filter: blur(20px) brightness(1.2) contrast(1.1);
  backdrop-filter: blur(10px);  /* Even more expensive */
}
```

### Performance Optimization Tips

```css
/* Use will-change to hint the browser (use sparingly) */
.animated-element {
  will-change: transform, opacity;
}

/* Remove will-change after animation completes */
.animated-element.idle {
  will-change: auto;
}

/* Use contain to limit repaint scope */
.card {
  contain: layout paint;  /* Tells the browser internal changes don't affect outside */
}
```

### Review Checklist

- [ ] Is `transition: all` used?
- [ ] Are width/height/top/left being animated?
- [ ] Is box-shadow being animated?
- [ ] Does selector nesting exceed 3 levels?
- [ ] Is `will-change` used unnecessarily?

---

## Responsive Design Checkpoints

### Mobile First Principle

```css
/* ✅ Mobile First — base styles target mobile */
.container {
  padding: 16px;
  display: flex;
  flex-direction: column;
}

/* Progressive enhancement */
@media (min-width: 768px) {
  .container {
    padding: 24px;
    flex-direction: row;
  }
}

@media (min-width: 1024px) {
  .container {
    padding: 32px;
    max-width: 1200px;
    margin: 0 auto;
  }
}

/* ❌ Desktop First — requires more overrides */
.container {
  max-width: 1200px;
  padding: 32px;
  flex-direction: row;
}

@media (max-width: 1023px) {
  .container {
    padding: 24px;
  }
}

@media (max-width: 767px) {
  .container {
    padding: 16px;
    flex-direction: column;
    max-width: none;
  }
}
```

### Breakpoint Recommendations

```css
/* Recommended breakpoints (based on content, not devices) */
:root {
  --breakpoint-sm: 640px;   /* Large phones */
  --breakpoint-md: 768px;   /* Portrait tablets */
  --breakpoint-lg: 1024px;  /* Landscape tablets / small laptops */
  --breakpoint-xl: 1280px;  /* Desktop */
  --breakpoint-2xl: 1536px; /* Large desktop */
}

/* Usage */
@media (min-width: 768px) { /* md */ }
@media (min-width: 1024px) { /* lg */ }
```

### Responsive Review Checklist

- [ ] Is Mobile First adopted?
- [ ] Are breakpoints based on content breakpoints, not device sizes?
- [ ] Are overlapping breakpoints avoided?
- [ ] Does text use relative units (rem/em)?
- [ ] Are touch targets large enough (≥44px)?
- [ ] Has portrait/landscape switching been tested?

### Common Issues

```css
/* ❌ Fixed width */
.container {
  width: 1200px;
}

/* ✅ Max-width + fluid */
.container {
  width: 100%;
  max-width: 1200px;
  padding-inline: 16px;
}

/* ❌ Fixed-height text containers */
.text-box {
  height: 100px;  /* Text may overflow */
}

/* ✅ Min-height instead */
.text-box {
  min-height: 100px;
}

/* ❌ Small touch targets */
.small-button {
  padding: 4px 8px;  /* Too small, hard to tap */
}

/* ✅ Adequate touch area */
.touch-button {
  min-height: 44px;
  min-width: 44px;
  padding: 12px 16px;
}
```

---

## Browser Compatibility

### Features to Check

| Feature | Compatibility | Recommendation |
|---|---|---|
| CSS Grid | Modern browsers ✅ | IE needs Autoprefixer + testing |
| Flexbox | Widely supported ✅ | Older versions need prefixes |
| CSS Variables | Modern browsers ✅ | IE unsupported, needs fallback |
| `gap` (flexbox) | Newer ⚠️ | Safari 14.1+ |
| `:has()` | Newer ⚠️ | Firefox 121+ |
| `container queries` | Newer ⚠️ | Browsers from 2023+ |
| `@layer` | Newer ⚠️ | Check target browsers |

### Fallback Strategies

```css
/* CSS variable fallback */
.button {
  background: #3b82f6;              /* Fallback value */
  background: var(--color-primary); /* Modern browsers */
}

/* Flexbox gap fallback */
.flex-container {
  display: flex;
  gap: 16px;
}
/* Old browser fallback */
.flex-container > * + * {
  margin-left: 16px;
}

/* Grid fallback */
.grid {
  display: flex;
  flex-wrap: wrap;
}
@supports (display: grid) {
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  }
}
```

### Autoprefixer Configuration

```javascript
// postcss.config.js
module.exports = {
  plugins: [
    require('autoprefixer')({
      // Based on browserslist config
      grid: 'autoplace',  // Enable Grid prefixes (IE support)
      flexbox: 'no-2009', // Modern flexbox syntax only
    }),
  ],
};

// package.json
{
  "browserslist": [
    "> 1%",
    "last 2 versions",
    "not dead",
    "not ie 11"  // Adjust per project requirements
  ]
}
```

### Review Checklist

- [ ] Has [Can I Use](https://caniuse.com) been checked?
- [ ] Do new features have fallback strategies?
- [ ] Is Autoprefixer configured?
- [ ] Does the browserslist match project requirements?
- [ ] Has it been tested in target browsers?

---

## Less / Sass Specific Issues

### Nesting Depth

```scss
/* ❌ Deep nesting — generates overly long compiled selectors */
.page {
  .container {
    .content {
      .article {
        .title {
          color: red;  // Compiles to .page .container .content .article .title
        }
      }
    }
  }
}

/* ✅ Maximum 3 levels */
.article {
  &__title {
    color: red;
  }

  &__content {
    p { margin-bottom: 1em; }
  }
}
```

### Mixin vs Extend vs Variables

```scss
/* Variables — for single values */
$primary-color: #3b82f6;

/* Mixin — for configurable code blocks */
@mixin button-variant($bg, $text) {
  background: $bg;
  color: $text;
  &:hover {
    background: darken($bg, 10%);
  }
}

/* Extend — for sharing identical styles (use with caution) */
%visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
}

.sr-only {
  @extend %visually-hidden;
}

/* ⚠️ Problems with @extend */
// Can produce unexpected selector combinations
// Cannot be used inside @media
// Prefer mixins instead
```

### Review Checklist

- [ ] Does nesting exceed 3 levels?
- [ ] Is @extend overused?
- [ ] Are mixins too complex?
- [ ] Is the compiled CSS size reasonable?

---

## Quick Review Checklist

### 🔴 Must Fix

```markdown
□ transition: all
□ Animating width/height/top/left/margin
□ Excessive use of !important
□ Hard-coded colors/spacing repeated >3 times
□ Selector nesting >4 levels
```

### 🟡 Should Fix

```markdown
□ Missing responsive handling
□ Using Desktop First approach
□ Complex box-shadow being animated
□ Missing browser compatibility fallbacks
□ CSS variable scope too broad
```

### 🟢 Optimization Suggestions

```markdown
□ Could use CSS Grid to simplify layout
□ Could use CSS variables to extract repeated values
□ Could use @layer to manage priority
□ Could add contain for performance optimization
```
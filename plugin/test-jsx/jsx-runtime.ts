/**
 * The JSX runtime bun compiles `status.tsx` through under the test runner. solid-js
 * publishes no automatic runtime — `solid-js/jsx-runtime` resolves to its reactive core,
 * which has no `jsx` — so this produces the plain element tree the test walks with the
 * runtime's own `For` and `Show`. opencode still compiles the same JSX through its Solid
 * plugin, so nothing here reaches a real run.
 */
export function jsx(type: any, props: any) {
  return { type, props: props ?? {} }
}

export const jsxs = jsx
export const jsxDEV = jsx

export function Fragment(props: any) {
  return props.children
}

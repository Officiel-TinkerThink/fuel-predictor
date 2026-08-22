# Presentation layer structure

Apply when adding components, hooks, client state, or render transforms.

## Layout

```
presentation/
├── components/{ui,common,<feature>}/
├── hooks/
├── state/
└── views/
```

## Rules

- Components draw. Hooks wire UI to application intents. Application maps response to view model. Gateways handle HTTP.
- Create discriminated unions for remote/UI states: loading, empty, error, ready, and domain-specific safe states. Avoid independent booleans that permit impossible combinations.
- Separate editable local document state from cached remote data. Define ownership, invalidation, and persistence rules for each state store.
- Render server-provided facts and decisions. Presentation may sort/filter for display only when it does not change business meaning.
- Make transforms pure and React-free when they can be shared/tested outside component lifecycle.
- Every data-bearing screen/component has designed loading, empty, error, and permission/not-found states.
- Hooks call application functions, not raw fetch or URLs.

## Never

- `useEffect` chains that accidentally create state machines.
- Recomputing authoritative totals, permissions, eligibility, or status in JSX.
- Store remote API data in unrelated editable UI store.

## Worked example

```ts
type ProjectViewState =
  | { kind: 'loading' }
  | { kind: 'empty' }
  | { kind: 'error'; message: string; requestId: string }
  | { kind: 'ready'; project: ProjectView }

// Bad: { isLoading: boolean; error?: Error; project?: Project } permits conflicting states.
```

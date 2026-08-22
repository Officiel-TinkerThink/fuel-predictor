# Frontend naming conventions

Apply when naming files, exports, types, routes, events, and state.

## Rules

- React components/types/classes: `PascalCase`. Functions, variables, hooks: `camelCase`. Constants: `UPPER_SNAKE_CASE` only for stable constants.
- Components use `PascalCase.tsx`; hooks use `useXxx.ts`; pure helpers use descriptive `camelCase.ts` filename; tests mirror source name with `.test.ts(x)`.
- Name by domain intent, not technical role: `SubmitApplication`, `useProfile`, `OrderSummary`; avoid `Manager`, `Helper`, `Data`, `Thing`, `Util`.
- Boolean names read as questions: `isLoading`, `hasPermission`, `canSubmit`.
- Event handlers begin `handle` locally, callbacks passed as props begin `on`, analytics events use past-tense/action convention defined by analytics contract.
- Use names from Product Bible/domain contract. Do not introduce synonyms for existing concepts.
- URL segments and API JSON field names follow declared contract; do not transform naming silently at arbitrary layers.

## Never

- Abbreviations that hide meaning.
- `index.tsx` as unnamed component implementation.
- Names encoding temporary implementation detail rather than business responsibility.

## Worked example

```ts
// Good
const isSubmitting = false
function useProjectList() {}
function handleArchive() {}

// Bad
const flag = false
function useData() {}
function doThing() {}
```

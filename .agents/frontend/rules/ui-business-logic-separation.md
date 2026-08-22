# UI and business-logic separation

Apply when deciding whether code belongs in component, hook, application, domain, or backend.

## Rule

Backend/domain owns business rules and authoritative outcomes. Browser owns interaction, presentation state, input hygiene, and accessible feedback.

```
component → hook → application intent → gateway
 draws      wires       orchestrates       transports
```

## Rules

- Map raw API response once into view model in application layer. JSX receives named presentation states, not nested transport/data comparisons.
- Components emit intent; they never decide authorization, lifecycle, eligibility, pricing, totals, or workflow outcome.
- Hooks compose state/query and application intent. They do not construct URLs, credentials, or business verdicts.
- Server refusal is information. Render it clearly; do not retry, reinterpret, or replace it with optimistic local state.
- Use optimistic updates only for explicitly reversible, non-governed interactions with defined conflict behavior.
- Side effects have a single owner and cleanup path.

## Never

- Fetch and draw in same component.
- Duplicate server validator/business policy in client.
- Hide a button as an authorization mechanism.

## Worked example

```tsx
// Component draws server result; it does not decide archive eligibility.
return result.kind === 'rejected'
  ? <InlineError message={result.message} />
  : <ArchiveButton onClick={onArchive} />

// Bad: if (project.tasks.length === 0) archiveProjectLocally(project)
```

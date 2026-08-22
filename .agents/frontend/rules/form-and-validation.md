# Forms and validation

Apply to every form.

## Rules

- Define request contract schema once in `domain/`; infer form/use-case types from it. Server contract remains authority.
- Use accessible labels, instructions, focus management, inline field errors, form-level errors, and clear submit status.
- Client checks required/format/range/length only. Never duplicate authorization, pricing, eligibility, lifecycle, or other business rules.
- Keep submit handler thin: collect values → call application intent → map server result/errors → render.
- Preserve valid input after a server rejection. Disable submit only during submission, not merely because client thinks form invalid.
- Map server validation errors to field paths; show correlation/support ID for non-field failures.
- Secrets never enter URL, analytics, logs, local storage, draft persistence, or error echo. Use correct browser autocomplete attributes.
- State-changing submit must prevent accidental duplicate requests; use idempotency support where contract provides it.

## Tests

Test schema boundaries, visible invalid state, valid submission payload, server field errors, and secret redaction.

## Worked example

```ts
export const renameProjectSchema = z.object({
  name: z.string().trim().min(1).max(100),
})

// Good: form sends validated shape, server decides whether rename is permitted.
await renameProject(gateway, projectId, values)
// Bad: if (currentUser.role === 'owner') { ... } as the only permission decision.
```

## Never

- Schema created inside component render.
- Hand-rolled duplicate state/validation for every field.
- Optimistic success for actions requiring server confirmation.

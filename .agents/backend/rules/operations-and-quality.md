# Backend operations and quality

Apply when changing configuration, jobs, integrations, error handling, observability, or tests.

- Read configuration through one validated application boundary. Keep secrets out of source, logs, errors, and client-visible responses.
- Create and dispose external resources through the application lifecycle. Set timeouts, bounded retries, and failure behavior deliberately for integrations.
- Use structured, safe observability: correlation information, meaningful events, and metrics that make failures diagnosable without exposing sensitive data.
- Give asynchronous work explicit ownership, retry limits, idempotency behavior, and a visible terminal outcome.
- Test business rules directly; test boundaries and integrations at their real seams. Cover successful paths, expected failures, and meaningful edge cases.
- Keep changes small and reviewable. Update tests and documentation when behavior or contracts change.

## Check

Before finishing, run the relevant checks and ensure failure modes are safe, observable, and actionable.

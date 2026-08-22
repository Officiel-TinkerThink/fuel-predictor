# Handler layer

Apply when adding HTTP routes/controllers under `modules/<module>/handlers/`.

## Handler responsibility

Parse transport input, authenticate, resolve dependencies, call one use case, serialize its result. Handlers are thin adapters, not business logic.

## Rules

- Validate request shape at boundary with explicit request/response schemas.
- Pass authenticated principal, correlation ID, and parsed command to use case; never trust client-supplied actor/tenant/ownership fields.
- Translate domain errors centrally in framework error mapping. Return safe machine-readable code, client-safe message, and correlation ID.
- Use correct status codes and idempotency key for externally retried state changes.
- Version public APIs. Paginate collection endpoints with bounded limits and stable cursor/offset contract.
- Do not expose ORM rows, internal IDs when public IDs are required, provider errors, stack traces, or secrets.
- Route dependencies may perform authentication/coarse permission checks only; entity-level authorization remains in use case.

## Worked example

```python
@router.post("/projects/{project_id}/archive", response_model=ProjectResponse)
def archive(project_id: ProjectId, current_user: CurrentUser, usecase: ArchiveProjectDep):
    result = usecase.execute(ArchiveProjectInput(project_id, current_user.id))
    return ProjectResponse.from_domain(result)
```

## Never

- Call repository directly from handler.
- Commit, run transactions, make provider calls, or implement state transitions in handler.
- Catch exceptions to return generic success or silently discard failures.

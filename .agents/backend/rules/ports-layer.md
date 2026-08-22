# Ports layer

Apply when a use case needs storage, time, messaging, a provider, or another external capability. Define ports in `modules/<module>/ports.py`, owned by consumer use case.

## Rules

- Use small `typing.Protocol` interfaces. Depend on abstractions, not adapter classes.
- Signatures use domain/shared types only; never ORM rows, HTTP request/response, framework session, SDK client, or dataframe types.
- Name methods after intent: `find_active`, `reserve`, `send`, `record`. Never expose generic `request`, `query`, or `filters: dict` interfaces.
- Split a port beyond roughly 3–8 methods. A large port hides unrelated use cases.
- Return domain values, purpose-built DTOs, or `None` when absence is normal. Do not use `None` for failure.
- Inject a `Clock`, `IdGenerator`, `UnitOfWork`, event publisher, and external gateways where needed. This makes use cases deterministic.
- Provide typed fakes under tests. Fakes record state; do not rely on loose mocks or call-count assertions.

## Worked example

```python
class ProjectRepository(Protocol):
    def get(self, project_id: ProjectId) -> Project | None: ...
    def save(self, project: Project) -> None: ...

# Bad: exposes database language and leaks infrastructure.
class Repository(Protocol):
    def query(self, filters: dict[str, object]) -> list[dict[str, object]]: ...
```

## Never

- Put port definitions in shared infrastructure because an adapter happens to be reused.
- Add a port method only to satisfy one test.
- Branch on adapter implementation with `isinstance`.

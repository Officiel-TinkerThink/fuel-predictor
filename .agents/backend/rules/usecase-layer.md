# Use-case layer

Apply when adding application behavior under `modules/<module>/usecases/`.

## Purpose

Use cases coordinate domain rules, authorization, ports, transaction boundaries, audit, and events. One file/class represents one user or system intent.

## Rules

- Inject ports in constructor. Import no ORM, HTTP, framework, SDK, cache, or adapter type.
- Accept one frozen input command/model; return a domain entity or explicit result DTO. Never return ORM rows or untyped dicts.
- Authorize after loading relevant entity/context. Handler authorization is only a coarse gate.
- Open transaction through `UnitOfWork`; repositories never commit. Write audit evidence in same transaction when it proves a write.
- Publish events only after successful commit. Event handlers must be idempotent.
- Convert expected failures to domain errors; do not raise HTTP errors or swallow exceptions.
- Long-running/retriable work is requested by one use case and performed by worker use case. HTTP path must not block on it.
- Default synchronous. Use async only for genuine bounded concurrent I/O.

## Tests

Test happy path and every domain failure with fake ports, fixed clock, and fake unit of work. Assert resulting state, audit facts, and emitted events.

## Worked example

```python
class ArchiveProject:
    def __init__(self, projects: ProjectRepository, clock: Clock, uow: UnitOfWork) -> None:
        self._projects, self._clock, self._uow = projects, clock, uow

    def execute(self, command: ArchiveProjectInput) -> Project:
        project = require_project(self._projects.get(command.project_id))
        archived = project.archive(command.actor_id, self._clock.now())
        with self._uow:
            self._projects.save(archived)
        return archived
```

## Never

- Instantiate repositories, clients, or adapters inside a use case.
- Put unrelated methods in a service class.
- Publish before commit or commit in a repository.

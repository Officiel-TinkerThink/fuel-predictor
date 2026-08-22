# Backend package structure

Apply when creating/moving packages or imports.

## Direction

`handler → use case → domain/ports ← repository/adapters/framework`

Framework composes dependencies. Domain is innermost. Imports flow inward; implementations satisfy ports from outside.

## Rules

- `domain/` imports only standard library, validation libraries, and shared pure types.
- `usecases/` imports domain, ports, and shared types.
- `repository/` and `adapters/` implement ports and may import infrastructure.
- `handlers/` call use cases only.
- `framework/` creates settings, clients, sessions, error mapping, DI, app/worker lifecycle.
- Enforce boundaries with import-linter or equivalent CI test. New dependency direction requires documented architectural decision.
- Use `snake_case` modules/functions, `PascalCase` classes, `UPPER_SNAKE_CASE` constants. Name by responsibility; no vague `helpers.py`/`utils.py`.

## Never

- Framework or adapter imports under domain/use cases.
- ORM row imports outside owning repository/module.
- Circular module dependencies.

## Worked example

```python
# Good dependency flow.
# handlers/archive_project.py -> usecases/archive_project.py -> domain/project.py
# repository/project_repository.py implements ProjectRepository from ports.py

# Bad: app/modules/projects/domain/project.py imports FastAPI or SQLAlchemy.
```

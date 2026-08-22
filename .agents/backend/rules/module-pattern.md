# Module pattern

Apply when creating/changing a backend module.

## Layout

```
modules/<module>/
├── domain/
├── usecases/
├── repository/
├── handlers/
├── adapters/
├── ports.py
├── public.py
└── module.py
```

## Rules

- Module owns one cohesive business capability, its domain language, persistence mapping, and public API.
- `module.py` declares router, dependency wiring, jobs, and startup registration; it has no business rules.
- `public.py` is only supported cross-module boundary. Export narrow contracts, use cases, or read models; never import another module's repository/rows/domain internals.
- Shared code must be genuinely cross-domain and dependency-light. Prefer a local abstraction until two modules need same stable concept.
- Module dependencies form directed graph. Detect and break cycles via consumer-owned ports or domain events.
- Keep files focused. Split by intent/responsibility before they become hard to navigate.

## Never

- A global `common`, `core`, or `utils` dumping ground.
- Hidden module registration, import side effects, or cross-module database writes bypassing public contract.

## Worked example

```python
# Good: notifications consumes a narrow public event contract.
from app.modules.projects.public import ProjectArchived

# Bad: notifications reaches into another module's persistence internals.
from app.modules.projects.repository.rows import ProjectRow
```

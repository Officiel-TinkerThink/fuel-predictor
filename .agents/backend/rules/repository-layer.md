# Repository layer

Apply when changing persistence under `modules/<module>/repository/`.

## Purpose

Repository maps database rows to domain objects and executes persistence queries. It contains no business decisions.

## Layout

```
repository/
├── rows.py       # ORM table shapes
├── mapping.py    # pure row/entity mapping
└── <aggregate>_repository.py
```

## Rules

- Name persistence classes `XxxRow`; never attach them to entities or return them outside repository.
- Keep mapping pure, explicit, and validated. Corrupt persisted JSON/data must fail visibly, not be silently coerced.
- One repository per aggregate. Use named, bounded query methods; no generic dict-filter DSL.
- Repositories use injected session/connection and never commit, create engine, or start transaction.
- Use parameterized query builders/bound values; never interpolate values into SQL.
- Enforce concurrency with database constraints/locks and translate storage exceptions into domain errors.
- Load required relations deliberately; prevent unbounded reads and N+1 queries.
- Append-only or immutable records are inserted/corrected by new facts, not mutated or deleted.

## Tests

Use migrated disposable instance of production-compatible database. Cover mapping, constraints, transaction behavior, concurrency, and error translation.

## Worked example

```python
def get(self, project_id: ProjectId) -> Project | None:
    row = self._session.get(ProjectRow, project_id)
    return to_project(row) if row else None

# Bad: repository decides policy and commits hidden transaction.
def archive_old(self) -> None:
    self._session.execute(text("DELETE FROM projects WHERE ..."))
    self._session.commit()
```

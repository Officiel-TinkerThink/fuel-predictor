# Alembic migrations

Apply for every persistent schema change.

## Workflow

1. Update ORM row shape and metadata registration.
2. Generate migration, then read and edit every line.
3. Test upgrade from empty/current schema, downgrade or documented compensation, and production-compatible dialects.
4. Ship migration with application change; never alter already-applied migration.

## Rules

- One migration per logical change, one linear history, descriptive revision name.
- Explicit names for tables, indexes, and constraints. Use portable types and bounded strings where target database requires them.
- Store timestamps in UTC; define nullability, defaults, indexes, uniqueness, foreign keys, and deletion behavior deliberately.
- Use expand → backfill → switch reads/writes → contract for live destructive/rename changes.
- Batch large backfills; make them resumable and observable. Do not mix operational seed data into schema migration.
- Preserve immutable/audit/evidence records. Destructive migration needs approved retention decision, backup, and clear docstring.
- Do not use `create_all()` as deployment schema management.

## Tests

CI runs upgrade head and downgrade/compensation path. Integration tests run against migrated schema, not ad-hoc tables.

## Worked example

```python
# Safe rollout: add nullable `display_name` -> backfill -> code reads new value
# with fallback -> later migration makes it non-null.

# Unsafe rollout: rename/drop live `name` column in one migration while deployed
# application instances still read it.
```

# 01 — Generate and store the operation code

**What to build:** a pure domain rule for the code (vehicle mark, `yymmdd-hhmm` base, lowest free
suffix, normalising a typed reference); `CreateDailyOperation` forms the code in the site time
zone and retries with the next suffix if a concurrent insert took it; a unique, nullable
`daily_operations.operation_code` column with a migration that backfills existing planned
operations; the `FUEL_PREDICTOR_SITE_TIMEZONE` setting; ADR 0016 and the glossary entry.

**Blocked by:** nothing.

**Status:** in-review

- [x] A new operation for `VT 01` created at 02:14 UTC on 2026-09-23 has code `260923-0914-VT01`.
- [x] A second one in the same minute gets `260923-0914-VT01-2`; a third `-3`.
- [x] An operation created after midnight local time but before midnight UTC carries the local date.
- [x] A lost race on the unique code is retried with the next suffix rather than surfacing an error.
- [x] Historical imports have no code.
- [x] The migration backfills codes for existing planned operations, in creation order, and leaves
      imported rows empty; downgrade drops the column.

## Comments

- 2026-09-23: No `tzdata` package added. `python:3.12-slim` resolves `Asia/Jakarta` from the OS
  zone database (checked with `docker run`); if a future base image drops it, the settings
  validator refuses to start rather than silently falling back to UTC.
- 2026-09-23: The migration copies the code rule instead of importing it, so it keeps producing
  the same codes whatever the application rule becomes.

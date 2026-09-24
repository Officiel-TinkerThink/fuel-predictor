# 01 — A model code for every model version

**What to build:** a domain rule for `M-yymmdd-nn`; the model repository assigns the next free
code when it creates a version (in-app training and package registration both go through it); a
unique `model_versions.model_code` column with a migration that backfills existing versions in
creation order; the id columns widened to 64 on both tables.

**Blocked by:** nothing.

**Status:** in-review

- [x] A model trained in the app on 2026-09-24 (site time) gets `M-260924-01`; the next that day `-02`.
- [x] An uploaded package gets a code from its manifest's `trained_at`.
- [x] Existing versions get codes by migration, in creation order; downgrade removes the column.
- [x] A package whose `model_version` is 45 characters registers.

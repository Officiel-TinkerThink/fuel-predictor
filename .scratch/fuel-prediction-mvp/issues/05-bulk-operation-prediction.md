# 05 — Support bulk operation prediction

**What to build:** A planner can download a localized Excel/CSV template, submit many Daily Operations, receive row-level validation feedback, and retrieve predictions plus operation IDs for every accepted row.

**Blocked by:** 03 — Deliver a traceable baseline fuel prediction.

**Status:** in-review

- [x] A user can obtain an Indonesian bulk-prediction template with required and optional columns explained.
- [x] Valid rows create predictions using the same behavior as the single-operation API.
- [x] Invalid rows are reported with specific correction reasons while valid rows complete.
- [x] Each accepted row receives a durable operation ID and prediction lineage.
- [x] Batch output distinguishes estimated fuel requirement from recommended allocation.

## Comments

- 2026-08-18: Added localized CSV/XLSX templates, Indonesian web/API upload flows, and a bulk
  orchestration use case that delegates each accepted row to `CreateDailyOperation` and
  `GenerateFuelPrediction`. Accepted rows retain filename/sheet/row/header/raw-value provenance
  in `daily_operation_sources` (Alembic revision `20260818_04`); invalid rows return that same
  provenance with row-level correction reasons. No new external architecture was introduced, so
  DeepWiki research was not needed; the implementation uses the existing FastAPI, openpyxl,
  SQLAlchemy, and Alembic boundaries.

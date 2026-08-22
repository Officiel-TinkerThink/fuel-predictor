# 06 — Capture actual fuel and evaluate outcomes

**What to build:** Users can record one or many Actual Fuel values against operation IDs, then review evaluated error metrics overall and by ANGBER vehicle category.

**Blocked by:** 03 — Deliver a traceable baseline fuel prediction.

**Status:** ready-for-agent

- [x] A user can enter Actual Fuel for an existing operation ID without overwriting prepared fuel.
- [x] A batch actual-fuel template accepts valid operation IDs and reports unmatched or invalid rows.
- [x] Actual-fuel records identify their measurement source or status.
- [x] The system computes MAE, RMSE, MAPE or sMAPE, and prediction-interval coverage when enough matched records exist.
- [x] Performance is viewable both overall and per ANGBER vehicle category.

## Comments

- Implemented 2026-08-18: individual and bulk Indonesian actual-fuel workflows, source/status
  capture, Alembic migration `20260818_05`, and overall/per-ANGBER MAE, RMSE, sMAPE, and
  interval-coverage reporting. Valid rows persist independently of prepared fuel; unmatched,
  invalid, and duplicate rows are quarantined with Indonesian correction messages.

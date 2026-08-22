# 08 — Train candidates and promote models manually

**What to build:** A manager can start training from a validated dataset, compare a candidate against the active model, and explicitly promote a chosen candidate while retaining complete lineage.

**Blocked by:** 03 — Deliver a traceable baseline fuel prediction; 06 — Capture actual fuel and evaluate outcomes.

**Status:** in-review

- [x] A validated dataset can be selected to create a new candidate training run.
- [x] Candidate and active-model metrics can be compared overall and by ANGBER vehicle category.
- [x] The dashboard may recommend retraining from drift or degradation but cannot automatically deploy a model.
- [x] Promotion requires an explicit user action and preserves the previous active-model history.
- [x] New predictions identify the promoted model version that produced them.

## Comments

- 2026-08-18: Implemented candidate/active/retired lifecycle with explicit manual promotion,
  MLflow-backed candidate comparison against actual-fuel outcomes overall and by ANGBER, Indonesian
  API/form governance dashboard, and Alembic revision `20260818_06`. The dashboard can recommend
  manual retraining when active-model MAE exceeds the configured threshold; it contains no automatic
  promotion or deployment path. Existing model records migrate their former latest serving model to
  active, preserving prior prediction lineage. DeepWiki was unavailable and no external
  implementation was adopted.

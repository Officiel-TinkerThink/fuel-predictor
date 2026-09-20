# 03 — Attach the lineage at feature time and record it on the prediction

**What to build:** The trainer and the scorer obtain the lineage from the catalog through `lineage_of` and hand it to `prediction_features.py`, which stays the sole feature contract. `input_snapshot` records `vehicle_type` and `vehicle_group`. The keys of `feature_values` and `FEATURE_VERSION` do not change.

**Blocked by:** 02 — Add the type column to the catalog and a lineage resolver.

**Status:** in-review

- [x] Training (`MlflowBaselineModelStore.train`) and scoring resolve the lineage from the *current* catalog at call time; nothing reads it back from a stored snapshot.
- [x] `feature_values` output is byte-for-byte what it was for the same operation (contract `baseline-v2` untouched).
- [x] Every new prediction's stored snapshot carries `vehicle_type` and `vehicle_group`; old snapshots without them still load.
- [x] `predict_fuel` / `find_similar_operations` results and the web result page show type and group in `details` as information; no input surface changes.

## Comments

- 2026-09-20: The REST API stores the vehicle name as written (only the MCP path canonicalises,
  ADR 0013); the lineage still resolves through aliases, so type and group are right either
  way. Canonicalising at `CreateDailyOperation` was left alone as out of scope.

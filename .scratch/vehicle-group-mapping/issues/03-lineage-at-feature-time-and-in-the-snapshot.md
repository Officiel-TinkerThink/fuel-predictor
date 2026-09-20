# 03 — Attach the lineage at feature time and record it on the prediction

**What to build:** The trainer and the scorer obtain the lineage from the catalog through `lineage_of` and hand it to `prediction_features.py`, which stays the sole feature contract. `input_snapshot` records `vehicle_type` and `vehicle_group`. The keys of `feature_values` and `FEATURE_VERSION` do not change.

**Blocked by:** 02 — Add the type column to the catalog and a lineage resolver.

**Status:** ready-for-agent

- [ ] Training (`MlflowBaselineModelStore.train`) and scoring resolve the lineage from the *current* catalog at call time; nothing reads it back from a stored snapshot.
- [ ] `feature_values` output is byte-for-byte what it was for the same operation (contract `baseline-v2` untouched).
- [ ] Every new prediction's stored snapshot carries `vehicle_type` and `vehicle_group`; old snapshots without them still load.
- [ ] `predict_fuel` / `find_similar_operations` results and the web result page show type and group in `details` as information; no input surface changes.

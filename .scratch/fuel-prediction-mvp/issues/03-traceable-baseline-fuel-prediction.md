# 03 — Deliver a traceable baseline fuel prediction

**What to build:** A planner can request a fuel prediction for one valid Daily Operation and receive an estimated fuel requirement, conservative recommended allocation, uncertainty range, and traceable lineage from a trained baseline candidate.

**Blocked by:** 02 — Import and validate historical ANGBER datasets.

**Status:** in-review

- [x] A validated dataset can train an interpretable baseline candidate using shared training/inference features.
- [x] A prediction labels prepared-fuel learning honestly as estimated fuel requirement, not actual consumption.
- [x] A prediction includes estimated liters, recommended allocation, uncertainty interval, operation ID, and model identity.
- [x] Every prediction is traceable to its input, feature version, dataset version, and model version.
- [x] The initial safety recommendation is configurable and is not presented as a proven 99% guarantee before actual-fuel calibration.

## Comments

- 2026-08-18: Implemented a local MLflow-backed linear-regression baseline. The adapted lifecycle
  uses an explicitly trained latest candidate for Ticket 03 prediction; it intentionally does not
  introduce automatic promotion, which remains the boundary for Ticket 08. DeepWiki was not
  available in this environment, so no external implementation was adopted.

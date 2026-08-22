# 04 — Add ordered multi-stop route calculation

**What to build:** A planner can enter an ordered Stop Sequence and receive route distance for that exact sequence, with a transparent manual-distance fallback when routing is unavailable.

**Blocked by:** 03 — Deliver a traceable baseline fuel prediction.

**Status:** in-review

- [x] The planner can add, remove, and reorder stops in a Daily Operation.
- [x] The routing integration calculates distance using the submitted order and never optimizes or reorders stops.
- [x] A calculated route distance becomes the distance used by the prediction.
- [x] If routing fails, the planner can continue with a manual total distance and the resulting prediction is visibly flagged.
- [x] The routing integration remains replaceable and does not change the prediction contract.

## Comments

- 2026-08-18: Implemented ordered stop persistence and a routing-provider port with a Google Maps
  adapter. The adapter passes `optimize_waypoints=False` and rejects reordered provider responses;
  an unavailable provider preserves the submitted manual total and persists an explicit fallback
  flag through the prediction response and input lineage. DeepWiki is not available in this
  environment, so no external implementation was adopted; this is a narrow realization of ADR
  0003 rather than a new architectural pattern.

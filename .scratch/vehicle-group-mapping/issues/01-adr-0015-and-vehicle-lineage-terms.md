# 01 — Record ADR 0015 and the vehicle-lineage terms

**What to build:** `docs/adr/0015-vehicle-lineage-instance-type-group.md` recording decisions 1–8 of `../spec.md`, and `CONTEXT.md` entries for *vehicle type* (tipe kendaraan) and *vehicle group* (grup kendaraan) placed in the four-level lineage down to *vehicle category*.

**Blocked by:** None — can start immediately.

**Status:** in-review

- [x] The ADR states the three fixed levels, that a single-type group names its type after itself, that the lineage is derived at feature time and never snapshotted as a source, and that the planner-facing contract is unchanged.
- [x] The ADR's consequences name the practical win (a new unit is predictable once catalogued, no retrain) and the deliberate deferrals (feature contract, admin page, per-instance terms, generic hierarchy).
- [x] The ADR does not contradict ADR 0001, 0004, 0009 or 0013; where it touches them it says so.
- [x] `CONTEXT.md` defines the terms and the fallback order same unit → same type → same group → same category.

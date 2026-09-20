# 05 — Add the type step to similar-operations ranking and update the guides

**What to build:** `application/similar_operations.py` ranks same unit → same type → same group → same category, with a `same_type` value in `match.vehicle`, taking the lineage from `lineage_of`; `docs/production/mcp-integration.md` §3 and `docs/production/panduan-operator.md` (regenerate the HTML) describe the lineage, the new match value and the alert.

**Blocked by:** 02 — Add the type column to the catalog and a lineage resolver.

**Status:** in-review

- [x] With two types in one group, a same-type operation outranks a same-group one at equal distance and lifting hours; with one type per group, ranking is unchanged from today.
- [x] `match.vehicle` values are `same`, `same_type`, `same_group`, `same_category`; existing clients that only know three values still receive valid output.
- [x] Tool input schemas and the web form are unchanged.
- [x] Docs describe the four-level lineage, state that the planner only ever names the unit, and list the new alert.

## Comments

- 2026-09-20: `same_type` is emitted only when the type is a real refinement (type differs from
  group). With one type per group a type match would say nothing a group match does not, so
  existing clients keep seeing `same_group` for today's fleet.

# 04 — Lifting capacity gates the activity

Requested 2026-09-24 by the product owner.

**What to build:** a `bisa_lifting` column in the vehicle catalog (`vehicles.can_lift`, migration)
for the three cranes, the only units the Data Ratio sheet prices lifting for. The planning form
offers two activities, *Mobilisasi* (`transport`) and *Mobilisasi + lifting*
(`transport_and_lifting`); the second is disabled for a unit that cannot lift. `CreateDailyOperation`
refuses lifting for such a unit, so the form, API, bulk sheet and MCP are all gated. The Armada page,
the MCP `list_vehicles` result and the bulk template say which units can lift.

**Blocked by:** 01.

**Status:** in-review

- [x] VT 01 planned with lifting is refused on every route, naming the unit.
- [x] A crane may lift; a unit not in the catalog is not second-guessed.
- [x] The form offers exactly two activities.
- [x] `lifting` (without mobilisation) stays readable for operations planned before, and is no
      longer offered for new plans.

## Comments

- 2026-09-24: Decided with the owner: two activities (a crane that lifts also travels), and only
  the three cranes can lift; the forklifts are mobilisation only until the sheet says otherwise.

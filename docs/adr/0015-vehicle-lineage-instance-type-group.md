# ADR 0015: A vehicle has a fixed three-level lineage, derived from the catalog when needed

## Status

Proposed

## Context

The fleet catalog lists 23 units, fifteen of them `VT 01…VT 15`. The active feature contract
(`baseline-v2`) one-hot encodes the **unit**: the model learns fifteen separate vacuum-truck
coefficients from a handful of rows each, and a unit it has never seen — `VT 16`, a crane hired
for a week — silently scores as "no vehicle", because the vectoriser drops a name it was not
fitted on. The catalog already carries a coarser level, `grup` (Vacuum Truck, Truck, Crane,
Forklift), but nothing on the prediction path uses it.

The owner will refine the fleet taxonomy later: the vacuum trucks may turn out to be two kinds,
"VT A" and "VT B". The obvious move — make "VT A" the group — throws away the fact that VT A and
VT B are both vacuum trucks, which is exactly the level a model with thin data, and a planner
looking for a comparable day, must be able to fall back to.

Two things must hold whatever the owner decides: the planner keeps naming a unit and nothing
else, and a change to the taxonomy can never silently disagree with a model trained under the
previous one.

## Decision

### Three fixed levels, held in the catalog

Every unit sits in a lineage of exactly three levels below the category ADR 0001 fixed:

```
kendaraan (unit)     VT 01
  └ tipe (type)      VT A            the owner's finer cut inside a group
      └ grup (group) Vacuum Truck    the kind of machine
          └ kategori ANGBER          ADR 0001, unchanged
```

The catalog (`kendaraan-angber.csv`, the `vehicles` table) gains one column, `tipe`. `grup` keeps
its meaning and its data. **A group with a single type names that type after itself** — which is
every group today, so the column is backfilled from the group and the bundled sheet carries the
same value in both. The level exists from the start so that splitting a group later is an edit
of a few cells, not a schema change. It is three levels by design, not the first three of a
tree: the fleet is 23 units, and the value is in one fallback step, not in hierarchy machinery.

### The operation stores the fact; the lineage is derived, never snapshotted

A `DailyOperation` records the canonical unit name and nothing more. Type and group are looked
up from the catalog **at the moment they are needed** — when a candidate is trained, when a
prediction is scored, when a candidate is evaluated, when similar history is ranked — through
one resolver, `VehicleCatalog.lineage_of(name)`, that both catalog implementations provide.

The taxonomy is a lens the owner may refine, not a fact about the day. When the owner re-types
the vacuum trucks, every reading of history must see the new lens; a lineage stored on the
operation would leave the training set half `Vacuum Truck`, half `VT A`. The prediction's stored
`input_snapshot` does carry `vehicle_type` and `vehicle_group` — as a *record* of which lens
was applied that day, for traceability. Nothing reads it back.

A unit the catalog does not know is `tidak diketahui` at every level, the convention the
feature contract already uses for an unnamed vehicle. Resolution never raises: feature time is
not the place to discover a catalog gap.

### The planner-facing contract does not change

In: the unit, by name or alias, exactly as before — the web form's select, `predict_fuel`'s
`vehicle`. Out: the recommendation. Which level the model reasons at is invisible to the planner
and never asked of them: no type or group field on any form, no new tool argument, no change to
the tool's input schema. The lineage appears in the result's details as information.

### The feature contract is a separate decision

`feature_values` now receives the lineage, so every caller already resolves it and a contract
that pools by type or group changes one file. `baseline-v2` does not read it: its keys and values
are byte-for-byte what they were. Whether `vehicle` is dropped, whether type and group enter as
nested one-hot terms with per-level distance and lifting-hour slopes, whether the constant
`vehicle_category` stays — that is a data-engineering decision and will be its own ADR, with a
`baseline-v3` bump.

### A model says which taxonomy it was trained on

A *catalog fingerprint* — a stable hash of the sorted `(unit, type, group)` triples — is
recorded with every model trained from now on. When a model's contract consumes the lineage, a
fingerprint that differs from the current catalog raises a dashboard alert asking for a retrain.
For `baseline-v2`, which reads the unit alone, a re-typing cannot change a prediction and no
alert is raised: which contracts are lineage-aware is a list kept beside `FEATURE_VERSION`,
empty until `baseline-v3` adds itself. Promotion stays manual (ADR 0004); the alert is a signal.

### One fallback order for the whole application

Wherever the application looks for "the same kind of vehicle" — the similar-operations ranking
today, the model's pooling later — the order is same unit → same type → same group, and then
nothing. The category is not a level: every unit is ANGBER, so "same category" would mean any
other machine, and an unrelated machine shown as similar history misleads more than an empty
list. ADR 0013's ranking ended in "same category"; this ADR removes that tier. The ranking labels
a row `same_type` only when the type is a real refinement (type differs from group); with one
type per group, every label is what it was before this ADR.

### The lineage is managed where it already lives

The workbook is where the operations staff maintain the fleet, and the CSV is in git, so a
re-typing is a commit and a `python -m fuel_predictor import-vehicles`. An admin page to edit
the catalog is deferred until a non-developer needs it.

## Consequences

- **A new unit is predictable the moment it is catalogued**, with no retrain, as soon as a
  contract pools by group: a rented crane gets the crane estimate. Today, under `baseline-v2`,
  it is still "no vehicle"; this ADR makes the fix a contract change rather than a redesign.
- One Alembic revision (`vehicle_type`, backfilled from `vehicle_group`), one CSV column, one
  resolver on the catalog port, one extra argument on the feature contract, `vehicle_type` and
  `vehicle_group` on stored snapshots, a `same_type` match value, and a catalog fingerprint on
  trained models with a gated alert.
- Every caller of the feature contract now depends on the catalog: the scorer, the trainer, the
  candidate evaluation. That is the point — they cannot drift apart on which lens they use.
- Deciding the actual types, the feature contract, per-unit correction terms and a catalog admin
  page are all explicitly deferred. Per-unit terms return only when actual-fuel monitoring shows
  a unit consistently off its type.
- Supersedes nothing. Refines ADR 0013's "the vehicle is a feature": the unit remains what the
  planner names; what the model reasons about is now a separate, deliberate choice.

# Vehicle instance → type → group: lineage ownership and resolution

Status: ready-for-agent

Handoff written 2026-09-19, revised 2026-09-20, after a design conversation with the product
owner. It covers the **application side only**: where the instance → type → group lineage lives,
who changes it, and how an operation arrives at prediction time with that lineage attached. What the model then *does*
with the group (the feature contract) is a separate, later decision — see "Out of scope".

## Problem

The fleet catalog lists 23 units, fifteen of them `VT 01…VT 15`. The active feature contract
(`baseline-v2`, `src/fuel_predictor/application/prediction_features.py`) one-hot encodes the
**instance** name, so the model learns fifteen separate vacuum-truck coefficients from a handful
of rows each, and a unit it has never seen (`VT 16`, a rented crane) silently scores as "no
vehicle" because `DictVectorizer` drops unknown keys. The catalog already carries the right level
of abstraction — `grup` (Vacuum Truck / Truck / Crane / Forklift) — but nothing uses it for
prediction.

The product owner will refine the fleet taxonomy later (for example, the VTs may turn out to be
two kinds, "VT A" / "VT B"). That refinement must not erase the coarser fact that VT A and VT B
are both vacuum trucks: with thin data, a model and the similar-operations search both need to
fall back from the fine level to the coarse one. The application must make the refinement cheap
to take and cheap to change, and must never let a changed taxonomy silently disagree with a
trained model.

## Decisions (agreed with the product owner)

1. **Three fixed levels, held in the catalog.** Every unit has a lineage:

   ```
   kendaraan (instance)   VT 01
     └ tipe (type)        VT A          <- the owner's later refinement
         └ grup (group)   Vacuum Truck  <- exists today
             └ kategori   ANGBER        <- unchanged (ADR 0001)
   ```

   The `vehicles` table (`name`, `vehicle_group`, `aliases`;
   `src/fuel_predictor/infrastructure/sqlalchemy_vehicles.py`, fed from `kendaraan-angber.csv`
   by `python -m fuel_predictor import-vehicles`) gains one column, `tipe` / `vehicle_type`,
   between instance and group. `grup` keeps its current meaning and data. **A group with a
   single type gives that type the group's own name** (`Forklift SCM → Forklift / Forklift`,
   `VT 01 → Vacuum Truck / Vacuum Truck`) — which is every group today. The column exists from
   day one so nothing is flattened; splitting a group later is an edit of a few cells, not a
   schema change. Do not add a second table, a parallel mapping, or a generic hierarchy: three
   levels is the design, not a start.

2. **The operation stores the fact; the lineage is derived, not snapshotted.** A
   `DailyOperation` keeps only the canonical `vehicle` name (as today). Type and group are looked
   up from the catalog **at feature time**, for training and scoring alike, through one resolver
   returning the whole lineage. Reason: the taxonomy is a modelling lens over the fleet, not a
   fact about the day. When the owner re-types or re-groups, all history must be reclassified
   consistently; a snapshot would leave training data half `Vacuum Truck`, half `VT A`.

3. **Unknown is its own value at every level.** A unit not in the catalog resolves to
   `tidak diketahui` for both type and group, the convention `_vehicle_of` already uses for an
   unnamed vehicle. Never raise at feature time.

4. **A model records which taxonomy it was trained on.** A *catalog fingerprint* — a stable hash
   of the sorted `(canonical name, type, group)` triples — is logged as an MLflow param at training time
   and stored alongside `feature_version` in the model version / package manifest. At activation
   and in the monitoring job, a fingerprint that differs from the current catalog raises a plain
   alert ("Penggolongan kendaraan berubah sejak model dilatih; latih ulang kandidat."). It is a
   signal only: promotion stays manual (ADR 0004).

5. **Managing the lineage stays CSV + `import-vehicles` for now.** The workbook is where the
   operations staff already keep this, and the CSV is in git so every re-typing is a commit.
   An admin "Armada" page is explicitly deferred until a non-developer needs to edit it.

6. **A new unit is predictable the moment it is in the catalog** — no retrain. Even before the
   owner has decided its type, a group alone (type named after the group) is enough for a
   group-level estimate. This is the practical win and should be stated in the ADR's
   consequences.

7. **The planner-facing contract does not change.** In: the unit, by name or alias, exactly as
   today (web form select, `predict_fuel {"vehicle": ...}`). Out: the recommendation. Which level
   of the lineage the model uses is invisible to the planner and never asked of them: no type or
   group field on any form, no new MCP tool argument, no change to the tool's input schema.
   The lineage is recorded on the prediction snapshot for traceability and shown in the details
   block as information, nothing more.

8. **Fallback order is fixed and shared.** Wherever the application looks for "the same kind of
   vehicle" — similar-operations ranking today, the model's pooling later — the order is
   same unit → same type → same group → same category. One place defines it.

## What to build

- **ADR 0015** in `docs/adr/` recording decisions 1–8 (status Proposed → Accepted once merged).
  Read ADR 0001, 0004, 0009, 0013 first; do not contradict them. Update `CONTEXT.md` with the
  terms *vehicle type* (tipe kendaraan) and *vehicle group* (grup kendaraan) and the four-level
  lineage down to *vehicle category*.
- **Catalog column** `tipe` (CSV) / `vehicle_type` (table): one Alembic revision, backfilled
  with `vehicle_group`; `VehicleOption` gains `type`; `PackagedVehicleCatalog` reads `tipe` and
  uses `grup` when the column or cell is blank (a single-type group names its type after
  itself), so the existing sample CSV keeps importing. Add the column to
  `kendaraan-angber.csv`, filled with the group names.
- **A resolver** on the `VehicleCatalog` port (`src/fuel_predictor/application/vehicles.py`):
  `lineage_of(name: str | None) -> VehicleLineage(vehicle, type, group)`, canonical-or-alias
  in, `tidak diketahui` at every level when unknown. Both implementations
  (`PackagedVehicleCatalog`, `SqlAlchemyVehicleRepository`) implement it.
- **Feature-time attachment.** `feature_values` / `input_snapshot` receive the lineage
  (signature becomes `(operation, lineage)` or the trainer/scorer attaches it — pick the shape
  that keeps `prediction_features.py` the sole feature contract, as its docstring promises).
  Add `vehicle_type` and `vehicle_group` to `input_snapshot` so every stored prediction says
  which lens was applied. **Do not change the keys of `feature_values` or bump
  `FEATURE_VERSION`** — that is the data-engineering follow-up. This spec only guarantees the
  lineage is *available* there.
- **Fingerprint**: a pure function in the application layer; logged in
  `MlflowBaselineModelStore.train` beside `feature_version`; stored on the model version;
  accepted into the external package manifest as an optional field (bump the manifest schema
  in `src/fuel_predictor/schemas/model-package/` accordingly, keep old packages valid).
- **Alert**: monitoring (`application/monitoring.py`, `alert_remediation.py`) gains a
  "catalog changed since training" alert kind with its plain-Indonesian remediation text, shown
  on the dashboard like the existing ones.
- **Surfaces**: `predict_fuel` / `find_similar_operations` MCP results and the web result page
  show `vehicle_type` and `vehicle_group` next to `vehicle` in `details`. Similar-operations
  ranking (`application/similar_operations.py`) gains the type step: same unit → same type →
  same group → same category, with a `same_type` match label; it takes the lineage from the
  resolver, not from `VehicleOption.group` directly.
- **Tests**: resolver (alias, unknown, empty, blank `tipe` names the type after the group);
  fingerprint stable across row order and changed by a re-typing alone; alert raised on
  mismatch and silent on match; snapshot carries type and group; similar ranking prefers same
  type over same group; `import-vehicles` followed by a prediction of a previously unknown unit
  succeeds.
- Docs: `docs/production/mcp-integration.md` §3 (details table) and
  `docs/production/panduan-operator.md` (catalog / alerts sections; regenerate the HTML with
  `build-operator-guide-html.py`) mention the group and the alert.

## Out of scope (deliberately)

- **The feature contract.** Whether `vehicle` is dropped, which of type / group enter the
  model and how (nested one-hot so a type is "its group plus a correction", per-level distance
  and lifting-hour slopes), whether `vehicle_category` (constant `ANGBER`) stays — all of that
  is the data-engineering decision and will be a separate spec / `baseline-v3` bump.
- Deciding the actual types. Every type is named after its group until the owner says otherwise.
- An admin page to edit the catalog.
- A generic hierarchy (N levels, a tree table). Three levels is the design.
- Per-instance bias terms. Revisit only when actual-fuel monitoring shows a unit consistently
  off its type.

## Pointers

- Catalog port and options: `src/fuel_predictor/application/vehicles.py`
- DB catalog: `src/fuel_predictor/infrastructure/sqlalchemy_vehicles.py`; CSV catalog:
  `src/fuel_predictor/infrastructure/packaged_vehicle_catalog.py`;
  sample: `src/fuel_predictor/examples/kendaraan-angber.csv`
- Feature contract: `src/fuel_predictor/application/prediction_features.py`
- Trainer: `src/fuel_predictor/infrastructure/mlflow_baseline_models.py`
- Operation creation: `src/fuel_predictor/application/daily_operations.py`
- Similar-operations ranking: `src/fuel_predictor/application/similar_operations.py`
- MCP vehicle resolution: `src/fuel_predictor/delivery/mcp_server.py` (`resolve_vehicle`)
- Drift categorical columns: `src/fuel_predictor/infrastructure/evidently_drift.py`
- Package manifest: `src/fuel_predictor/domain/model_package.py`, schema under `schemas/`
- Repo conventions: `docs/agents/engineering-standards.md`, `docs/agents/domain.md`;
  test/lint commands in `README.md` (CI runs `ruff check`, `mypy src tests`, pytest collect)

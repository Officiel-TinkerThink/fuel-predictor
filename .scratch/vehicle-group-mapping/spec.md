# Vehicle instance → vehicle group: mapping ownership and resolution

Status: ready-for-agent

Handoff written 2026-09-19 after a design conversation with the product owner. It covers the
**application side only**: where the instance→group mapping lives, who changes it, and how an
operation arrives at prediction time with the right group attached. What the model then *does*
with the group (the feature contract) is a separate, later decision — see "Out of scope".

## Problem

The fleet catalog lists 23 units, fifteen of them `VT 01…VT 15`. The active feature contract
(`baseline-v2`, `src/fuel_predictor/application/prediction_features.py`) one-hot encodes the
**instance** name, so the model learns fifteen separate vacuum-truck coefficients from a handful
of rows each, and a unit it has never seen (`VT 16`, a rented crane) silently scores as "no
vehicle" because `DictVectorizer` drops unknown keys. The catalog already carries the right level
of abstraction — `grup` (Vacuum Truck / Truck / Crane / Forklift) — but nothing uses it for
prediction.

The product owner will decide the grouping itself later (for example, the VTs may turn out to be
two kinds, "VT A" / "VT B"). The application must make that decision cheap to take and cheap to
change, and must never let a changed grouping silently disagree with a trained model.

## Decisions (agreed with the product owner)

1. **The catalog is the single mapping.** The `vehicles` table (`name`, `vehicle_group`,
   `aliases`; `src/fuel_predictor/infrastructure/sqlalchemy_vehicles.py`, fed from
   `kendaraan-angber.csv` by `python -m fuel_predictor import-vehicles`) already holds
   `VT 01 → Vacuum Truck`. Do not add a second table or a parallel mapping. `grup` changes
   meaning from "descriptive kind" to "the unit the model reasons about". One column, no
   hierarchy: a subtype later is a new *value* (`Vacuum Truck 10 kL`), not a new column.

2. **The operation stores the fact; the group is derived, not snapshotted.** A `DailyOperation`
   keeps only the canonical `vehicle` name (as today). The group is looked up from the catalog
   **at feature time**, for training and scoring alike, through one resolver. Reason: the
   grouping is a modelling lens over the fleet, not a fact about the day. When the owner
   re-groups, all history must be reclassified consistently; a snapshot would leave training data
   half `Vacuum Truck`, half `VT A`.

3. **Unknown is its own group.** A unit not in the catalog resolves to `tidak diketahui`, the
   convention `_vehicle_of` already uses for an unnamed vehicle. Never raise at feature time.

4. **A model records which grouping it was trained on.** A *catalog fingerprint* — a stable hash
   of the sorted `(canonical name, group)` pairs — is logged as an MLflow param at training time
   and stored alongside `feature_version` in the model version / package manifest. At activation
   and in the monitoring job, a fingerprint that differs from the current catalog raises a plain
   alert ("Pengelompokan kendaraan berubah sejak model dilatih; latih ulang kandidat."). It is a
   signal only: promotion stays manual (ADR 0004).

5. **Managing the mapping stays CSV + `import-vehicles` for now.** The workbook is where the
   operations staff already keep this, and the CSV is in git so every regrouping is a commit.
   An admin "Armada" page is explicitly deferred until a non-developer needs to edit it.

6. **A new unit is predictable the moment it is in the catalog with a group** — no retrain. This
   is the practical win and should be stated in the ADR's consequences.

## What to build

- **ADR 0015** in `docs/adr/` recording decisions 1–6 (status Proposed → Accepted once merged).
  Read ADR 0001, 0004, 0009, 0013 first; do not contradict them. Update `CONTEXT.md` with the
  term *vehicle group* (grup kendaraan) and its relationship to *vehicle* and *vehicle category*.
- **A resolver** on the `VehicleCatalog` port (`src/fuel_predictor/application/vehicles.py`):
  `group_of(name: str | None) -> str`, canonical-or-alias in, group or `tidak diketahui` out.
  Both implementations (`PackagedVehicleCatalog`, `SqlAlchemyVehicleRepository`) implement it.
- **Feature-time attachment.** `feature_values` / `input_snapshot` receive the group (signature
  becomes `(operation, group_of)` or the trainer/scorer attaches it — pick the shape that keeps
  `prediction_features.py` the sole feature contract, as its docstring promises). Add
  `vehicle_group` to `input_snapshot` so every stored prediction says which lens was applied.
  **Do not change the keys of `feature_values` or bump `FEATURE_VERSION`** — that is the
  data-engineering follow-up. This spec only guarantees the group is *available* there.
- **Fingerprint**: a pure function in the application layer; logged in
  `MlflowBaselineModelStore.train` beside `feature_version`; stored on the model version;
  accepted into the external package manifest as an optional field (bump the manifest schema
  in `src/fuel_predictor/schemas/model-package/` accordingly, keep old packages valid).
- **Alert**: monitoring (`application/monitoring.py`, `alert_remediation.py`) gains a
  "catalog changed since training" alert kind with its plain-Indonesian remediation text, shown
  on the dashboard like the existing ones.
- **Surfaces**: `predict_fuel` / `find_similar_operations` MCP results and the web result page
  show `vehicle_group` next to `vehicle` in `details`. Similar-operations ranking already uses
  same unit → same group → same category; leave it, but make it use the resolver rather than
  reading `VehicleOption.group` directly if it does.
- **Tests**: resolver (alias, unknown, empty); fingerprint stable across row order and changed
  by a regroup; alert raised on mismatch and silent on match; snapshot carries the group;
  `import-vehicles` followed by a prediction of a previously unknown unit succeeds.
- Docs: `docs/production/mcp-integration.md` §3 (details table) and
  `docs/production/panduan-operator.md` (catalog / alerts sections; regenerate the HTML with
  `build-operator-guide-html.py`) mention the group and the alert.

## Out of scope (deliberately)

- **The feature contract.** Whether `vehicle` is dropped, whether the group gets per-group
  distance / lifting-hour slopes, whether `vehicle_category` (constant `ANGBER`) stays — all of
  that is the data-engineering decision and will be a separate spec / `baseline-v3` bump.
- An admin page to edit the catalog.
- Per-instance bias terms. Revisit only when actual-fuel monitoring shows a unit consistently
  off its group.

## Pointers

- Catalog port and options: `src/fuel_predictor/application/vehicles.py`
- DB catalog: `src/fuel_predictor/infrastructure/sqlalchemy_vehicles.py`; CSV catalog:
  `src/fuel_predictor/infrastructure/packaged_vehicle_catalog.py`;
  sample: `src/fuel_predictor/examples/kendaraan-angber.csv`
- Feature contract: `src/fuel_predictor/application/prediction_features.py`
- Trainer: `src/fuel_predictor/infrastructure/mlflow_baseline_models.py`
- Operation creation: `src/fuel_predictor/application/daily_operations.py`
- MCP vehicle resolution: `src/fuel_predictor/delivery/mcp_server.py` (`resolve_vehicle`)
- Drift categorical columns: `src/fuel_predictor/infrastructure/evidently_drift.py`
- Package manifest: `src/fuel_predictor/domain/model_package.py`, schema under `schemas/`
- Repo conventions: `docs/agents/engineering-standards.md`, `docs/agents/domain.md`;
  test/lint commands in `README.md` (CI runs `ruff check`, `mypy src tests`, pytest collect)

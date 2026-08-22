# Fuel Prediction MVP Specification

Status: ready-for-agent

## Problem Statement

Distribution planners need to allocate newly issued fuel for a complete daily ANGBER operation. Current records are Excel-based and inconsistent, while planning often uses incomplete distance estimates. The business needs a locally usable system that turns structured plans into conservative, traceable estimates and learns safely when actual fuel becomes available.

## Solution

Build a local Indonesian-language application with a form, bulk Excel/CSV workflows, a prediction API, routing integration, ingestion/validation, model lifecycle controls, and a monitoring dashboard. It predicts an **estimated fuel requirement** from prepared-fuel history and separately returns a conservative **recommended allocation**. It accepts actual fuel later without pretending that prepared fuel is ground truth.

## User Stories

1. As a planner, I want to select an ANGBER vehicle category so that the estimate reflects equipment-level behavior.
2. As a planner, I want to select transport, lifting, or both so that the operation is described consistently.
3. As a planner, I want to enter stops in their actual order so that the route represents the real daily sequence.
4. As a planner, I want the application to include every entered stop and return leg so that it avoids the point-to-point-times-two shortcut.
5. As a planner, I want to enter lifting hours only when relevant so that non-lifting equipment is not treated as incomplete.
6. As a planner, I want a manual distance fallback so that a routing-provider failure does not block planning.
7. As a planner, I want to see estimated fuel requirement and recommended allocation separately so that I understand accuracy versus safety.
8. As a planner, I want a generated operation ID so that later actual fuel can be matched reliably.
9. As a planner, I want to upload a batch template so that I can predict many planned operations efficiently.
10. As a data operator, I want validation and a correction report so that malformed rows do not silently affect training.
11. As a data operator, I want blank pre-created calendar rows ignored so that they do not become observations.
12. As a data operator, I want corrected rows to be re-importable so that data quality improves over time.
13. As a manager, I want to upload a versioned dataset and train a candidate model so that new data can be evaluated safely.
14. As a manager, I want to compare a candidate with the active model globally and by vehicle category so that weak segments are visible.
15. As a manager, I want to manually promote a better candidate so that production changes remain controlled.
16. As a manager, I want to enter or bulk-import actual fuel by operation ID so that the system can evaluate real outcomes.
17. As a manager, I want local dashboard alerts for data quality, missing actuals, drift, and degradation so that I know when attention is needed.
18. As an auditor, I want each prediction linked to input data, feature version, dataset version, and model version so that it is reproducible.
19. As a future integrator, I want the prediction service behind a stable API so that a later AI/MCP client can use the same logic.

## Implementation Decisions

- Model the core entities as VehicleCategory, Location, RoutePlan, DailyOperation, FuelRecord, Prediction, DatasetVersion, ModelVersion, TrainingRun, and DataQualityIssue.
- Preserve raw source values and source-sheet provenance. Normalize ANGBER categories and lifting-hour headers during ingestion.
- Treat each record as a DailyOperation, not a single travel leg. Do not infer remaining tank fuel from previous records.
- Use a routing-provider adapter. Google Maps is the initial preferred provider; isolate it so a later provider can replace it. Use exact input order only; never optimize or reorder stops.
- Permit stop names/coordinates before the location catalog exists. Add an importable LocationCatalog interface later, using stable IDs as the canonical location reference.
- Return a prediction contract containing estimated liters, recommended liters, uncertainty interval, operation ID, route-distance source, and model version.
- Start with interpretable baseline regression and benchmark stronger tree models. Training/inference share one feature pipeline.
- Candidate training is initiated manually after validated, versioned data upload. Promotion is manual; monitoring may recommend retraining but cannot deploy a model.
- Store actual fuel distinctly from prepared fuel and label UI results honestly until sufficient actuals are available.
- Support individual and bulk prediction/actual workflows through validated Excel/CSV templates.
- Keep dashboard alerts local in the MVP. Default thresholds are configuration, not hard-coded policy.

## Testing Decisions

- Test external behavior at the API and workflow seams: ingestion, route-distance resolution, prediction creation, bulk validation, actual-fuel matching, candidate comparison, promotion, and dashboard alert generation.
- Use fixture workbooks containing blank calendar rows, malformed numeric values, each vehicle category, lifting and non-lifting operations, manual-route fallback, and unmatched operation IDs.
- Verify that invalid records are quarantined and reported; valid records proceed without mutation of raw provenance.
- Verify route requests preserve planner-entered stop order and that manual fallback is visible on the resulting prediction.
- Verify every persisted prediction has a model/dataset/feature lineage record.
- Verify metrics are computed both overall and per vehicle category, and no candidate promotion occurs without an explicit action.

## Out of Scope

User accounts; roles; approval workflows; cloud deployment; email/chat alerts; AI or MCP client; route optimization; individual vehicle IDs; live telematics; receipts/photos; automatic model deployment; and guaranteed 99% safety before actual-fuel calibration.

## Further Notes

The source workbook's `Dari` and `Ke` values are free text. They must be retained for audit but will eventually map to a company location catalog. The initial prepared-fuel dataset is useful for an allocation model, but it must not be represented as verified consumption.

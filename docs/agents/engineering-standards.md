# Engineering Standards

## Architecture

- Use domain-driven boundaries. The Daily Operation, Fuel Record, Prediction, Dataset Version, and Model Version are domain concepts, not UI or persistence shapes.
- Keep domain rules and feature calculation independent of FastAPI, database, spreadsheet, routing-provider, and dashboard concerns.
- Use explicit interfaces at boundaries such as routing, model registry, dataset storage, and imports. Infrastructure implements those interfaces.
- Keep the initial product a modular monolith. Do not split services until a real operational boundary requires it.

## Data contracts

- Validate input at every boundary and preserve source provenance.
- Use typed, versioned request, response, dataset, and model contracts.
- Do not let free-text source values silently become canonical domain values.
- Keep prepared fuel and Actual Fuel separate through storage, APIs, metrics, and UI.

## Code quality

- Prefer small cohesive modules and clear domain names from `CONTEXT.md`.
- Avoid duplicate logic, feature transformations, validation rules, and configuration. Extract a shared abstraction only after there is real repeated behavior.
- Keep dependencies flowing inward: delivery and infrastructure depend on the domain, never the reverse.
- Document decisions and non-obvious tradeoffs in ADRs or ticket comments, not only in code comments.

## Testing

- Follow test-driven development for behavior: write a failing external-behavior test first when practical, then implement the smallest change that passes it, then refactor safely.
- Prefer API and workflow tests at the highest useful seam. Unit-test pure domain rules and feature transformations.
- Tests must describe observable outcomes, not private implementation details.
- Every defect fix receives a regression test.

## Events

- Represent meaningful lifecycle changes explicitly, for example `daily_operation_created`, `prediction_generated`, `actual_fuel_recorded`, `dataset_validated`, `candidate_model_trained`, and `model_promoted`.
- In the local MVP, events may be persisted or dispatched in-process; do not introduce a message broker until a real asynchronous integration needs it.
- Event consumers must be idempotent and must not bypass the domain model.

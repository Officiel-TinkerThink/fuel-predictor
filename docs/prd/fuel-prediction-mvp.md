# PRD: Fuel Prediction MVP

## Purpose

Provide a simple local application that helps Indonesian distribution operations plan adequate fuel for a complete daily heavy-equipment operation. It must reduce over-allocation without creating unsafe fuel shortages.

## Problem

Fuel planning is currently based on manual judgment and incomplete point-to-point distance estimates. One operation can include multiple stops, travel, lifting, and a return leg. Historical data exists in Excel, but it has free-text locations, inconsistent headers, empty calendar rows, and some malformed values. The team needs a dependable system around prediction, not merely a trained model.

## Product outcomes

1. Create a consistent plan for a full ordered stop sequence.
2. Estimate fuel and show a conservative recommended allocation.
3. Keep every prediction traceable to its inputs, dataset, feature version, and model version.
4. Collect actual fuel later and measure model performance by vehicle category.
5. Make data-quality, drift, and retraining needs visible in a local dashboard.

## MVP users and language

Staff or a manager can use the application locally. The UI and Excel templates are Indonesian; engineering documents and code documentation are English. Authentication and role management are not part of the MVP.

## Core workflow

1. A user creates one daily operation or uploads many operations through an Excel/CSV template.
2. They choose an ANGBER vehicle category, transport/lifting/both activity mode, ordered stops, and lifting hours where applicable.
3. The system calculates route distance in the entered order through a routing provider. If that fails, the user can supply a manual total distance and the plan is marked accordingly.
4. The system generates an operation ID, predicts estimated fuel requirement, calculates a conservative recommended allocation, and stores the full record.
5. The user may later enter or bulk-import actual fuel against operation IDs.
6. The dashboard shows data quality, prediction/actual comparison, category-level performance, drift, candidate training runs, and model status.

## Data policy

The initial ANGBER Excel file is an ingestion source, not the application data model. Blank pre-created calendar rows are excluded. `L (Jam)` and mislabelled `L (Km)` represent lifting hours. Historical `D (Km)` represents the day's complete travel distance. Invalid values are quarantined with a correction report; they are never silently guessed, discarded, or rewritten.

## Success measures

- Valid operation plans can be predicted individually and in bulk.
- Every result is reproducible and linked to a versioned model/dataset.
- Staff can review validation failures and re-import corrections.
- The system exposes global and category-level MAE, RMSE, MAPE/sMAPE, and prediction-interval coverage once suitable targets exist.
- Recommended allocations are configurable, with an initial conservative 99% coverage intent; the achieved level is validated once actual fuel is collected.

## Deferred capabilities

AI/MCP interaction, production deployment, external alert delivery, authentication, individual vehicle IDs, route optimization, receipt/photo uploads, and automated promotion/deployment are deferred.

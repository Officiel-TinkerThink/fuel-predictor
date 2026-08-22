# Fuel Prediction System Context

## Glossary

- **Daily operation**: one row representing a vehicle category's complete activity sequence for a day, including travel, lifting where applicable, and return travel.
- **ANGBER**: *Angkutan Berat*; the heavy-equipment category used for a daily operation.
- **Prepared fuel**: fuel newly issued for a daily operation. It is the only current target label and is not yet verified actual consumption.
- **Actual fuel**: post-operation, ground-truth fuel consumption recorded later against an operation ID.
- **Stop sequence**: ordered locations supplied by a planner, such as depot → site A → site B → depot. The entered order is authoritative.
- **Estimated fuel requirement**: the predicted fuel value shown while prepared fuel remains the training label.
- **Recommended allocation**: a conservative fuel amount derived from the estimate and uncertainty, intended to reduce shortages.
- **Location catalog**: the future source of stable location IDs, names, aliases, and coordinates.

## Product boundary

The MVP is a locally run, Indonesian-language fuel-prediction application. It has no user accounts, roles, approvals, or route optimization. It predicts the prepared fuel requirement for a daily operation, records feedback, and monitors data/model health.

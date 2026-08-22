# ADR 0002: Keep Prepared Fuel and Actual Fuel Distinct

## Status

Accepted

## Context

The historical workbook records newly issued prepared fuel, not verified post-operation consumption. Actual fuel may be collected later.

## Decision

Persist prepared fuel and actual fuel as separate values with explicit source and status. Label MVP outputs as estimated fuel requirement and recommended allocation. Do not claim actual-consumption accuracy until actual records support evaluation.

## Consequences

Historical data can start the system, while later ground truth improves calibration without corrupting lineage or reporting.

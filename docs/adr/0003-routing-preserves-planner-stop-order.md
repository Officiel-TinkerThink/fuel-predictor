# ADR 0003: Preserve Planner Stop Order

## Status

Accepted

## Context

Fuel planning must reflect the sequence a planner intends to execute. Reordering stops would change the operational plan.

## Decision

Calculate route distance using the exact entered stop order. Use a routing-provider adapter and permit a flagged manual-distance fallback when routing fails. Do not optimize routes.

## Consequences

The MVP produces explainable distance inputs and can later adopt a company location catalog without changing the route contract.

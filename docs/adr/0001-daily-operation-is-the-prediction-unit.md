# ADR 0001: Use Daily Operation as the Prediction Unit

## Status

Accepted

## Context

One source row can describe a complete day's multi-stop travel and lifting activity. It is not reliably a single origin-to-destination trip.

## Decision

The prediction unit is a DailyOperation. It contains the full stop sequence, distance, activity mode, lifting hours, vehicle category, and newly issued fuel target.

## Consequences

The application avoids treating `Dari`/`Ke` as a complete route. It can later add route optimization as a separate capability without changing historical meaning.

# ADR 0004: Require Manual Model Promotion

## Status

Accepted

## Context

The system will monitor data drift and performance, but early data has limited verified actual-fuel outcomes.

## Decision

Dataset upload creates a versioned validated dataset. Training creates a candidate model. Dashboard alerts may recommend retraining, but promotion of a candidate to active model is an explicit manual action.

## Consequences

The system supports learning while preventing unreviewed regression from reaching planning users.

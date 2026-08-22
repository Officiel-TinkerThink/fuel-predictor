# ADR 0005: Use a Clean Domain-Driven Modular Monolith

## Status

Accepted

## Context

The Fuel Prediction MVP needs a maintainable application, not scattered route handlers, spreadsheet scripts, and model code. It must remain locally simple while supporting future routing, monitoring, AI, and deployment integrations.

## Decision

Build a domain-driven modular monolith with data contracts, inward dependency flow, test-first behavioral verification, and explicit meaningful domain events. Use event dispatch within the application initially; do not introduce distributed event infrastructure without a concrete need.

## Consequences

Business logic stays testable and reusable across the form, API, bulk imports, and later AI interface. The project avoids premature microservices while retaining clear seams for future extraction.

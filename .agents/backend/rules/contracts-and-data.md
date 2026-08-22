# Backend contracts and data

Apply when changing APIs, messages, persistence, schemas, or data transformations.

- Treat public inputs and outputs as explicit versioned contracts. Validate data at the boundary and return stable, safe error shapes.
- Keep internal models separate from transport and storage representations when their concerns differ. Do not expose provider errors, secrets, or implementation details.
- Make authorization and ownership decisions on the server using trusted context. Client-supplied identity or permission data is untrusted.
- Design state changes to be idempotent when callers, jobs, or providers can retry. Define pagination, ordering, and limits deliberately for collections.
- Evolve persisted data safely: make changes compatible with running versions, backfill in manageable batches, and document or test recovery.
- Preserve data quality with explicit constraints, identifiers, timestamps, lifecycle states, and retention decisions appropriate to the feature.

## Check

Before finishing, verify every changed boundary has clear validation, error handling, and compatibility expectations.

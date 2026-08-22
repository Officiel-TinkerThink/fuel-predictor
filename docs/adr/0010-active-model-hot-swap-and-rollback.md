# ADR 0010: Swap the active model in process under optimistic concurrency

## Status

Accepted

## Context

The plan requires activating a validated candidate without dropping prediction requests, and a
one-action rollback to a retained known-good model. Two administrators, or an administrator and an
agent, must not be able to silently overwrite each other's decision. The VM has 1-2 GB RAM, so the
active and candidate models cannot always be assumed to fit in memory together.

Today `GenerateFuelPrediction` loads the active model through the model store on demand, and
promotion only changes a row's lifecycle status.

## Decision

Hold the active model in a single in-process holder that owns a loaded model together with the
version it was loaded from. Prediction reads the holder's current reference once per request and
uses that reference for the whole request; a request that started under the previous model finishes
under the previous model.

Activation runs as an ordered sequence:

1. Load and warm the candidate while the active model keeps serving.
2. Run the package's deterministic smoke tests against the loaded candidate.
3. Persist the lifecycle transition in one database transaction that also asserts the current active
   version still equals `expected_current_version`.
4. Swap the holder's reference to the warmed candidate.
5. Run a post-activation health check.

If any step before the swap fails, the previous model stays active and stays loaded. If the health
check in step 5 fails, the operator is shown a recovery-oriented message and rollback is offered;
the failed version is not silently reverted, because an automatic revert would hide a real problem.

Activation and rollback both require `expected_current_version`. A mismatch is rejected as a
conflict naming the version that is actually active, so the caller can re-read and decide again.
The database transaction is the arbiter: the in-memory swap only happens after the transaction
commits, so two concurrent activations cannot both win.

Before loading a candidate, compare the manifest's declared memory envelope against available
memory. If the active and candidate models cannot coexist, reject activation with an explicit
capacity message rather than risking an out-of-memory kill of the serving process.

Retain the previous known-good artefact and its metadata after activation. Rollback re-activates a
retained version through the same sequence and records the administrator and a required reason.

## Research and adaptation

- CPython guarantees that rebinding a single attribute is atomic with respect to other threads, so a
  reference swap needs no lock on the read path. The load-and-warm path is serialised with a lock so
  only one activation runs at a time. This is the standard read-mostly pattern rather than anything
  novel.
- [PostgreSQL transaction isolation](https://www.postgresql.org/docs/current/transaction-iso.html)
  gives us the conditional update that implements `expected_current_version`. We use a single
  `UPDATE ... WHERE version = :expected` and treat a zero row count as the conflict, which needs no
  serialisable isolation and no advisory lock.
- The optimistic-concurrency contract mirrors HTTP `If-Match`/`ETag` semantics, which is why the
  same `expected_current_version` argument appears in the REST routes and in the deferred MCP tools.

We rejected process restart as the activation mechanism: it drops in-flight requests and cannot meet
the "without dropping prediction requests" criterion. We rejected a blue/green second container
because doubling the resident application does not fit the memory envelope.

## Consequences

Prediction gains a holder in the composition root, and its lifetime is tied to the application
process rather than to a request. Tests that assert model behaviour must go through the holder, and
a restart re-loads the active model from its persisted version rather than trusting memory.

Because rollback requires the previous artefact, retention policy is now a correctness concern, not
just a disk concern: the retention job must never delete the model that rollback would target.

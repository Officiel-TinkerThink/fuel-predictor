# ADR 0011: Remove the MLflow server from production once package ingestion reaches parity

## Status

Accepted

## Context

`compose.yaml` runs an MLflow server next to the application and PostgreSQL, and
`MlflowBaselineModelStore` is the only way the application stores or loads a model. That made sense
while training happened inside the product.

ADR 0009 moves training out of production entirely. Once candidates arrive as validated packages,
production no longer needs an experiment tracker: it needs to load one approved artefact and record
which version is active. Meanwhile the MLflow service consumes memory that the plan's 1-2 GB
envelope cannot spare, ships a large dependency tree into the production image, and adds a second
stateful volume to back up.

## Decision

MLflow belongs to the external training environment, not to production.

Introduce a `ModelArtifactStore` port with two implementations behind it: the existing MLflow-backed
store, and a filesystem store that reads the versioned model directory populated by package
ingestion. Production selects the filesystem store; the MLflow store remains available for local
development and for the transition period.

Keep the MLflow service in `compose.yaml` until package ingestion has parity, defined as: a package
can be uploaded, validated, activated, rolled back, and served, and the monitoring and comparison
screens read the same metrics they read today. When that parity is demonstrated, remove the `mlflow`
service and its volume from the production Compose file, drop MLflow from the production image's
dependencies, and keep it only as an optional development extra.

The training environment continues to use MLflow for experiment tracking. The boundary between the
two is the package format, not a shared tracking server, so production never reaches across the
network to MLflow at prediction time.

## Research and adaptation

- [MLflow tracking](https://mlflow.org/docs/latest/tracking.html) is designed around experiment
  tracking and model registry workflows during development. Nothing in the production serving path
  requires it once the artefact and its metadata are pinned, which is precisely what ADR 0009's
  manifest does.
- The plan's own resource envelope forces the question: MLflow's server, its SQLite backend store,
  and its artifact root are all counted against the same 1-2 GB as PostgreSQL and the application.
  Removing it is the single largest reduction available without weakening a product capability.

We rejected keeping MLflow purely as a model registry in production. It would remain a stateful
service to back up and upgrade in exchange for metadata that the manifest and PostgreSQL already
hold.

## Consequences

`TrainBaselineCandidate` and the local baseline path keep working through the MLflow store during
the transition, so this ADR does not break the existing MVP flow on the day it is accepted. The
parity condition is a real gate: removing the service early would leave no way to produce a model.

After removal, local development that wants experiment tracking runs MLflow itself or uses the
training repository. Backup procedures lose the `mlflow_data` volume and gain the versioned model
directory, which must be updated in the operations runbook at the same time.

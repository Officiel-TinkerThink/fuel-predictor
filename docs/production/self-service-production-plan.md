# Self-Service Production Plan

## Status

Proposed implementation plan for taking the current local MVP to a small, self-service
production deployment. This document does not replace the accepted ADRs. Any implementation
that changes an accepted decision must add a superseding ADR first.

## Context

The expected production workload is small:

- no more than five human users;
- approximately 200 prediction requests per day;
- model training can run outside the production machine;
- the primary operator is non-technical and may not have regular technical support;
- the product needs a polished Indonesian-language interface;
- prediction, monitoring, model lifecycle, and agent access must remain auditable;
- standards-compliant agent harnesses should be able to connect through MCP.

The current project already provides a domain-driven modular monolith, FastAPI delivery,
PostgreSQL persistence, Alembic migrations, MLflow-backed baseline candidates, Evidently drift
checks, manual model promotion, actual-fuel collection, and monitoring dashboards. Production
work should extend those seams instead of introducing a parallel application.

## Goals

1. Let a non-technical operator complete routine work from a clear web interface.
2. Serve individual and bulk fuel predictions reliably on a small VM.
3. Train candidate models outside production and ingest approved model packages safely.
4. Activate validated candidates without interrupting prediction traffic.
5. Preserve manual promotion and one-action rollback.
6. Distinguish service health, data drift, and measured model performance.
7. Expose safe prediction and observability capabilities through MCP.
8. Automate backups, monitoring runs, certificate renewal, restart, and retention.

## Non-goals

- Kubernetes, Kubeflow, a feature store, or distributed workflow infrastructure.
- Training or AutoML workloads on the production VM.
- Automatic model promotion based only on an experiment score or drift alert.
- Anonymous public MCP access.
- Uploading model binaries as MCP tool arguments.
- Replacing PostgreSQL with SQLite without superseding ADR 0006.

## Target production topology

```text
Human browser                         MCP client / agent harness
      |                                         |
      +---------------- HTTPS ------------------+
                            |
                 Existing gateway or Caddy
                            |
                FastAPI modular monolith
                +-----------------------+
                | Web UI                |
                | REST API              |
                | MCP /mcp endpoint     |
                | Auth and audit        |
                | Prediction service    |
                | Model lifecycle       |
                | Monitoring queries    |
                +-----------------------+
                     |              |
                 PostgreSQL     Versioned model directory
                                      |
                              Remote encrypted backup
```

Caddy is optional when the VM already has a reliable HTTPS gateway such as Nginx, Traefik, or a
provider-managed proxy. The requirement is one maintained HTTPS entry point, not Caddy itself.

## Production stack

| Concern | Production choice | Notes |
|---|---|---|
| Application | Existing FastAPI modular monolith | Keep one deployable application. |
| Human UI | Server-rendered templates with progressive enhancement | Avoid a second runtime service; use a coherent design system and local static assets. |
| API | Existing versioned REST API | UI and MCP call the same application use cases. |
| Agent interface | Official Python MCP SDK mounted at `/mcp` | Use Streamable HTTP and scoped authorization. |
| Persistence | PostgreSQL + SQLAlchemy + Alembic | Preserve ADR 0006 and existing repositories. |
| Model registry | PostgreSQL metadata plus versioned artifacts | MLflow remains primarily in the external training environment. |
| Monitoring | Existing Evidently adapter plus scheduled application command | Store compact report summaries; do not run a separate Evidently server. |
| HTTPS/static files | Existing gateway or Caddy | Automatic certificate renewal and one public origin. |
| Packaging | Docker Compose | Application and PostgreSQL; add a proxy only when needed. |
| Backup | Encrypted PostgreSQL dump and model/report archive | Copy off the VM and test restoration. |

## External training environment

Training may run on a developer machine, Colab, a temporary cloud runner, or another controlled
machine with sufficient CPU and memory. It owns:

- dataset preparation and version identification;
- AutoML or controlled candidate search;
- cross-validation and untouched test evaluation;
- MLflow experiment tracking;
- model packaging and signing/checksum generation.

AutoML selects a candidate; the project's evaluation and promotion policy decides whether it is
eligible for production.

### Model package contract

Production accepts a documented archive, for example:

```text
fuel-model-2026.08.22.1.zip
+-- model.onnx or model.skops
+-- manifest.json
+-- input-schema.json
+-- reference-statistics.json
+-- smoke-tests.json
+-- checksum.sha256
```

The manifest must include at least:

- unique model version;
- model format and runtime compatibility version;
- target definition and unit;
- feature-contract version and ordered feature schema;
- training dataset version;
- training timestamp and source-code revision;
- global and per-category evaluation metrics;
- labeled test-set size;
- model size and expected memory envelope;
- checksum of every package member.

Prefer ONNX when the complete preprocessing and estimator pipeline can be exported faithfully.
Use a constrained format such as `skops` when ONNX cannot represent the pipeline. Do not accept
arbitrary Pickle or Joblib uploads from users because loading them can execute code.

## Model ingestion and zero-downtime activation

### States

```text
uploaded -> validating -> candidate -> active -> retired
                    \-> rejected
```

Upload never implies activation.

### Validation

The server must:

1. enforce archive and extracted-size limits;
2. generate storage paths itself and reject path traversal;
3. verify checksums and optional package signature;
4. validate the manifest and input schema;
5. confirm feature-contract and runtime compatibility;
6. load the candidate in an isolated validation step;
7. execute deterministic smoke-test cases;
8. compare declared metrics with the current model and configured policy;
9. persist the result and full audit record.

### Activation

Keep the active model serving while the candidate is loaded and warmed. After smoke tests pass,
atomically swap the in-memory active-model reference and persist the new active version in the
same lifecycle operation. Requests already using the previous model may finish normally; new
requests use the new model. Retain the previous known-good artifact for rollback.

Activation and rollback accept `expected_current_version` so two administrators or agents cannot
silently overwrite each other's decision. If the candidate and active model cannot coexist in
available memory, reject activation with a clear capacity message rather than risking an
out-of-memory crash.

Manual promotion remains mandatory, in accordance with ADR 0004.

## User experience plan

The production UI is Indonesian-first and uses business language. Technical identifiers and raw
statistics belong in expandable details, not the primary workflow.

### Navigation

```text
Ringkasan
Operasi Harian
  - Buat Prediksi
  - Prediksi Massal
  - Riwayat Prediksi
BBM Aktual
  - Catat Aktual
  - Impor Massal
Pemantauan
  - Kinerja Model
  - Pergeseran Data
  - Kesehatan Sistem
Model
  - Model Aktif
  - Unggah Kandidat
  - Riwayat dan Rollback
Integrasi Agen
Pengaturan
```

### Design system

Create reusable templates/components for:

- application shell, responsive navigation, breadcrumbs, and page headers;
- form fields with units, examples, and inline Indonesian validation;
- status badges with text and icons in addition to color;
- metric cards that always show period and sample size;
- tables with search, filters, empty states, and CSV export;
- confirmation dialogs for activation, rollback, credential revocation, and destructive actions;
- progress/step indicators for bulk import and model ingestion;
- alert banners that state the problem, impact, and recommended action;
- accessible charts with table equivalents.

Use locally served assets so the application remains usable when external CDNs are unavailable.
Meet basic keyboard navigation, focus visibility, contrast, semantic labeling, and mobile/tablet
layout requirements.

### Overview dashboard

The first page should answer:

- Is the service healthy?
- Which model is active?
- How many predictions were made in the selected period?
- Is there meaningful data drift?
- Is measured performance stable, degraded, or unavailable?
- How many actual-fuel outcomes are still missing?
- Did the latest monitoring run and backup succeed?

Do not report model performance when actual outcomes are unavailable. Show `Belum cukup data`
with the labeled-sample requirement and a direct link to upload actual outcomes.

### Prediction workflow

- Use descriptive Indonesian labels and display units beside every numeric input.
- Preserve entered values after validation errors.
- Show manual route fallback prominently when routing fails.
- Present estimated requirement, recommended allocation, uncertainty, model version, and warnings
  as separate concepts.
- Provide a printable/downloadable result with operation ID and lineage.

### Bulk workflow

Use a guided flow:

```text
Unduh template -> Unggah -> Validasi -> Pratinjau -> Proses -> Unduh hasil/perbaikan
```

Valid rows may proceed while invalid rows remain quarantined with actionable correction messages,
preserving the current data policy.

### Monitoring UX

Separate three views:

1. **Kesehatan sistem**: availability, error rate, latency, disk, monitoring freshness, and backup.
2. **Pergeseran data**: reference/current windows, sample sizes, changed features, and plain-language
   recommendations.
3. **Kinerja model**: MAE, RMSE, sMAPE, interval coverage, bias, and category breakdown only from
   matched actual outcomes.

At the expected volume, default drift presentation should use a stable weekly/current window rather
than imply confidence from a handful of recent rows. Existing minimum-sample behavior remains
visible.

### Model-management UX

Use a five-step wizard:

```text
Unggah -> Validasi -> Bandingkan -> Konfirmasi -> Verifikasi
```

The comparison must show current and candidate metrics, sample sizes, model size, compatibility,
and validation warnings. Successful activation runs a post-switch health check. A failed activation
leaves the previous model active and displays a recovery-oriented message. Rollback requires explicit
confirmation and records the administrator and reason.

## Authentication and authorization

The existing MVP has no accounts, but internet-facing production and MCP require them.

Initial human roles:

- `operator`: create predictions, import operations, and record actual fuel;
- `manager`: view monitoring and model comparisons;
- `administrator`: manage users, upload/promote/rollback models, manage agent credentials, and view
  audit logs.

Use secure password hashing, server-side authorization checks, secure HTTP-only session cookies,
CSRF protection for browser mutations, login rate limits, session expiry, and password reset.
Administrative operations should support a second factor when feasible.

## MCP plan

Mount the MCP application at `/mcp` in the same ASGI process. MCP is a delivery adapter: its tools
call the same application-layer use cases as HTTP forms and REST routes. Do not duplicate business
rules in MCP handlers.

### Initial read/compute tools

- `predict_fuel`
- `get_service_health`
- `get_drift_summary`
- `get_performance_summary`
- `get_current_model`
- `list_model_versions`
- `get_prediction_input_schema`

### Deferred privileged tools

- `validate_model_candidate(artifact_id)`
- `activate_model_candidate(artifact_id, expected_current_version)`
- `rollback_model(target_version, expected_current_version)`

Model binary upload stays in the authenticated web/REST upload flow. MCP receives only an opaque
artifact ID after upload. Keep privileged MCP tools disabled until read-only MCP operation and
auditing have been proven in production.

### MCP security

- expose MCP only over HTTPS;
- use standards-compatible OAuth for broad remote-client compatibility;
- issue a distinct identity and scopes to every agent client;
- start ordinary clients with `fuel:predict`, `fuel:monitor`, and `models:read` only;
- validate JSON Schema inputs and outputs;
- apply per-client rate and request-size limits;
- audit caller, tool, arguments summary, result status, model version, and timestamp;
- never forward inbound MCP credentials to another service;
- make activation and rollback explicit, separately scoped operations.

No separate MCP container, Redis instance, message broker, or database is needed at this scale.

## Monitoring execution

Move expensive reconciliation and drift calculation out of interactive page requests where needed.
Provide an idempotent application command, for example:

```text
python -m fuel_predictor monitor
```

Run it daily using the host scheduler or a small scheduled Compose job. Store report summaries and
timestamps in PostgreSQL so the UI and MCP read precomputed results quickly. Monitoring failures
must not interrupt prediction serving.

## Operations and recovery

Automate:

- container restart and health checks;
- HTTPS certificate renewal at the gateway;
- daily PostgreSQL backups;
- backup of active/candidate model artifacts and report metadata;
- encrypted off-VM backup upload;
- log rotation and model/report retention;
- disk, uptime, failed-backup, and failed-monitoring alerts;
- operating-system security updates in a controlled maintenance window.

Document and test:

- restoring PostgreSQL and model artifacts to a clean machine;
- rolling back the application image and database migration safely;
- rolling back the active model;
- rotating human and MCP credentials;
- operating temporarily without the route provider;
- recovering when object storage or monitoring is unavailable.

## Resource envelope

Training is excluded from production sizing.

Minimum target for a small model:

```text
1 vCPU
1 GB RAM
20 GB available SSD
```

Preferred operational headroom:

```text
1-2 vCPU
2 GB RAM
20-40 GB available SSD
```

The polished UI is delivered as static assets/templates and MCP is mounted in the existing ASGI
process, so neither materially changes the machine class. The main transient memory requirement is
holding active and candidate models together during validation/activation. PostgreSQL and the
current MLflow service must also be counted until external model-package ingestion allows MLflow to
be removed from the production Compose topology.

## Delivery phases

### Phase 1: Production product shell

- add authenticated users, roles, sessions, and audit records;
- introduce the reusable Indonesian design system and responsive application shell;
- redesign overview, prediction, bulk import, actual-fuel, monitoring, and model pages;
- add accessibility and browser-level workflow tests.

### Phase 2: External model ingestion

- define and publish the package JSON Schemas;
- build the external packager and production upload endpoint;
- implement staged validation and compatibility checks;
- implement atomic activation, post-activation verification, and rollback;
- retain the existing MLflow path until package ingestion has parity.

### Phase 3: Operational monitoring

- add scheduled, idempotent monitoring execution;
- store report summaries for fast UI/MCP reads;
- add service-health and backup state;
- add external alerts with plain-language remediation.

### Phase 4: MCP read-only launch

- mount Streamable HTTP MCP in FastAPI;
- implement prediction and monitoring tools/resources;
- add OAuth/scopes, per-client credentials, rate limits, and audit UI;
- verify compatibility with representative harnesses.

### Phase 5: Privileged MCP operations

- expose validate/activate/rollback by artifact ID only if required;
- require stronger scopes, optimistic concurrency, server-side policy, and human confirmation where
  the client supports it;
- perform a security review before enabling these tools.

### Phase 6: Deployment hardening and handoff

- configure HTTPS gateway, backups, restore rehearsal, alerts, and retention;
- create an operator guide in Indonesian with screenshots;
- create a technical recovery runbook;
- conduct a non-technical usability test and correct the observed friction;
- complete a handoff drill covering prediction, bulk import, actual fuel, monitoring, model upload,
  activation failure, rollback, and credential revocation.

## Acceptance criteria

The production plan is complete when:

- an operator can complete individual and bulk predictions without technical assistance;
- all visible validation and recovery messages are understandable in Indonesian;
- model upload cannot overwrite or activate the current model implicitly;
- a valid candidate can be activated without dropping prediction requests;
- a failed candidate leaves the current model active;
- rollback restores a retained known-good model and creates an audit record;
- drift reports state reference/current windows and sample sizes;
- performance reports use matched actual outcomes and clearly report insufficient labels;
- MCP prediction and monitoring work through a standards-compliant remote client;
- each MCP client has revocable scoped credentials and every call is audited;
- model binaries are never transferred through MCP tool arguments;
- backup restoration succeeds on a clean environment;
- a non-technical user can complete the documented operating procedures;
- production runs within the measured VM memory/disk envelope under model activation and monitoring
  workloads.

## Decisions requiring follow-up ADRs

Before implementation, record or supersede decisions for:

1. production UI delivery approach and design-system dependency;
2. human authentication/session strategy and MCP authorization provider;
3. external model package format and trusted serialization formats;
4. active-model hot-swap and rollback consistency guarantees;
5. production MLflow topology after external training is introduced;
6. production HTTPS gateway and backup destination.

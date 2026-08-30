# Handoff — start here

Single entry point for anyone (person or agent) picking this project up cold. Read this file
first, then follow the links. It answers four questions: what this is, what has been built, where
things live, and what to do next.

Last updated: 2026-08-31.

## 1. What this is

**Fuel Predictor** — an Indonesian-language web application that predicts the fuel a heavy-vehicle
(**ANGBER**) *daily operation* needs, records what was actually consumed afterwards, and monitors
whether the model is still trustworthy.

The distinction that governs the whole domain: the number the app produces is fuel **to prepare**
(*prepared fuel*, the training label), not fuel **consumed** (*actual fuel*, ground truth recorded
later). Confusing the two invalidates every metric. See [CONTEXT.md](CONTEXT.md) for the glossary
and [ADR 0002](docs/adr/0002-prepared-and-actual-fuel-are-distinct.md).

Model promotion is **always manual** — there is no auto-promotion path anywhere
([ADR 0004](docs/adr/0004-candidate-models-require-manual-promotion.md)).

## 2. Where to read next, in order

| Read | For |
|---|---|
| [CONTEXT.md](CONTEXT.md) | Domain glossary. Terminology is load-bearing here. |
| [docs/adr/](docs/adr/) | The 12 decisions already made. **Read the relevant ADR before changing anything it covers** — several encode a trap, not just a preference. |
| [docs/production/implementation-progress.md](docs/production/implementation-progress.md) | The detailed running log: every phase item, why it was built that way, and what each bug taught. The authoritative record. |
| [docs/prd/fuel-prediction-mvp.md](docs/prd/fuel-prediction-mvp.md) | Original product requirements. |
| [docs/production/self-service-production-plan.md](docs/production/self-service-production-plan.md) | The six-phase plan this work was executed against. |
| [AGENTS.md](AGENTS.md) | Agent working rules; points at `.agents/` and `docs/agents/`. |
| [README.md](README.md) | Local run instructions and the demo walkthrough (Indonesian). |
| [docs/production/server-deployment.md](docs/production/server-deployment.md) | Standing the system up on a server, first time through. |
| [docs/production/recovery-runbook.md](docs/production/recovery-runbook.md) | When a deployment that exists has gone wrong. Symptom-first. |

## 3. What is built

All six phases of the production plan are implemented. 334 tests pass; `ruff check` and
`mypy --strict` are clean.

### Prediction and operations

- Create a daily operation and get an estimated fuel requirement, a conservative **recommended
  allocation**, and an uncertainty range — via the Indonesian web form (`/prediksi`) or the JSON
  API (`POST /api/v1/daily-operations`). Both paths share the same domain rules.
- **Ordered stop sequences** with planner order preserved
  ([ADR 0003](docs/adr/0003-routing-preserves-planner-stop-order.md)), Google Maps distance when a
  key is configured, and an explicit manual fallback when it is not.
- **Bulk operation prediction** by CSV upload (`/prediksi-operasi-massal`), with a per-row
  correction report for rejected rows.
- **Actual-fuel recording**, single (`/bahan-bakar-aktual`) and bulk, matched back to operations
  for evaluation.
- **Historical dataset import** (`/impor-data-historis`) with a downloadable sample CSV, plus
  manual baseline-candidate training from an imported dataset version.

### Identity and access

- Users, roles (`operator` / `manager` / `administrator`), sessions, CSRF, and an audit log
  (`/pengguna`, `/audit`).
- **`ROUTE_CAPABILITIES` in [`delivery/security.py`](src/fuel_predictor/delivery/security.py) is
  the single source of truth** for which capability a route requires. Add every new route there;
  `tests/test_route_capability_coverage.py` fails if you don't.
- Bootstrap admin via `FUEL_PREDICTOR_BOOTSTRAP_ADMIN_USERNAME` / `..._PASSWORD`, so a fresh
  deployment is signable-into with no manual SQL step.
- **Unprovisioned mode**: before the first user exists, every request is treated as an
  authenticated administrator with no CSRF. This is what keeps the original MVP tests passing. A
  real deployment always provisions an admin at startup and so never runs in this mode.

### Model lifecycle

- **External model packages** ([ADR 0009](docs/adr/0009-external-model-package-format.md)): zip
  packages with a JSON-Schema-validated manifest, reference statistics, and smoke tests that run
  before anything can be activated. Upload at `/model/unggah`.
- **Hot-swap activation and rollback**
  ([ADR 0010](docs/adr/0010-active-model-hot-swap-and-rollback.md)) with retention of prior package
  bytes — rollback needs the target's artefact, so packages are retained and backed up alongside
  the database.
- Governance dashboard, candidate comparison, and **manual promotion only**
  (`/pengelolaan-model`, `/kandidat-model/{id}/perbandingan`, `/model/riwayat`).
- MLflow for baseline training and tracking
  ([ADR 0011](docs/adr/0011-production-mlflow-topology.md)).

### Monitoring

- Three views: **Kesehatan Sistem** (alerts, data quality, dataset validation, missing-actual
  backlog, infra metrics, backup status), **Pergeseran Data** (Evidently-backed feature drift in
  plain language), **Kinerja Model** (MAE / RMSE / sMAPE / interval coverage, overall and
  per-category, plus a rolling error trend).
- **Alert delivery** with remediation text, over webhook and/or SMTP.
- Monitoring runs on a schedule as a `monitor` service in the deployment, not host cron, so it
  cannot be forgotten at install time.

### Agent / MCP surface

- **Read-only MCP tools** (shipped enabled): `predict_fuel`, `get_service_health`,
  `get_drift_summary`, `get_performance_summary`, `get_current_model`, `list_model_versions`,
  `get_prediction_input_schema`.
- **Privileged MCP tools** — `validate_model_package`, `activate_model_version`,
  `rollback_model_version` — implemented but **shipped disabled** behind
  `FUEL_PREDICTOR_MCP_PRIVILEGED_TOOLS_ENABLED`. They require a confirmation token and are audited.
  **Do not enable them in production until the security review in section 5 is done.**
- Agent client credentials managed at `/integrasi-agen`, with per-client rate limiting
  (`FUEL_PREDICTOR_MCP_MAX_CALLS_PER_WINDOW`). Every call is audited, and an MCP *preview* is
  distinguished from a real activation in the audit trail.

### Deployment

- [`compose.prod.yaml`](compose.prod.yaml) — `db`, `mlflow`, `app`, `caddy`, `monitor`. Caddy
  terminates TLS with automatic Let's Encrypt
  ([ADR 0012](docs/adr/0012-https-gateway-and-encrypted-backup.md)).
- **Only the gateway publishes ports** (80, 443/tcp, 443/udp). `compose.prod.yaml` is deliberately
  standalone, *not* an overlay on `compose.yaml`, because Compose merges `ports` across `-f` files
  and cannot unpublish a port an earlier file published — an overlay would leave the app and
  MLflow reachable on the host without TLS. Verify with
  `docker compose -f compose.prod.yaml config | grep -c published`, which must return 3.
- Proxy header trust is bounded: uvicorn runs with `--proxy-headers` *and*
  `--forwarded-allow-ips`. Without the second flag any client could forge its own source address
  and poison the audit trail.
- **Encrypted off-VM backup** ([`deploy/backup.sh`](deploy/backup.sh)): `pg_dump` plus the retained
  model packages, `age`-encrypted to a *public* recipient key and uploaded via `rclone`. The VM
  holds no key capable of decrypting its own backups. Retention: 7 daily, 4 weekly, 3 monthly.
- **Rehearsable restore** ([`deploy/restore.sh`](deploy/restore.sh)), which prints the four checks
  that decide whether the restore actually worked.
- Backup outcomes are *recorded*, not inferred: `python -m fuel_predictor record-backup`, called by
  the backup script.

### Documentation and drills

- [Indonesian operator guide](docs/production/panduan-operator.md) (plus an HTML build, screenshots
  captured) — no technical commands, written for the non-technical user.
- [Technical recovery runbook](docs/production/recovery-runbook.md) — symptom-first, usable at 2am
  by someone who did not build this.
- [Handoff drill and usability protocols](docs/production/handoff-drill.md).
- Browser end-to-end scenarios that actually execute `app.js`: `python scripts/browser_e2e.py`
  (24 checks over six scenarios). The pytest suite asserts against server-rendered HTML and never
  runs `app.js`, so this script covers a real blind spot — its first run found a toggle that had
  never worked.

## 4. Codebase map

Clean domain-driven modular monolith
([ADR 0005](docs/adr/0005-use-a-clean-domain-driven-modular-monolith.md)), PostgreSQL + Alembic
([ADR 0006](docs/adr/0006-postgresql-persistence-and-migrations.md)), server-rendered Jinja UI with
a local design system ([ADR 0007](docs/adr/0007-server-rendered-ui-with-a-local-design-system.md)).

```
src/fuel_predictor/
  domain/          business rules, no framework imports
  application/     use cases; the layer delivery calls
  infrastructure/  SQLAlchemy repos, MLflow, Evidently, Google Maps, hashing, artefact store
  delivery/        FastAPI routers, one <feature>_pages.py per area, each a build_<name>_router
    security.py        ROUTE_CAPABILITIES — the source of truth for authorization
    rendering.py       Jinja environment, NAVIGATION, view-model helpers
    templates/         base.html shell, components.html macros, one file per page
    static/            app.css, app.js (progressive enhancement only — no page requires JS)
    mcp_server.py      read-only agent tools
    mcp_privileged.py  gated write tools
  packaging/       model package builder
alembic/           migrations
deploy/            Caddyfile, backup.sh, restore.sh
scripts/           browser_e2e.py and MCP verification helpers
```

`delivery/form.py` — the original f-string page builder — **is deleted**. If you find a reference
to it, the reference is stale.

## 5. What is open

Four items. Three of them cannot be closed by writing code, which is exactly why they are still
open: each is a check on work performed by the person who built it.

1. **Usability test** with a real non-technical participant —
   [protocol](docs/production/handoff-drill.md).
2. **Handoff drill** with an incoming technical owner. Exercises 5–12 were each verified
   individually against a running server during implementation; what has not happened is *a person
   other than the builder* performing them end to end.
3. **Security review** before enabling the privileged MCP tools.
4. **Package signature verification** — optional. It adds provenance, not integrity; integrity is
   already covered by the manifest validation and smoke tests.

Known code-level gaps:

- Nav items the plan names but that have no page yet are deliberately absent from
  `rendering.NAVIGATION` rather than linked to a placeholder. Add each back to `NAVIGATION` as its
  page ships — `tests/test_navigation_links.py` will then cover it.
- Accessibility is checked by `tests/test_accessibility.py` against a written checklist, but
  nothing automated runs axe-core or a real a11y engine.
- `CONTEXT.md`'s "Product boundary" paragraph is updated as of this file's date; if you change the
  product boundary, update it there too — the glossary above it is the part agents rely on most.

## 6. Working rules for the next agent

- **Run `pytest`, `ruff check`, and `mypy --strict` before every commit.** All three are clean
  today; keep them that way.
- **Read the relevant ADR before changing what it covers.**
- **New route? Add it to `ROUTE_CAPABILITIES`.** A missing entry once meant any authenticated
  caller of any role could train a model.
- **Retiring a route? `grep -rn "<old-path>" src/fuel_predictor/` before deleting it.**
  `test_navigation_links.py` only checks `NAVIGATION` entries, not arbitrary in-template links —
  three templates once pointed at deleted routes and no test caught it.
- **CSRF plus `extra="forbid"`**: strip the submitted `csrf_token` field out of a dict before it
  reaches a Pydantic model with `model_config = ConfigDict(extra="forbid")`, or validation 422s.
- **Scripted `httpx` sign-in**: the sign-in page's hidden CSRF token is a *pre-session*
  double-submit token. It works for `POST /masuk` and 403s on everything after. Fetch any
  authenticated page once signed in and read *its* `csrf_token` — that value is stable for the
  whole session.
- **SQLite tests enforce foreign keys** (`PRAGMA foreign_keys=ON`), so the suite fails where
  production fails. Do not turn this off; it is what surfaced two real production 500s.
- Issues and specs live as local Markdown under `.scratch/` (mostly gitignored, except
  `.scratch/fuel-prediction-mvp/`). See [docs/agents/issue-tracker.md](docs/agents/issue-tracker.md).

## 7. Branches

Remote: `https://github.com/Officiel-TinkerThink/fuel-predictor.git`

| Branch | Role |
|---|---|
| `main` | Integration / default branch. |
| `develop` | Shared development line. |
| `local` | Local-environment line. |
| `production-plan` | Where the six-phase production work was carried out. |
| `master` | Holds only the `Baseline: local MVP before production work` commit — the wholesale rollback point. Not part of the working flow, local only. |

Everything except `master` is pushed to `origin`.

## 8. Running it

**Local, with Docker (PostgreSQL included):**

```bash
cp .env.example .env
docker compose up --build
```

Set `POSTGRES_PASSWORD` in `.env` first.

**Local, without Docker** (needs PostgreSQL 16 and Python 3.12+):

```bash
python -m venv .venv && .venv/bin/python -m pip install -e ".[dev]"
```

Then set `FUEL_PREDICTOR_DATABASE_URL` in `.env`, run `alembic upgrade head`, and start
`uvicorn fuel_predictor.main:app --reload`. On Windows use `.venv\Scripts\` in place of
`.venv/bin/`; README.md has the PowerShell form.

**On a server** — follow
[docs/production/server-deployment.md](docs/production/server-deployment.md) top to bottom; it is
the step-by-step first deployment, including verification, backups, and the restore rehearsal.
In short: point a DNS A record at the VM, set `DOMAIN`, `ACME_EMAIL`, `POSTGRES_PASSWORD`, the
bootstrap admin credentials, `FUEL_PREDICTOR_FORWARDED_ALLOW_IPS`, and the backup variables in
`.env`, and run:

```bash
docker compose -f compose.prod.yaml up -d --build
```

Caddy obtains the certificate on the first request. Then rehearse `deploy/restore.sh` **before**
you need it — a restore first attempted during an incident is not a backup strategy.

Every environment variable is documented in [.env.example](.env.example).

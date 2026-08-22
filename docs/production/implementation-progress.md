# Production Plan Implementation Progress

Tracks work against [self-service-production-plan.md](self-service-production-plan.md) across
sessions. Update this file whenever a phase item lands or a design decision is made, so a fresh
session (or a different model) can resume without re-deriving context.

## How the codebase is organized right now

- `docs/adr/0007`-`0012` record the six decisions the plan deferred. Read them before changing
  anything they cover.
- Identity (users, sessions, audit) lives in `domain/identity.py`, `application/identity.py`,
  `infrastructure/password_hashing.py`, `infrastructure/sqlalchemy_identity.py`.
- Request-level auth (session middleware, CSRF, the route→capability table) lives in
  `delivery/security.py`. **`ROUTE_CAPABILITIES` in that file is the single source of truth for
  which capability a route needs** — routes themselves mostly don't call `guard.require()`
  individually (a few do, redundantly, for defense in depth). Add new routes there.
- The Jinja design system lives in `delivery/rendering.py` (environment, navigation, view-model
  helpers), `delivery/templates/` (`base.html` is the shell, `components.html` has the reusable
  macros), and `delivery/static/` (`app.css`, `app.js`).
- Every page is on the Jinja design system now. `delivery/form.py` — the original f-string page
  builder — is **deleted**; there is nothing left to migrate for Phase 1's UI redesign. Pages are
  organized by feature area, each a `delivery/<name>_pages.py` module with a `build_<name>_router`
  factory: `dashboard.py` (overview, users, audit), `prediction_pages.py` (create operation,
  estimate), `bulk_prediction_pages.py`, `actual_fuel_pages.py` (single + bulk), `monitoring_pages.py`
  (the three Pemantauan views), `historical_dataset_pages.py` (import, baseline training),
  `model_governance_pages.py` (governance dashboard, candidate comparison, promotion). Templates
  live in `delivery/templates/`, one file per page plus the shared `components.html` macros and
  `pesan.html` for simple message-and-a-link-back pages. See "Known gaps" below for what's still not
  built at all (not migrated — doesn't exist yet).
- **Legacy/unprovisioned mode**: until the first user account exists, `SecurityGuard` and the
  middleware treat every request as an authenticated administrator with no CSRF requirement. This
  is what keeps the original 34 MVP tests passing unmodified — they never create a user. A real
  deployment always provisions an administrator at startup via
  `FUEL_PREDICTOR_BOOTSTRAP_ADMIN_USERNAME` / `FUEL_PREDICTOR_BOOTSTRAP_ADMIN_PASSWORD` (or the
  `bootstrap_administrator` parameter to `create_app`), so it never runs in this mode. See
  `ResolveSession.is_system_provisioned` and `_UNPROVISIONED_CALLER` in `security.py`.
- Migration `20260822_08_users_sessions_audit.py` adds the three new tables.

## Phase 1 — Production product shell

- [x] Authenticated users, roles (`operator`/`manager`/`administrator`), sessions, audit records —
      domain, application, infrastructure, delivery, and Alembic migration all in place and tested
      (`tests/test_authentication_and_roles.py`, 7 tests).
- [x] Design system foundation: `base.html` shell, `components.html` macros (badge, metric, banner,
      error summary, form fields, steps, confirm dialog, sparkline), hand-authored `app.css` with
      light/print/reduced-motion handling, progressive-enhancement `app.js` (no page depends on JS).
- [x] Bootstrap-administrator settings (`bootstrap_admin_username`/`bootstrap_admin_password`) so a
      fresh deployment can be signed into without a manual SQL step.
- [x] Overview dashboard (`/`) — real data from `GetMonitoringDashboard` +
      `GetModelGovernanceDashboard`. Two fields are honestly `Belum tersedia` (scheduled-monitoring
      status, backup status) because Phase 3 doesn't exist yet — do not fake these.
- [x] User administration (`/pengguna`) and audit log (`/audit`) pages, both on the new template
      system.
- [x] Every remaining POST form in `delivery/form.py` (still the original f-string pages) now
      carries and validates a real CSRF token, via a `_csrf_input(csrf_token)` helper threaded
      through each render function and `_current_csrf(request)` in each route. Without this they
      would have been completely unusable the moment a real deployment provisioned an admin — CSRF
      is enforced globally at that point and these forms previously had no token field at all.
      Regression test: `test_legacy_form_pages_carry_a_working_csrf_token_once_provisioned` in
      `tests/test_authentication_and_roles.py`. Watch for the same trap in any new form: the
      submitted `csrf_token` field must be stripped out of a dict before it reaches a
      `model_config = ConfigDict(extra="forbid")` Pydantic model, or validation 422s.
- [x] Prediction form migrated to the Jinja design system — `delivery/prediction_pages.py` now owns
      `GET /prediksi`, `POST /operasi-harian`, and `POST /operasi-harian/{id}/prediksi`, replacing
      the old f-string versions in `form.py` (which are deleted, not just superseded — `_render_form`,
      `_render_success`, `_render_prediction_success`, `_render_stop_input` are gone). New templates:
      `prediksi.html`, `operasi-tersimpan.html`, `estimasi.html`, and a reusable `pesan.html` for
      simple message-and-a-link-back pages. The dynamic ordered-stop-sequence UI (add/remove/reorder,
      lifting-hours show/hide) moved from page-embedded `<script>` into `delivery/static/app.js` as
      real progressive enhancement — every control still works via plain form POST with JS off.
      New reusable macro: `ui.stop_sequence_field` in `components.html`.
- [x] Fixed `rendering.NAVIGATION`: it had been written to match the plan's *aspirational* nav
      structure, not the routes that actually exist yet, so half the sidebar 404'd (`/prediksi-massal`,
      `/bbm-aktual`, `/model`, `/pemantauan/*`, etc.) the moment a real user was signed in — none of
      the earlier manual smoke tests caught it because they only followed one link at a time. Fixed to
      point only at real routes, with comments marking which plan-named items are still missing pages
      (`Riwayat Prediksi`, `Unggah Kandidat`, `Riwayat dan Rollback`, `Integrasi Agen`, and the
      Kesehatan Sistem / Pergeseran Data split). **Regression test added**:
      `tests/test_navigation_links.py` signs in and GETs every `NAVIGATION` href, asserting none 404.
      Run this test (or extend it) any time `NAVIGATION` changes.
- [x] Fixed `format_decimal` (`rendering.py`): it always showed a fixed number of decimal places
      (`42,00`), where the original f-string pages trimmed trailing zeros (`42`, `43,2`) via Python's
      `:g` format. Existing tests asserting exact rendered numbers (`"43,2 km" in response.text`)
      caught this immediately — now trims trailing zeros while keeping thousands grouping.
- [x] Bulk-prediction upload page migrated — `delivery/bulk_prediction_pages.py` owns
      `GET`/`POST /prediksi-operasi-massal`, replacing `_render_bulk_prediction_form` and
      `_render_bulk_prediction_success` in `form.py` (deleted). New templates: `prediksi-massal.html`
      (upload form, uses `ui.steps` and `ui.file_field`) and `prediksi-massal-selesai.html` (results
      table + correction report). Verified end-to-end live (import → train → promote → bulk upload →
      9-row results table with correctly trimmed decimals) since this exercises a different code path
      (multipart `UploadFile`) than the plain-form prediction page did.
- [x] Actual-fuel pages (single + bulk) migrated — `delivery/actual_fuel_pages.py` owns
      `GET`/`POST /bahan-bakar-aktual` and `GET`/`POST /bahan-bakar-aktual-massal`, replacing all
      four `_render_actual_fuel_*`/`_render_bulk_actual_fuel_*` functions in `form.py` (deleted). New
      templates: `bbm-aktual.html`, `bbm-aktual-tersimpan.html`, `bbm-aktual-massal.html`,
      `bbm-aktual-massal-selesai.html`. Verified end-to-end live: bulk upload with one valid + one
      invalid row produced the correct accepted-row table and correction-report table in one pass.
- [x] Monitoring pages migrated and genuinely split into the plan's three views —
      `delivery/monitoring_pages.py` owns `GET /pemantauan/kesehatan-sistem`, `GET
      /pemantauan/pergeseran-data`, and `GET /pemantauan/kinerja-model`, replacing the single combined
      `/pemantauan-operasi` page (deleted) *and* absorbing the separate old `/kinerja-prediksi`
      full-history performance report into the new Kinerja Model page — the plan's nav only names one
      "Kinerja Model" item, and the two features (full-history report vs. rolling/windowed trend)
      answer the same question at different time horizons, so they're sections on one page rather than
      two competing pages. New templates: `kesehatan-sistem.html` (alerts, data quality, dataset
      validation, missing-actual backlog; infra metrics like uptime/latency/disk/backup are honestly
      `Belum tersedia` pending Phase 3, same pattern as the overview page), `pergeseran-data.html`
      (feature drift with plain-language status), `kinerja-model.html` (overall + per-category
      performance metrics, rolling error trend, category degradation). `_render_monitoring_dashboard`
      and `_render_prediction_performance` deleted from `form.py`; `_metric`/`_format_decimal` kept
      since model governance still uses them. Updated `test_monitoring_dashboard.py` for the new path
      and page title. Verified live: all three pages 200, Kinerja Model correctly showed both the
      overall/per-category metrics and matched-outcome data together.
      **Caught by manual grep, not by any test**: three templates from earlier migrations
      (`ringkasan.html`, `bbm-aktual.html`, `bbm-aktual-tersimpan.html`, `bbm-aktual-massal-selesai.html`)
      still linked to `/pemantauan-operasi` or `/kinerja-prediksi` after those routes were deleted here.
      `test_navigation_links.py` only checks `rendering.NAVIGATION` entries, not arbitrary in-template
      links — when retiring a route, `grep -rn "<old-path>" src/fuel_predictor/` before deleting it.
- [x] Model governance/comparison and historical-dataset-import pages migrated —
      `delivery/model_governance_pages.py` owns `GET /pengelolaan-model`, `GET
      /kandidat-model/{id}/perbandingan`, `POST /kandidat-model/{id}/promosikan`;
      `delivery/historical_dataset_pages.py` owns `GET /impor-data-historis`,
      `GET /contoh-data-riwayat.csv`, `POST /impor-data-historis`, and
      `POST /dataset-versions/{id}/latih-kandidat-baseline`. **This was the last of `delivery/form.py`
      — the file is now deleted entirely**, along with every `_render_*` function and `_page`/`_option`
      helper it held. New templates: `pengelolaan-model.html`, `kandidat-perbandingan.html`,
      `model-dipromosikan.html`, `impor-data-historis.html`, `impor-data-historis-selesai.html`,
      `kandidat-terlatih.html`; `pesan.html` gained an optional `detail` paragraph (guarded with
      `is defined` since the Jinja environment uses `StrictUndefined`) for the training-error page,
      which needs both an error message and a separate dataset-version-ID line.
      **Found while migrating, not by any test**: `POST /dataset-versions/{id}/latih-kandidat-baseline`
      had no entry in `ROUTE_CAPABILITIES` at all — pre-existing since the route was first added, not
      introduced by this migration — meaning any authenticated caller regardless of role could train a
      baseline candidate. Added `MANAGE_MODELS`, matching its JSON-API equivalent
      (`POST /api/v1/dataset-versions/*/baseline-candidates`). No regression test added for this specific
      gap yet — the existing role tests don't parametrize over every route, so a systematic
      "every ROUTE_CAPABILITIES entry has a role-appropriate test" check is still a real gap (see
      Known gaps).
      Verified end-to-end live: full demo flow (import → train → governance page shows candidate →
      comparison page → promote → "Model aktif diperbarui") plus the 404 error page for an unknown
      candidate, all through the real HTTP flow with cookies and CSRF tokens exactly as a browser
      would send them.
- [ ] Nav items the plan names but that don't exist yet, intentionally left out of
      `rendering.NAVIGATION` rather than linked to a placeholder: "Riwayat Prediksi", "Unggah
      Kandidat", "Riwayat dan Rollback", "Integrasi Agen". Add each back to `NAVIGATION` as its page
      ships.
- [ ] Accessibility/browser-level workflow tests — the design system follows the plan's checklist
      (focus visibility, semantic status, table equivalents for charts) but nothing automated
      verifies it yet (e.g. axe-core or Playwright a11y checks).
- [x] Systematic `ROUTE_CAPABILITIES` coverage test — `tests/test_route_capability_coverage.py`.
      Confirmed after the fact that the one gap found during migration
      (`POST /dataset-versions/{id}/latih-kandidat-baseline`) was the only one: every non-public route
      now has an entry, every entry matches a real route, and no entry is duplicated (a duplicate
      would silently hide the real capability, since the lookup returns the first match). Enumerates
      routes via `app.openapi()["paths"]` rather than walking `app.routes` — this FastAPI version
      wraps included routers in an internal `_IncludedRouter` object, so `app.routes` doesn't expose
      flat `APIRoute` instances the way older versions did; the OpenAPI schema is the stable,
      version-independent way to see what's actually registered. Extend this test, don't write a
      parallel one, if route enumeration ever needs to change again.

**Phase 1's UI redesign is complete**: every human-facing page renders through the Jinja design
system, `delivery/form.py` is deleted, and the three remaining unchecked items above are additive
(new nav items for pages that don't exist yet, a11y test automation, capability-table coverage
testing) rather than migration work. What's left in Phase 1 proper before it can be called fully
done per the plan's own Phase 1 bullet list: accessibility/browser-level workflow tests, and the
"redesign ... monitoring, and model pages" bullet is now satisfied. Phases 2-6 remain untouched.

## Phase 2 — External model ingestion (ADR 0009, ADR 0010)

Started. Landed the first slice: the manifest schema and its validation, which is plan validation
steps 4-5 ("validate the manifest and input schema" / "confirm feature-contract and runtime
compatibility"). Nothing in this slice touches an actual archive, ONNX/skops loading, activation, or
rollback yet — see "Not done" below for exactly where it stops.

- [x] Published JSON Schema for `manifest.json` — `schemas/model-package/manifest.schema.json`
      (draft 2020-12), with a `README.md` alongside it explaining the split between schema-shape
      validation (anyone, any language, can check this) and business-rule validation (only production
      knows which feature-contract/runtime versions it currently supports). Every manifest field ADR
      0009 lists is required; `model_format` is a two-value enum (`onnx`, `skops`) so Pickle/Joblib are
      rejected at the schema level, not by a runtime `if`, and `additionalProperties: false` throughout
      so an unrecognized field is a hard validation error rather than silently ignored. Watch the
      `allOf` + `$ref` + `additionalProperties: false` combination if you extend this schema — JSON
      Schema's `additionalProperties` only sees properties declared in the *same* schema object, not
      ones pulled in through `$ref`, so that combination silently rejects everything from the
      referenced schema. `category` metrics duplicate the `overall` metrics' properties directly for
      exactly this reason instead of composing them.
- [x] Domain shape — `domain/model_package.py` (`ModelPackageManifest`, `ModelFormat`,
      `FeatureSchemaEntry`, `ManifestMetrics`, `ManifestCategoryMetrics`,
      `ModelPackageValidationError` which collects every failure rather than raising on the first).
- [x] Validation use case — `application/model_package_ingestion.py`'s `ParseModelPackageManifest`:
      runs schema validation first (via the `ManifestSchemaValidator` port), then business rules
      (feature-contract version recognized, runtime-compatibility version recognized, no duplicate
      feature names, a checksum present for every required package member), then builds the typed
      manifest. Adapter: `infrastructure/jsonschema_manifest_validator.py`'s
      `JsonSchemaManifestValidator`, using the `jsonschema` library (new dependency, plus
      `types-jsonschema` for mypy).
      Tests: `tests/test_model_package_manifest.py`, 13 cases including "every simultaneous problem is
      reported together, not just the first one" and the forbidden-format parametrized case.
- [ ] **Not done** — everything after manifest validation: archive handling (size limits, path-traversal-safe
      extraction, per-member checksum verification against the manifest, optional signature check),
      `input-schema.json`/`reference-statistics.json`/`smoke-tests.json` schemas and validation, the
      production upload endpoint, isolated ONNX/skops loading (needs `onnxruntime`/`skops` as new
      dependencies — not added yet), deterministic smoke-test execution, metric-vs-policy comparison,
      persistence + audit record, the external packager tool itself, the in-process active-model
      holder with `expected_current_version` optimistic concurrency (ADR 0010), atomic activation,
      post-activation health check, and rollback. This is most of Phase 2's actual scope — the
      manifest-validation slice above is the foundation everything else builds on, not the bulk of the
      work.

## Phase 3 — Operational monitoring

Not started. Needs: scheduled `python -m fuel_predictor monitor` idempotent command, stored report
summaries (so the overview page's two `Belum tersedia` fields become real), service-health/backup
state, external alerting.

## Phase 4 — MCP read-only launch

Not started.

## Phase 5 — Privileged MCP operations

Not started. Depends on Phase 2 and Phase 4.

## Phase 6 — Deployment hardening and handoff

Not started. Depends on ADR 0012 (Caddy + `age`/`rclone` backup) being implemented, plus the
Indonesian operator guide, recovery runbook, and handoff drill.

## Notes for whoever picks this up next

- Full test suite (100 tests as of this writing) passes; `ruff check` and `mypy --strict` are clean.
  Keep it that way — run all three before committing.
- Manual browser smoke-testing caveat: in this sandboxed environment the Browser pane sometimes
  doesn't composite frames (`screenshot` fails with "pane is not displayed"), and coordinate/ref
  clicks on real `<button type="submit">` elements can silently no-op even though `read_page` shows
  them correctly. When that happens, `document.querySelector(...).requestSubmit()` via
  `javascript_tool` reliably drives the same form submission and is a fine substitute for verifying
  a page renders and behaves correctly end-to-end — it isn't a product bug, it's a tool/environment
  limitation. Don't burn time debugging the click itself; switch to `requestSubmit()` and move on.
- Smoke-testing tip for scripted (`httpx`) sign-in flows outside pytest: the CSRF token in the
  sign-in page's hidden field is a *pre-session* double-submit token, different from the session's
  real `csrf_token` that every page renders once you're signed in. Posting `/masuk` with the
  pre-session token works fine for signing in, but reusing that same value on later POSTs 403s.
  Fetch any authenticated page (e.g. `/`) after sign-in and read its `csrf_token` hidden field
  instead — that one value is stable for the whole session and works on every subsequent POST.
- `git` was not initialized in this repository before this work started; it now is, on branch
  `production-plan`, with a `Baseline: local MVP before production work` commit before any change
  in this effort. That commit is the rollback point if something here needs to be reverted wholesale.
- The Windows dev environment's Docker Desktop was unstable during this session (unrelated to this
  codebase) — if `docker compose` hangs, that's an environment issue, not a regression here.

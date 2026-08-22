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
- `delivery/dashboard.py` holds the first three pages built on the new template system: `/`
  (overview), `/pengguna` (users), `/audit`. Everything else still renders through the original
  f-string builders in `delivery/form.py` — see "Known gaps" below.
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
- [ ] **Not done**: redesigning model governance/comparison and historical-dataset-import pages onto
      the Jinja design system. They still render through the f-string functions remaining in
      `delivery/form.py` (`_render_model_governance`, `_render_candidate_comparison`,
      `_render_promotion_success`, `_render_training_success`, `_render_training_error`,
      `_render_import_form`, `_render_import_success`), which live behind auth + capability checks and
      correctly carry CSRF tokens, but are visually and structurally unchanged from the MVP. After
      these, `form.py` should be near-empty and worth deleting outright rather than migrating
      piecemeal — check what's left before starting the next one. Follow the pattern in
      `prediction_pages.py` / `bulk_prediction_pages.py` / `actual_fuel_pages.py` /
      `monitoring_pages.py` / `dashboard.py`: a new `delivery/<name>.py` module, matching templates,
      then delete the old render functions from `form.py` (don't leave both versions in place), remove
      now-unused params from `build_form_router` and its `main.py` call site, update
      `rendering.NAVIGATION` and `security.ROUTE_CAPABILITIES` for any path change, and
      `grep -rn "<old-path>"` across `src/fuel_predictor/` for stale links before deleting a route.
- [ ] Nav items the plan names but that don't exist yet, intentionally left out of
      `rendering.NAVIGATION` rather than linked to a placeholder: "Riwayat Prediksi", "Unggah
      Kandidat", "Riwayat dan Rollback", "Integrasi Agen". Add each back to `NAVIGATION` as its page
      ships.
- [ ] Accessibility/browser-level workflow tests — the design system follows the plan's checklist
      (focus visibility, semantic status, table equivalents for charts) but nothing automated
      verifies it yet (e.g. axe-core or Playwright a11y checks).

## Phase 2 — External model ingestion (ADR 0009, ADR 0010)

Not started. This is the next major phase: JSON Schemas for the package manifest, the external
packager, staged validation, atomic activation with `expected_current_version`, rollback, and the
in-process model holder described in ADR 0010.

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

- Full test suite (43 tests as of this writing) passes; `ruff check` and `mypy --strict` are clean.
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

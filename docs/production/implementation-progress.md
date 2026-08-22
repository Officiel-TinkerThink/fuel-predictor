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
- [ ] **Not done**: redesigning prediction, bulk import, actual-fuel, and model pages onto the new
      Jinja/design-system templates. They still render through the original f-string functions in
      `delivery/form.py`, which now live behind auth + capability checks (via `ROUTE_CAPABILITIES`)
      and now correctly carry CSRF tokens, but are visually and structurally unchanged from the MVP.
      This is the largest remaining Phase 1 item. Suggested order: prediction form → bulk prediction
      → actual fuel (single + bulk) → monitoring (needs the 3-way Kesehatan/Pergeseran/Kinerja split
      from the plan, currently one page) → model governance/comparison.
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

- Full test suite (41 tests as of this writing) passes; `ruff check` and `mypy --strict` are clean.
  Keep it that way — run all three before committing.
- `git` was not initialized in this repository before this work started; it now is, on branch
  `production-plan`, with a `Baseline: local MVP before production work` commit before any change
  in this effort. That commit is the rollback point if something here needs to be reverted wholesale.
- The Windows dev environment's Docker Desktop was unstable during this session (unrelated to this
  codebase) — if `docker compose` hangs, that's an environment issue, not a regression here.

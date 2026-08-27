# Production Plan Implementation Progress

Tracks work against [self-service-production-plan.md](self-service-production-plan.md) across
sessions. Update this file whenever a phase item lands or a design decision is made, so a fresh
session (or a different model) can resume without re-deriving context.

## Status at a glance

All six phases are implemented. 274 tests pass; `ruff` and `mypy --strict` are clean.

| Phase | State |
|---|---|
| 1 — UI redesign and identity | Done |
| 2 — External model pipeline | Done. Package signature verification remains, and is optional |
| 3 — Operational monitoring | Done, including alert delivery with remediation |
| 4 — MCP read-only launch | Done |
| 5 — Privileged MCP operations | Implemented, **shipped disabled** behind an explicit config gate |
| 6 — Deployment hardening and handoff | Code and docs done; two people-based exercises open |

**Known issue, found 2026-08-27 and not yet fixed:** SQLite does not enforce foreign keys unless
each connection opts in; PostgreSQL always does. Turning enforcement on locally
(`PRAGMA foreign_keys=ON` in `build_engine`) makes six tests fail on dangling references the suite
had been silently accepting — and two of those were real production 500s:
model-package upload, and `data_quality_issues` rows written for a dataset whose import was
rejected. The upload one is fixed (Alembic `20260827_13`); the rest need individual fixes, so
enforcement is recorded here rather than shipped red. It belongs at the top of the next batch:
every one of these is a request that works on SQLite and fails in production.

**Four things remain, and three of them cannot be done by writing code:**

1. **Usability test** with a non-technical participant ([protocol](handoff-drill.md)).
2. **Handoff drill** with an incoming technical owner ([protocol](handoff-drill.md)).
3. **Security review** before enabling the Phase 5 privileged MCP tools.
4. Package signature verification — optional; adds provenance, not integrity.

These are recorded as open rather than marked done. Every one of them is a check on work performed
by the person who built it, which is exactly the kind of check that cannot be self-administered.

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
      status, backup status) were honestly `Belum tersedia` until Phase 3 filled them in; they now
      show real state.
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
- [x] Accessibility tests — `tests/test_accessibility.py` checks the design system's checklist
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
- [x] Archive handling — plan validation steps 1-3. `infrastructure/zip_model_package_archive.py`'s
      `ZipModelPackageArchiveReader` reads an uploaded ZIP into memory under
      `ModelPackageArchiveLimits` (archive bytes, total extracted bytes, member count, per-member
      compression ratio — all configurable via `FUEL_PREDICTOR_MODEL_PACKAGE_MAX_*`), rejecting
      absolute paths, drive letters, and `..` traversal in member names under *both* POSIX and Windows
      separator conventions (a ZIP built on either platform can be uploaded to a server running the
      other). `verify_member_checksums` in the application layer then confirms archive contents match
      the manifest exactly — no unexplained extras in either direction — excluding `manifest.json`
      itself, which cannot carry a checksum of the bytes containing that checksum.
      Tests: `tests/test_model_package_archive.py`, 21 adversarial cases.
      **Two testing notes worth keeping.** First, the original "tampered declared size" test passed for
      the wrong reason — `zipfile`'s own CRC/size consistency check rejects such an archive as
      malformed, so the bounded-read path was never exercised. It's now split into two honest tests,
      one pinning `zipfile`'s behaviour and one asserting our *specific* size-limit message. Second,
      that size-limit test deliberately does **not** claim to prove reading is bounded: a
      read-in-full-then-reject implementation passes it identically. The bounded read in `_read_one`
      is a memory-exhaustion defence a unit test can't practically detect, so its rationale lives in a
      code comment rather than a test name that would overstate what's verified.
- [x] In-process active-model holder and the activation sequence (ADR 0010) —
      `application/model_activation.py` and `domain/model_activation.py`. `ActiveModelHolder` keeps one
      `LoadedModel` (model + the version it came from, as one immutable pair so a reader can never see
      a model from one version beside metadata from another). Reads are lock-free; writes are
      serialised by a separate lock so only one candidate is loaded and warmed at a time.
      `ActivateModelVersion` runs ADR 0010's ordered sequence: capacity check → load and warm →
      smoke tests → conditional persist → swap → post-activation health check. Every failure before
      the swap leaves the previous model both active and loaded; the post-swap health-check failure is
      surfaced and deliberately **not** auto-reverted, per the ADR's reasoning that a silent revert
      hides a real problem.
      Ports defined but not yet implemented: `ModelArtifactLoader`, `SmokeTestRunner`, `MemoryProbe`,
      `ActivationRepository` — this slice is the orchestration and its concurrency semantics, tested
      against fakes. The SQLAlchemy `ActivationRepository` (a conditional `UPDATE ... WHERE` whose
      zero-row result is the conflict) and the real loader/probe are still to come.
      Tests: `tests/test_model_activation.py`, 9 cases including a genuine two-thread race asserting
      exactly one activation wins and the loser neither persists nor swaps.
      **Fixed while writing this**: the health check originally re-read `holder.current()` after
      releasing the lock, so a later activation could swap in between and this call would report on —
      and blame — the wrong model. It now health-checks the specific `LoadedModel` this activation
      swapped in.
- [x] SQLAlchemy `ActivationRepository` — `SqlAlchemyPredictionRepository.activate`. The conditional
      `UPDATE ... WHERE model_version_id = :expected AND status = 'active'` is the arbiter: a zero row
      count means someone else already changed the active model. When the caller expects *no* active
      model, the existing partial unique index on `lifecycle_status = 'active'` plays that role
      instead, and a losing racer's `IntegrityError` is translated into the same conflict result
      rather than surfacing as a crash. Re-activating the already-active version is treated as an
      idempotent success so a retried request isn't reported as a conflict with itself. Needed no
      Alembic revision — the existing `model_versions` schema and its partial unique index already
      carry everything the contract requires.
      Both a candidate and a previously-retired version may be activated: the first is a promotion,
      the second a rollback. The extra authority rollback needs (administrator, recorded reason) is
      the use case's job, not the repository's — this method owns the concurrency contract, not the
      approval policy. Re-activating a retired version clears `retired_at`, so a restored model does
      not still look retired.
      Tests: `tests/test_activation_repository.py`, 10 cases against a real SQLite database rather
      than a fake, since the partial unique index and the zero-row UPDATE are precisely what a fake
      cannot demonstrate. Includes a two-thread race.
      **On `ModelNotActivatableError`**: currently unreachable through `ModelLifecycleStatus`, whose
      three values are all handled. It exists because the plan's state diagram adds `rejected`, and a
      rejected package must never become active by accident. Rather than leave untested defensive
      code, the test drives it by writing the status directly, so the guard is genuinely exercised.
- [x] Smoke-test contract and runner — `schemas/model-package/smoke-tests.schema.json` plus
      `ParseSmokeTests` and `DeterministicSmokeTestRunner` in `application/model_package_ingestion.py`.
      A package must declare at least one case: one that asserts nothing about its own behaviour
      cannot be smoke-tested, so silently activating it would defeat the step. `tolerance` is
      absolute and defaults to a small non-zero value, because floating-point results differ across
      platforms and runtime versions and exact equality would fail packages for reasons unrelated to
      model correctness; the boundary is inclusive. The runner executes every case even after one
      fails, so an operator sees the whole picture in one pass, and treats a case that *raises* as a
      failure rather than a crash — a model erroring on a case it declared it could answer is exactly
      what this step exists to catch. `JsonSchemaValidator` is now generic over schema files, with
      `JsonSchemaManifestValidator` kept as a convenience binding.
      Tests: `tests/test_model_package_smoke_tests.py`, 9 cases.
- [x] `RollbackModelVersion` (ADR 0010) — a separate use case from `ActivateModelVersion` rather than
      a flag on it, because the two differ in meaning and in what they require: rollback names an
      administrator and a reason. The mechanics are identical, so the activation sequence is reused
      rather than duplicated. The rollback intent is recorded **before** the attempt, so an operator's
      decision survives even when the activation then loses a concurrency race or fails smoke tests —
      that is precisely the situation someone reconstructs later. An empty reason and an unknown
      target are both refused before anything is recorded.
      Tests: 4 cases in `tests/test_model_activation.py`.
- [x] Reference statistics — `schemas/model-package/reference-statistics.schema.json` and
      `ParseReferenceStatistics`. This is the drift baseline: a model trained outside production has
      no in-database dataset to compare against, so without it drift for an externally-trained model
      could not be computed at all. `row_count` travels with the summary so a verdict from a small
      baseline is never presented as confidently as one from a large baseline. Validation also checks
      the summary against the manifest's feature schema in both directions — a baseline describing
      different features than the model consumes cannot produce a meaningful verdict, and silently
      computing one anyway would be worse than refusing.
      Tests: `tests/test_model_package_reference_statistics.py`, 8 cases.
- [x] **Plan amended**: `input-schema.json` and `checksum.sha256` dropped from the package format.
      The plan's file list was explicitly illustrative ("for example"), and each of those two
      duplicated a field the manifest is *required* to carry — the ordered feature schema, and every
      member's checksum. Two sources for one fact can disagree, and a package whose
      `input-schema.json` contradicted its own manifest would have no correct interpretation. The
      amendment and its reasoning are recorded in the plan itself, next to the archive listing.
- [x] Test fixtures extracted to `tests/model_package_fixtures.py` rather than imported across test
      modules, so editing one test's fixture to suit itself cannot silently change another's meaning.
- [x] Promotion eligibility (plan validation step 8) — `application/model_promotion_policy.py`.
      **Eligibility is not promotion**: ADR 0004 keeps promotion a manual act, so this decides only
      whether an administrator *may* promote and gives them the comparison to decide whether they
      *should*. A candidate clearing every threshold still waits for a human, and a test asserts the
      summary text never implies otherwise.
      Uses both an absolute MAE ceiling and a relative regression ratio, because either alone is
      gameable: a ceiling alone accepts a clear regression that still sits under it (4.9 L passing a
      5 L ceiling while the active model is at 2.0 L), and a ratio alone accepts unbounded drift
      downward as long as each individual step is small. Small test sets block promotion, since
      metrics from them are not trustworthy enough to act on. A zero-MAE active model is compared
      absolutely rather than by ratio, which would divide by zero. Falling interval coverage warns
      but does not block — a better point estimate with slightly worse calibration can still be the
      right model, and that trade-off is the operator's judgement, not the policy's.
      Thresholds are configurable (`FUEL_PREDICTOR_PROMOTION_*`).
      Tests: `tests/test_model_promotion_policy.py`, 12 cases.
- [x] `MemoryProbe` — `infrastructure/system_memory_probe.py`. Reports *available* rather than
      *free* memory: free excludes reclaimable page cache, so on a healthy server it reads far lower
      than what an allocation could actually obtain and would reject activations that were perfectly
      safe. Holds back a configurable safety margin so an activation cannot consume the last of the
      machine's memory and starve the request currently being served — protecting the model already
      running is the entire point of the capacity check. Clamps at zero, because a negative value
      would compare as less than any requirement and silently invert the check into always-allow.
      Tests: `tests/test_system_memory_probe.py`, 3 cases.
- [x] Real `ModelArtifactLoader` — `infrastructure/model_artifact_loader.py`. **The dependency
      blocker is resolved**: `onnxruntime` and `skops` are installed (pip cache pointed at D: to
      avoid filling C:, which is still tight at ~3.7 GB). Loads either trusted format, feeds features
      in the manifest's declared order, and warms the model with one throwaway inference so the first
      real request isn't the slow one — a warm-up failure is a load failure, which keeps the
      currently-active model serving rather than swapping in something that cannot answer.
      `trusted_skops_types` is an explicit allow-list rather than something inferred from the file:
      `skops` refuses unknown types by default precisely so an untrusted package cannot make
      production reconstruct arbitrary objects, and widening that is a security decision.
      Tests: `tests/test_model_artifact_loader.py`, 9 cases using genuinely trained scikit-learn
      models rather than stubs — a fake predictor cannot show that a real artefact round-trips and
      answers correctly.
      **A test initially passed for the wrong reason here too**: the untrusted-type test used a plain
      `LinearRegression`, but every plain scikit-learn estimator is on skops' own trusted list, so
      there was nothing to refuse and the assertion never exercised the guard. The fixture now builds
      a pipeline carrying a user-defined callable — code the package brought with it, which is the
      case that actually matters — and asserts the fixture really is untrusted before testing that it
      is refused.
- [x] End-to-end validation flow — `application/model_package_validation.py`'s
      `ValidateModelPackage` runs plan steps 1-9 in order. **The order is itself a safety property**:
      cheap structural checks before parsing, parsing before loading, and the artefact loaded only
      after its bytes are checksum-verified against an already-validated manifest. A flow that loaded
      first would execute unverified bytes, which is the exact risk ADR 0009 restricts formats to
      avoid — asserted directly by a test that corrupts a checksum and expects rejection *before* any
      load happens. Failing the promotion policy is a verdict, not a validation error: a merely-worse
      candidate still validates so the operator can see the comparison; only malformed or dishonest
      packages are refused.
      Tests: `tests/test_model_package_validation_flow.py`, 6 cases building a real ZIP around a
      genuinely trained model.
      **This integration test caught a real contradiction the unit tests could not**:
      `_REQUIRED_PACKAGE_MEMBERS` demanded a checksum for `manifest.json` while
      `verify_member_checksums` deliberately excluded it (it cannot checksum itself), making a
      well-formed package impossible to construct. Each unit test passed in isolation because each
      only ever saw one side of the contradiction.
- [x] Persisted validation verdicts (plan step 9) — `model_package_validations` table with Alembic
      revision `20260822_09`, `application/model_package_records.py`, and its SQLAlchemy repository.
      **Rejections are recorded too, and that is the point**: "why was this package refused?" is a
      question asked days later, and it can only be answered if the refusal was written down at the
      time. `manifest` and `artifact_path` are nullable precisely so a package rejected *before* its
      manifest could be parsed still leaves a record instead of vanishing.
      Tests: `tests/test_model_package_records.py`, 7 cases including one that runs the real Alembic
      migration and then exercises the ORM against it — the two are hand-written in separate places,
      so nothing else would catch a column added to one and missed in the other. That test sets the
      database URL through the environment rather than Alembic's config, because `alembic/env.py`
      deliberately reads it from `ApplicationSettings` and would otherwise override the config and
      try to reach the real PostgreSQL (this is the existing convention in `tests/test_migrations.py`).
- [x] External packager — `src/fuel_predictor/packaging/model_packager.py`. Lives in this
      repository, not the training environment, so the package contract has exactly one
      implementation (ADR 0009); a separately-maintained packager would drift from the validator and
      produce packages rejected for reasons the trainer cannot reproduce locally.
      Checksums, `model_size_bytes`, and the member list are **computed from the bytes being
      written** rather than accepted from the caller — they are facts about those bytes, and a caller
      able to state them separately could state them wrongly. JSON is serialised canonically
      (sorted keys, fixed separators) so a rebuild is byte-identical and checksums are stable.
      Rejects a forbidden format, an empty artefact, duplicate feature names, a missing smoke case,
      and a smoke case that omits a declared feature — all caught at packaging time so the trainer
      sees them immediately instead of diagnosing a remote production rejection.
      Tests: `tests/test_model_packager_roundtrip.py`, 8 cases. **The central one feeds the
      packager's output straight into the validator**: packager and validator are separate code with
      schemas between them, and only a round-trip proves they agree. Testing either side alone would
      not.
- [x] Upload endpoint and UI — `delivery/model_upload_pages.py` with `GET`/`POST /model/unggah` and
      `GET /model/riwayat`, plus `infrastructure/model_artifact_store.py` for retention. **Uploading
      never activates** (ADR 0004): a package that validates and clears policy becomes an eligible
      candidate, and the page says so explicitly. Rejections are recorded before the error page
      renders, so the reason survives even though nothing was accepted. The artifact store re-checks
      the version against a safe-name pattern even though the manifest schema already constrained it,
      because this function is what turns a string into a filesystem path and therefore owns that
      decision. "Unggah Kandidat" and "Riwayat Paket" are now real entries in `NAVIGATION`.
- [x] **Fixed a startup regression this introduced**: importing `skops.io` at module scope pulls in
      scikit-learn's estimator discovery, which walks loaded shared libraries and fails outright on
      some Windows hosts (`GetModuleFileNameEx failed`) — and once `main.py` imported the loader, that
      made the *whole application* fail to start. Caught because the navigation test could no longer
      even import the app. `onnxruntime` and `skops` are now imported lazily inside the functions that
      use them: serving a prediction page should not pay that cost, and a machine that never uploads a
      package should never load those libraries at all.
- [x] `ActiveModelHolder` is on the serving path — `GenerateFuelPrediction` now takes an optional
      holder and reads it **exactly once per request**, keeping that reference for the whole request
      so an activation swapping mid-request cannot make a prediction attribute one model's numbers to
      another model's version (ADR 0010). While the holder is empty, prediction falls back to the
      MLflow-backed store unchanged, which is what ADR 0011 requires until package ingestion reaches
      parity — so this is additive, not a cutover, and every pre-existing test still passes untouched.
      `ensure_model_available` accepts a holder-only deployment, since a package-only install has no
      MLflow active row and that is legitimate rather than an error.
      Tests: `tests/test_prediction_uses_active_holder.py`, 7 cases including one asserting the
      reported version matches the model that actually produced the number.
- [x] **Ingested packages are now activatable end to end.** This was recorded here as "UI wiring",
      which understated it. The real gap was that a validated, retained package was never registered
      as a model version at all: `ActivateModelVersion` was not constructed anywhere in `main.py`,
      the active-model holder was never handed to the prediction path, and the artefact store had no
      way to read bytes back. Retained bytes with no model version row are unreachable — nothing
      could activate them and nothing could roll back to them. Now:
      - `RegisterIngestedPackage` records each accepted package as a candidate at upload time, keyed
        by the manifest's own `model_version`, which is also the directory the store retains it
        under, so "the row exists" and "the bytes exist" cannot drift apart.
      - `FilesystemModelArtifactStore.read_members` reads a retained package back, re-checking the
        version against the same pattern `store` uses — this is the second place a string becomes a
        filesystem path, so it owns that decision too.
      - `ActivateRetainedModelPackage` rebuilds the loader and smoke-test runner from the retained
        bytes and **re-verifies their checksums against the manifest** before loading. That is the
        difference between "these bytes were trustworthy once" and "these bytes are what we are
        about to load".
      - The governance promote button dispatches: a candidate with retained bytes runs the full
        ADR 0010 sequence; a model trained in this process keeps the simpler path, because it has no
        package to load.
      - `answers_a_representative_case` is the post-activation health check. The package's own smoke
        tests already ran pre-swap against the isolated model; this asks the model that is *now
        serving*, and treats a non-finite or negative litre figure as a failure — a model returning
        NaN would otherwise poison every prediction silently.
      - The holder is now on the serving path, so predictions come from the activated package.
      Proven by `tests/test_retained_package_activation.py`: a model packaged by this repo's own
      packager, uploaded through the UI, activated through the governance page, then predicting
      `17.0 L` — the packaged model's own arithmetic — under the package's own version id.
- [x] **Artefact retention** — `PruneRetainedPackages` and `python -m fuel_predictor
      prune-packages`. Correctness, not disk hygiene (ADR 0010): the rule is stated as what is
      *kept*, never as what is deleted, so anything not positively identified as keepable is left
      alone. Kept: the active model, every candidate awaiting review, and the most recent retired
      versions (default 3) as rollback targets. **Dry-run by default** — the failure mode is
      asymmetric, since keeping too much wastes disk while deleting a rollback target removes the
      recovery path and nobody finds out until the day they need it. Each kept version reports the
      reason it was kept, so an operator reading the plan sees why and not just what.
      `FilesystemModelArtifactStore.delete` re-checks the version against the same pattern `store`
      and `read_members` use: it is the third place a string becomes a filesystem path, and a
      recursive delete is the one where getting it wrong costs the most.
- [ ] **Still not done, and genuinely optional:** package signature verification. ADR 0009 lists it
      as optional and checksums already cover integrity end to end — including re-verification of
      retained bytes at activation time. Signing would add *provenance* (who built this package),
      not integrity. Worth doing if packages ever arrive from more than one trusted builder.

**Phase 2 is functionally complete.** The external model pipeline runs end to end and has been
verified live against a running server: a model trained with scikit-learn is packaged by this repo's
own packager, uploaded through the web UI, validated through all nine plan steps (bounded extraction,
checksum verification, manifest/statistics/smoke-test schema validation, isolated load, smoke tests
replayed against the real model, policy evaluation), retained on disk, and recorded in history — with
a rejected upload likewise recorded, reason intact. Prediction serves from the in-process holder once
a package is activated, falling back to the MLflow path until then per ADR 0011.

The three remaining items above are genuinely optional or small UI wiring, not missing capability.

## Phase 3 — Operational monitoring

- [x] Scheduled, idempotent monitoring execution — `python -m fuel_predictor monitor` (`__main__.py`)
      and `RunScheduledMonitoring`. Idempotent because the dashboard is a pure read over current
      state, so a scheduler retrying after a timeout records a second observation rather than
      double-counting. Exits **non-zero on failure**, which is the signal the plan's failed-run
      alerting depends on — a job that always exits zero cannot be monitored.
- [x] Stored report summaries — `monitoring_runs` table (Alembic `20260822_10`). The UI reads a
      precomputed summary instead of recomputing drift and reconciliation inside a page request,
      which is what made the dashboard slow exactly when someone was watching it. Summaries hold
      counts and verdicts, not whole row sets: the source tables already have the detail, and copying
      it here would grow without bound.
- [x] Service-health and backup state — `backup_runs` table plus `MonitoringFreshness`. Both the
      overview and Kesehatan Sistem pages now show real monitoring freshness and last-backup outcome
      in place of the `Belum tersedia` placeholders. A *failed* attempt does not by itself mark the
      picture stale — the last good summary is still the best information available — but it is
      surfaced separately so an operator sees monitoring is unhealthy even while the numbers look
      fine. When the picture *is* stale, the page says so and names the command to run.
      Backup outcomes are recorded by the backup job rather than inferred: the application cannot see
      whether an off-VM upload succeeded, and guessing would produce a reassuring dashboard with no
      basis. Writing those records is Phase 6 work (ADR 0012); the read side is ready for it.
- [x] **Two real bugs found by exercising the CLI against a broken database**, both now covered by
      regression tests:
      1. When the database was unreachable, `RunScheduledMonitoring` caught the dashboard failure and
         then *the write recording that failure also failed* — and that second exception escaped
         uncaught, turning a handled failure into a crash. `_record` now tolerates a storage failure.
      2. A run that completed but could not be persisted was reported as a success. That would leave
         the dashboard showing a stale picture while the scheduler saw green and raised no alarm; it
         is now reported as a failure.
- [x] **External alerting with plain-language remediation.** Recording an alert in the database is
      not delivery: nobody watches a dashboard they have no reason to open.
      - Two channels, on dependencies the project already has: a webhook (`httpx`) and SMTP email
        (`smtplib`, stdlib). A self-hosted single-VM deployment should not need a paid notification
        service to learn that its predictions have started drifting. The webhook wins when both are
        configured — it is the one that can point at a chat group someone already watches.
      - `domain/alert_remediation.py` holds the plain-Indonesian next action for every alert kind,
        in the order a non-specialist would take them, plus an urgency line per severity. It lives
        in the domain because the wording is part of what the system promises an operator, not a
        detail of how a message is delivered. A test asserts every kind has text, so a new alert
        kind cannot ship without guidance.
      - Delivery fires only when the picture *changes*: a new alert, a severity change, or one that
        cleared. A job that mails the same warning every hour trains its reader to ignore it.
        Resolution is reported too — without it an operator never learns the problem ended.
      - Delivery state is persisted (`alert_notifications`, Alembic `20260825_12`) because the
        monitoring job is a separate short-lived process; an in-memory record of "already told them"
        would be empty on every run.
      - A failed send records nothing, so the next run retries. Recording on failure would mark an
        alert handled that nobody received.
      - An unconfigured channel is stated plainly rather than passing silently. "No alerts were
        sent" and "nobody is listening" must never look the same in a log. Nothing is recorded as
        sent either, so configuring a channel later delivers the existing backlog instead of
        starting from a clean slate that hides current problems.
      - Delivery never changes the monitoring exit code. Monitoring itself succeeded; turning a
        notification problem into a failed run would make the scheduler report the wrong thing.
      Verified live: a real webhook receiver got the alert with its remediation, got nothing on the
      repeat run, and got the resolution notice when the alert cleared.
- [ ] **Known limitation, needs an external watchdog**: nothing in this process can detect that the
      monitoring job *stopped running altogether*. A dead-man's-switch has to live outside the thing
      it watches. The non-zero exit code is the hook for that (ADR 0012, Phase 6).

## Phase 4 — MCP read-only launch

Done, and verified against a live server (issue a credential in the browser, use it as a bearer
token against `/mcp`, revoke it, watch the next call 401).

- [x] Agent clients are a first-class identity: `AgentClient` with its own scopes
      (`fuel:predict`, `fuel:monitor`, `models:read`), its own revocable credential, and its own
      audit actor. Each client is separate so a misbehaving agent can be revoked without
      disturbing the others.
- [x] Credentials are `fpa_`-prefixed random tokens. Only the sha256 hash is stored, so the raw
      value is shown exactly once at issue time — a lost credential is reissued, not looked up.
      The prefix makes a leaked token recognisable to secret scanners.
- [x] `/integrasi-agen` (admin-only, `MANAGE_USERS`) issues, lists, and revokes credentials.
- [x] `/mcp` speaks JSON-RPC 2.0: `initialize`, `notifications/initialized`, `tools/list`,
      `tools/call`. It is public to the *session* middleware only because it does its own bearer
      authentication; it is not unauthenticated.
- [x] Seven read/compute tools, each declaring the one scope it needs: `predict_fuel`,
      `get_service_health`, `get_drift_summary`, `get_performance_summary`, `get_current_model`,
      `list_model_versions`, `get_prediction_input_schema`. Every one calls the same application
      use case the web pages call, so a rule cannot drift between the human and agent surfaces.
- [x] `tools/list` is filtered by the caller's scopes. Advertising a tool the credential cannot
      call invites an agent to plan around a capability it does not have, then fail partway.
- [x] Every call is audited — caller, tool, outcome, short note. Arguments are summarised rather
      than stored verbatim, so the audit trail does not become its own retention problem.
- [x] An invalid token and a revoked one are refused identically, so probing cannot tell them apart.
- [x] `predict_fuel` carries `safety_policy` in its result: an agent must be able to tell an
      estimate of *prepared* fuel from verified consumption.

Bug found and fixed while testing this phase: the transport caught `LookupError` to mean "unknown
tool", but `KeyError` is a `LookupError`. A prediction attempted with no trained model therefore
came back as JSON-RPC `-32601 Method not found` with an empty message — telling the agent the tool
did not exist rather than why the call failed. Replaced with an explicit `McpUnknownToolError`, and
`BaselineModelNotFoundError` now carries a plain-language default message so generic
stringification still says something an operator can act on. Both are covered by regression tests.

- [x] **Concurrency verified through the MCP surface itself.** Two agents racing a privileged
      activation against PostgreSQL: exactly one wins, neither crashes, and the loser is not given
      an error but a fresh `confirmation_required` naming the version that actually won — its
      confirm token is an HMAC over the expected-active version, so a state change underneath makes
      the token stop verifying. The token binding *is* the concurrency guard at this layer.
- [x] **Verified against the official MCP SDK client**, not just hand-rolled JSON-RPC — the
      acceptance criterion asks for a *standards-compliant remote client*, and our own client
      agreeing with our own server proves nothing. `scripts/verify-mcp-client.py` drives the real
      `mcp` package: initialize, tools/list, every read tool, a privileged preview that must change
      nothing, and an unknown tool that must raise. Run it against a deployment after any change to
      the MCP surface, and during the handoff drill.

Deliberately **not** in this phase: anything that writes. No upload, activation, or rollback tool
exists. Those are Phase 5 and stay unavailable until read-only operation has proven itself.

## Phase 5 — Privileged MCP operations

Implemented and **shipped disabled**. The plan says "expose validate/activate/rollback by artifact
ID *only if required*" and "perform a security review before enabling these tools", so the gate is
enforced by configuration rather than by the absence of code — an operator turns them on
deliberately, after the read-only surface has proven itself.

- [x] Three tools: `validate_model_package`, `activate_model_version`, `rollback_model_version`.
      Off unless `FUEL_PREDICTOR_MCP_PRIVILEGED_TOOLS_ENABLED` is set, **and** only visible to
      credentials holding the new `models:admin` scope.
- [x] `models:admin` is never in `DEFAULT_AGENT_SCOPES`, and the issue form does not pre-tick it.
      A regression test holds both: the form pre-checked every scope at one point, which would
      have handed the privileged scope to every credential issued by an administrator accepting
      the page as presented. That was found by driving the live page, not by the unit tests.
- [x] **Identifiers, never bytes.** No tool accepts an artefact. A model reaches the system only by
      a human uploading a package through the web UI, so a compromised agent can choose among
      models a person already vetted but cannot introduce one. A test asserts every privileged
      schema is `additionalProperties: false` and mentions no byte-carrying field — this is a
      stated acceptance criterion, so it is checked rather than assumed.
- [x] **Two-call confirmation.** The first call reports what *would* happen and returns a token;
      nothing changes. The token is an HMAC over the operation, the target version, and the
      currently-active version, so it cannot be replayed against a different version or reused to
      authorise a different operation. It is derived, not stored: a restart invalidates outstanding
      confirmations, which is the safe direction to fail.
- [x] **Optimistic concurrency.** Activation and rollback pass the caller's view of the active
      version into the same conditional UPDATE the web UI uses, so an agent acting on a stale
      reading loses the race rather than overwriting a change it never saw.
- [x] **Rollback requires a reason**, recorded before the attempt, so the decision survives an
      attempt that then fails.
- [x] Every call is audited through the same path as the read-only tools.
- [ ] **Security review before enabling in production.** Like the usability test and handoff drill,
      this is a human activity and is not marked done. The properties above are what the review
      should check, not a substitute for it.

Verified live with the flag enabled: a `models:read` credential is refused with
`Cakupan models:admin diperlukan untuk alat ini`, an admin credential sees all three tools, an
unconfirmed activation changes nothing, a token issued for one version is refused for another, and
rollback without a reason is rejected.

## Phase 6 — Deployment hardening and handoff

Code and documentation complete. The two people-based exercises are deliberately left open — see
the bottom of this section.

- [x] **HTTPS gateway** — `compose.prod.yaml` plus [`deploy/Caddyfile`](../../deploy/Caddyfile).
      Caddy terminates TLS and renews Let's Encrypt certificates with no cron job and no operator
      action. Security headers are set at the gateway so they cover responses rendered before any
      application middleware runs.
- [x] **Nothing but the gateway is published.** `compose.prod.yaml` is a *standalone* file rather
      than an overlay on `compose.yaml`, and that is the whole point: Compose **merges** `ports`
      across `-f` files and cannot unpublish a port an earlier file published. An overlay would
      have left the application and MLflow reachable on the host, bypassing TLS entirely.
      Duplicating a little configuration is the cheaper mistake. Verified:
      `docker compose -f compose.prod.yaml config | grep -c published` returns 3 (80, 443/tcp,
      443/udp) and nothing else.
- [x] **Proxy header trust is bounded.** uvicorn runs with `--proxy-headers` *and*
      `--forwarded-allow-ips`. Without the second flag any client could forge its own source
      address by setting a header, which would poison the audit trail.
- [x] **Encrypted off-VM backup** — [`deploy/backup.sh`](../../deploy/backup.sh): `pg_dump`
      custom-format plus an archive of the retained model packages, both encrypted with `age` to a
      recipient **public** key and uploaded with `rclone`. The job holds no secret capable of
      decryption, so a compromised VM cannot read its own backup history. Retention is 7 daily,
      4 weekly, 3 monthly. Pruning never fails a backup: a copy that uploaded fine must not be
      reported failed because an old one could not be deleted.
      The model packages travel with the dump deliberately — a database backup without them would
      restore to a state that cannot roll back, since rollback needs the target's bytes.
- [x] **Backup outcomes are recorded, not inferred** — `python -m fuel_predictor record-backup`,
      called by the script. The application cannot see whether an off-VM upload succeeded, and
      guessing would produce a reassuring dashboard with no basis. This closes the Phase 3 read
      side that was already waiting for it. A *recorded failure* still exits 0: the backup script's
      own exit code is what tells the scheduler the backup failed, and failing here too would
      report the same problem twice while hiding whether recording itself worked.
- [x] **Rehearsable restore** — [`deploy/restore.sh`](../../deploy/restore.sh). Fetches, decrypts,
      `pg_restore`s with `--clean --if-exists`, unpacks the model packages, then prints the four
      checks that decide whether the restore actually worked. A restore that loads rows but leaves
      the active model unloadable is not a successful restore, and the script says so.
- [x] **Scheduled monitoring ships with the deployment** — a `monitor` service rather than host
      cron, so an operator cannot forget to install it.
- [x] **Indonesian operator guide** — [`panduan-operator.md`](panduan-operator.md). No technical
      commands. Leads with the distinction that matters most: the number is fuel *to prepare*, not
      fuel *consumed*. Screenshot placeholders are marked; they need capturing against a real
      deployment.
- [x] **Technical recovery runbook** — [`recovery-runbook.md`](recovery-runbook.md). Written to be
      usable at 2am by someone who did not build this: symptom-first triage table, then what you
      will see / what it means / what to do.
- [x] **Drill and usability protocols written** — [`handoff-drill.md`](handoff-drill.md), including
      the two exercises people skip: forcing an activation failure by corrupting a retained
      artefact, and restoring on a genuinely clean machine.
- [ ] **Not done, and cannot be done by writing code:**
      1. The **usability test** with a non-technical participant.
      2. The **handoff drill** with an incoming technical owner.
      Exercises 5–12 of the drill have each been verified individually against a running server
      during implementation. What has not happened is *a person other than the builder* performing
      them end to end. Marking these done from a code review would be false.
      The operator guide's screenshots are now captured and embedded, so it is ready to hand to
      a usability-test participant.

## Notes for whoever picks this up next

- Full test suite (320 tests as of this writing) passes; `ruff check` and `mypy --strict` are clean.
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

# 07 — Provide local monitoring and alert dashboard

**What to build:** A local dashboard that makes data quality, missing actuals, data drift, prediction error, and model-degradation conditions visible for operational follow-up.

**Blocked by:** 02 — Import and validate historical ANGBER datasets; 06 — Capture actual fuel and evaluate outcomes.

**Status:** ready-for-agent

- [x] The dashboard shows unresolved data-quality issues and dataset validation summaries.
- [x] The dashboard identifies predictions still missing Actual Fuel after a configurable interval.
- [x] The dashboard shows feature-distribution drift and configured warning thresholds.
- [x] The dashboard shows rolling error trends and category-level degradation when matched Actual Fuel is available.
- [x] Alerts remain inside the local application and do not require email or messaging integration.

## Comments

- 2026-08-19: Implemented a local, idempotent alert reconciliation with persisted first/last
  observation and resolution timestamps. Evidently runs feature-drift analysis in-process against
  the active model dataset; no hosted service, credential, email, or automatic promotion is used.
  DeepWiki was unavailable and was not used. The existing manual candidate/promotion workflow is
  unchanged.

# 04 — Fingerprint the taxonomy a model was trained on, and alert when it drifts

**What to build:** A pure `catalog_fingerprint(options)` over sorted `(name, type, group)` triples, logged as an MLflow param and stored on the model version and (optionally) in the external package manifest; a monitoring alert kind "Penggolongan kendaraan berubah sejak model dilatih; latih ulang kandidat." raised at activation and by the monitoring job — only for models whose `feature_version` is in the lineage-aware list kept next to `FEATURE_VERSION`.

**Blocked by:** 02 — Add the type column to the catalog and a lineage resolver.

**Status:** in-review

- [x] The fingerprint is identical across row order and alias order, and changes when a single row's type changes.
- [x] A model trained now carries the fingerprint; an older model or package without one is handled as "unknown", never as a mismatch.
- [x] Manifest schema accepts the new optional field; every existing valid package still validates.
- [x] The alert is raised on mismatch for a lineage-aware model, silent on match, and silent for `baseline-v2` even on mismatch; the lineage-aware list is empty in this ticket.
- [x] The dashboard shows the alert with its remediation text like the existing alert kinds; the operator guide names it.

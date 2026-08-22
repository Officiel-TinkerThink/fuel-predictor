# 02 — Import and validate historical ANGBER datasets

**What to build:** An end-to-end upload workflow that accepts historical Excel/CSV data, creates a versioned dataset from valid Daily Operations, and gives the user a correction report for rows that cannot be safely used.

**Blocked by:** 01 — Create a local daily-operation planning foundation.

**Status:** ready-for-agent

- [ ] A user can upload the historical ANGBER workbook and see a dataset version with source provenance.
- [ ] Blank pre-created calendar rows are excluded without being reported as fuel operations.
- [ ] Lifting-hour headers are normalized while preserving the source header and sheet provenance.
- [ ] Malformed or invalid values are quarantined with row-level reasons; they are not silently guessed or accepted.
- [ ] Valid rows remain available for training and corrected data can be re-imported.

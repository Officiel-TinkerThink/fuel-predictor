# 02 — Record actual fuel by operation code

**What to build:** `RecordActualFuel` resolves the reference it is given as an `OPR-…` id or an
operation code (case and spaces ignored) and stores the record against the operation id. The web
form, `POST /api/v1/daily-operations/{ref}/actual-fuel` and the spreadsheet import all go through
it. The import template names the column "Kode Operasi (wajib)" and still reads sheets headed
"ID Operasi".

**Blocked by:** 01.

**Status:** in-review

- [x] The form accepts `260923-0914-vt01` and records against the matching `OPR-…` operation.
- [x] A spreadsheet row with a code is accepted; one with an unknown code is quarantined with a
      message that names the code column.
- [x] Old sheets headed "ID Operasi (wajib)" with `OPR-…` ids still import.

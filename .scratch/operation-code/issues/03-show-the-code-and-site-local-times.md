# 03 — Show the code wherever the operator notes or looks for an operation, in site-local time

**What to build:** the saved-operation and estimate pages show the code prominently, with a copy
button and a "write this down" hint; the bulk prediction result table and its CSV carry a
"Kode operasi" column; the actual-fuel waiting list, the prediction history and the saved-actual
confirmation show the code; the operation API response and the MCP `predict_fuel` result include
`operation_code`. Every time the screens show is rendered in the site time zone.

**Blocked by:** 01.

**Status:** in-review

- [x] The estimate page shows the code as the primary identifier; the `OPR-…` id moves to the
      technical details.
- [x] The bulk result CSV has "Kode operasi" as its second column.
- [x] The waiting list, and the "Catat" links it offers, use the code.
- [x] A time stored as 02:14 UTC is displayed as 09:14.
- [x] The operator guide explains what the code is and when to write it down.

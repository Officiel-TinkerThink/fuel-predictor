# 02 — The vehicle code in the operation code

**What to build:** a domain rule for the vehicle code (group - type - unit mark, skipping a missing
part); `CreateDailyOperation` looks the unit up in the catalog and forms
`yymmdd-hhmm-<vehicle code>`; the code column widens to fit.

**Blocked by:** 01.

**Status:** in-review

- [x] `VT 01` planned at 09:14 gets `260924-0914-VT-P410-VT01`.
- [x] A unit written with an alias gets its catalog unit's code (`oft tronton` → `TR-HINO-OFT`).
- [x] A unit with no type code gets `VT-VT14`; a vehicle not in the catalog gets its unit mark.
- [x] Typed back in any case or spacing, the code still finds the operation.

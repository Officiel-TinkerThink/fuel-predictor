# Fleet taxonomy from the Data Ratio sheet, in the operation code, and on a page

Status: in-review

Written 2026-09-24 from the product owner's request and the "Data Ratio" tab of the "Data Trip
Angber" workbook (`src/fuel_predictor/examples/data-ratio-angber.csv`).

## Problem

The catalog's type level (ADR 0015) was a placeholder: every unit's type was its group. The owner's
sheet names each unit's real type ("Type Kendaraan"): the fifteen vacuum trucks alone are four
different machines. The sheet also spells units differently from the catalog ("PM 01",
"Whinch Truck OFT", "Tronton OFT"), and the trip tabs use yet other spellings ("OFT Tronton",
"OFT Winch Truck", "SCM") that don't resolve today. Operators can't see the taxonomy anywhere,
and the operation code names only the unit.

## Decisions (agreed with the product owner)

1. **Types come from the sheet's "Type Kendaraan"**, written as the sheet writes them. Units the
   sheet doesn't list (VT 14, VT 15, the two forklifts) keep their group as their type.
2. **Catalog names stay; sheet spellings become aliases.** Operations and the trained model key on
   the catalog name, so renaming would split history and blind the model. `Oil Field Truck` is the
   sheet's "Tronton OFT" / "OFT Tronton" (HINO FM 260); `Winch Truck` is "Whinch Truck OFT" /
   "OFT Winch Truck" (Scania P410CB 6x6). The trip tabs use exactly these two OFT units.
3. **Every group and every type has a short code**, held in the catalog next to its name (columns
   `kode_grup`, `kode_tipe`) so the owner controls them: `VT` Vacuum Truck, `CR` Crane,
   `TR` Truck, `FL` Forklift; `P410` Scania P410 6X6, `UDQ` UD Truck Quester, and so on.
4. **Vehicle code = group - type - unit**: `VT-P410-VT01`. A unit whose type is only its group
   has no type code and its code skips that part: `VT-VT14`. A vehicle not in the catalog keeps
   the unit mark alone.
5. **The operation code carries the vehicle code**: `260924-0914-VT-P410-VT01` (chosen by the owner
   over unit + type and over unit only). Codes already issued are never rewritten.
6. **An "Armada" page** lists every unit with its vehicle code, group, type and other spellings, so
   anyone can check a code against the fleet. The code callout on the estimate names what each part
   of the code means.
7. **A test pins the catalog to the Data Ratio sheet**: every unit the sheet lists resolves to a
   catalog unit of the same type. A later sheet export that disagrees fails the build.

## Out of scope

- The sheet's fuel ratios (Drive Ratio, Lift Ratio, recommendation). They are a separate model input.
- Rewriting codes of operations created before this change.
- Loading the new catalog into a running database automatically: after deploying, run
  `python -m fuel_predictor import-vehicles`.

## Issues

- `issues/01-types-codes-and-aliases-in-the-catalog.md`
- `issues/02-vehicle-code-in-the-operation-code.md`
- `issues/03-fleet-page-and-code-legend.md`

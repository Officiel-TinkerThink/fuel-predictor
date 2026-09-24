# 01 — Types, codes and aliases in the vehicle catalog

**What to build:** `kendaraan-angber.csv` gains the sheet's types, the `kode_grup` / `kode_tipe`
columns and the sheet's spellings as aliases; `VehicleOption` carries the codes; the `vehicles`
table stores them (migration); loading a catalog refuses inconsistent codes; a test pins the
catalog to `data-ratio-angber.csv`.

**Blocked by:** nothing.

**Status:** in-review

- [x] Every unit in the Data Ratio sheet resolves to a catalog unit whose type is the sheet's type.
- [x] "OFT Tronton", "Tronton OFT", "OFT Winch Truck", "Whinch Truck OFT", "SCM" resolve.
- [x] A catalog where one group or one type has two different codes, or a code with characters
      other than capitals and digits, is refused with a message naming the row.
- [x] `import-vehicles` stores the codes; the migration adds the columns.

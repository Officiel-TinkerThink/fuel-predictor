# 02 — Add the type column to the catalog and a lineage resolver

**What to build:** A `tipe` column in the vehicle catalog (CSV `tipe`, table `vehicle_type`, one Alembic revision backfilled from `vehicle_group`), `VehicleOption.type`, and `lineage_of(name) -> VehicleLineage(vehicle, type, group)` on the `VehicleCatalog` port with both implementations.

**Blocked by:** None — can start immediately (01 in parallel).

**Status:** ready-for-agent

- [ ] `kendaraan-angber.csv` gains `tipe`, filled with each row's group name; a CSV without the column, or with a blank cell, still imports with the type named after the group.
- [ ] `python -m fuel_predictor import-vehicles` round-trips the column into the table and back out through `options()`.
- [ ] `lineage_of` resolves canonical names and aliases, and returns `tidak diketahui` at every level for an unknown or empty name without raising.
- [ ] A migration on a populated database leaves every existing row with `vehicle_type == vehicle_group`.
- [ ] No form, template, or MCP tool input changes.

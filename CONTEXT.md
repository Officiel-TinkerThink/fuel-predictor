# Fuel Prediction System Context

## Glossary

- **Daily operation**: one row representing a vehicle category's complete activity sequence for a day, including travel, lifting where applicable, and return travel.
- **ANGBER**: *Angkutan Berat*; the heavy-equipment category used for a daily operation.
- **Prepared fuel**: fuel newly issued for a daily operation. It is the only current target label and is not yet verified actual consumption.
- **Actual fuel**: post-operation, ground-truth fuel consumption recorded later against an operation, named by its operation code or operation ID.
- **Operation code** (kode operasi): the short identifier an operator writes down when a prediction is made and types back to record actual fuel — `260923-0914-VT01`: creation time in site-local time, then the vehicle. Fixed at creation; unique, with `-2`, `-3` for the same vehicle within one minute (ADR 0016). _Avoid_: prediction ID (actual fuel belongs to the operation, not to one of its predictions).
- **Operation ID**: the internal `OPR-…` key of an operation. Still accepted wherever a code is, but never what a person is asked to copy.
- **Stop sequence**: ordered locations supplied by a planner, such as depot → site A → site B → depot. The entered order is authoritative.
- **Estimated fuel requirement**: the predicted fuel value shown while prepared fuel remains the training label.
- **Recommended allocation**: a conservative fuel amount derived from the estimate and uncertainty, intended to reduce shortages.
- **Location catalog**: the future source of stable location IDs, names, aliases, and coordinates.

### The fleet

- **Vehicle** (kendaraan): one physical unit the planner names on an operation — `VT 01`, `Truck Crane 01` — by its canonical name or any alias the sheets use. The only thing about the fleet a planner is ever asked for. _Avoid_: instance.
- **Vehicle type** (tipe kendaraan): the owner's finer cut inside a group, such as "VT A" among the vacuum trucks. A group with a single type names its type after the group, which is every group today.
- **Vehicle group** (grup kendaraan): the kind of machine — Vacuum Truck, Truck, Crane, Forklift.
- **Vehicle lineage**: a unit's type and group as the catalog says them *right now*: vehicle → type → group → vehicle category (ANGBER). Derived from the catalog when a prediction, a training run or a history lookup needs it; recorded on a prediction only as a trace, never read back (ADR 0015).
- **Vehicle catalog**: the fleet as the workbook's "Dim_Kendaraan" sheet lists it — name, type, group, aliases. The single place the lineage is defined; editing it is how the owner re-types the fleet.
- **Fallback order**: same unit → same type → same group, and then nothing. The one order the application uses wherever it looks for "the same kind of vehicle". The vehicle category is not a level: every unit is ANGBER, so it would only mean "some other machine".

### Agents and their access

- **Agent client**: any program that calls the MCP endpoint. Whatever token it presents, this is the principal that is authorized, rate-limited, and named in the audit trail.
- **Scope**: one coarse permission an agent client holds (`fuel:predict`, `fuel:monitor`, `models:read`, `models:admin`). Deliberately coarser than a human capability.
- **Agent credential**: a long-lived static token an administrator issues to an agent client that belongs to no user. For headless agents and CI. _Avoid_: API key.
- **Registered agent client**: a program (a coding agent, a connector) that has told the server its name and the redirect addresses it may be sent back to. Registering grants nothing.
- **Authorization code**: a user's consent in transit: minted when they allow a registered agent client, redeemed once for a grant, dead within minutes either way.
- **Agent grant**: a user's standing delegation of some of their own scopes to one registered agent client. Short-lived access token plus refresh token; the grant, not the token, is what gets revoked. A grant is presented to the MCP endpoint as an agent client named "user via client". _Avoid_: OAuth token, connection.

## Product boundary

The MVP is a locally run, Indonesian-language fuel-prediction application. It has no user accounts, roles, approvals, or route optimization. It predicts the prepared fuel requirement for a daily operation, records feedback, and monitors data/model health.

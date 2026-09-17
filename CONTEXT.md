# Fuel Prediction System Context

## Glossary

- **Daily operation**: one row representing a vehicle category's complete activity sequence for a day, including travel, lifting where applicable, and return travel.
- **ANGBER**: *Angkutan Berat*; the heavy-equipment category used for a daily operation.
- **Prepared fuel**: fuel newly issued for a daily operation. It is the only current target label and is not yet verified actual consumption.
- **Actual fuel**: post-operation, ground-truth fuel consumption recorded later against an operation ID.
- **Stop sequence**: ordered locations supplied by a planner, such as depot → site A → site B → depot. The entered order is authoritative.
- **Estimated fuel requirement**: the predicted fuel value shown while prepared fuel remains the training label.
- **Recommended allocation**: a conservative fuel amount derived from the estimate and uncertainty, intended to reduce shortages.
- **Location catalog**: the future source of stable location IDs, names, aliases, and coordinates.

### Agents and their access

- **Agent client**: any program that calls the MCP endpoint. Whatever token it presents, this is the principal that is authorized, rate-limited, and named in the audit trail.
- **Scope**: one coarse permission an agent client holds (`fuel:predict`, `fuel:monitor`, `models:read`, `models:admin`). Deliberately coarser than a human capability.
- **Agent credential**: a long-lived static token an administrator issues to an agent client that belongs to no user. For headless agents and CI. _Avoid_: API key.
- **Registered agent client**: a program (a coding agent, a connector) that has told the server its name and the redirect addresses it may be sent back to. Registering grants nothing.
- **Authorization code**: a user's consent in transit: minted when they allow a registered agent client, redeemed once for a grant, dead within minutes either way.
- **Agent grant**: a user's standing delegation of some of their own scopes to one registered agent client. Short-lived access token plus refresh token; the grant, not the token, is what gets revoked. A grant is presented to the MCP endpoint as an agent client named "user via client". _Avoid_: OAuth token, connection.

## Product boundary

The MVP is a locally run, Indonesian-language fuel-prediction application. It has no user accounts, roles, approvals, or route optimization. It predicts the prepared fuel requirement for a daily operation, records feedback, and monitors data/model health.

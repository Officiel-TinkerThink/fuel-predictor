# Frontend maintainability and quality

Apply when organizing frontend code, adding dependencies, or verifying a change.

- Follow the project’s existing directory structure, build tools, and conventions unless a change is deliberately documented and justified.
- Keep dependencies flowing from feature intent toward implementation details. Avoid cross-feature reach-through and unbounded shared utility folders.
- Prefer small, composable modules with explicit inputs and outputs. Put shared code in a shared location only after more than one consumer has a stable common need.
- Keep types precise at boundaries and remove dead code, near-duplicates, and obsolete states as part of the change.
- Test behavior from the user’s perspective where practical, alongside focused tests for reusable logic and contract mapping.
- Respect performance budgets: avoid unnecessary client work, duplicate requests, and large dependencies for small tasks.

## Check

Before finishing, run the relevant lint, type, test, and build checks available in the project and review the changed user flow.

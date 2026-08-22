# Frontend data and contracts

Apply when working with client data, backend requests, forms, caching, or state changes.

- Consume documented contracts through one well-defined client boundary. Keep URLs, credentials, headers, and transport details out of visual components.
- Validate input early for usability, but treat the server as the authority for business rules, permissions, and final outcomes.
- Map raw responses into stable view data once. Components should receive named states and values rather than repeatedly inspect transport payloads.
- Make cache, refresh, retry, and optimistic-update behavior explicit. Use optimistic changes only when they are reversible and conflicts are handled.
- Protect sensitive data from URLs, browser storage, analytics, logs, and error messages unless the feature explicitly requires a protected mechanism.
- Keep state-changing interactions safe against accidental duplicate submission when the contract supports it.

## Check

Before finishing, test the request payload, server rejection path, recovery behavior, and any cached or optimistic state.

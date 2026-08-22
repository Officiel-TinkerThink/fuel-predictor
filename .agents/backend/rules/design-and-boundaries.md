# Backend design and boundaries

Apply when creating or changing backend behavior, modules, services, or integrations.

- Organize code around clear business capabilities and public contracts. Keep each module cohesive and expose only what other modules need.
- Keep business rules deterministic and independent of transport, persistence, provider, and framework details. Pass time, identity, randomness, and external facts in explicitly.
- Keep delivery code focused on parsing input, authentication, authorization, invoking the intended operation, and returning a safe response.
- Define small interfaces at boundaries where a capability needs a replaceable collaborator. Implement them outside the business core.
- Keep dependencies directional and explicit. A business concept must not depend on a delivery or infrastructure concern.
- Use names from the project’s domain language; prefer specific concepts over generic buckets such as `helpers`, `utils`, or `manager`.

## Check

Before finishing, confirm the change has one clear owner, visible dependencies, and business behavior that can be tested without network, database, or framework setup.

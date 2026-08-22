# Domain Docs

## Layout

This is a single-context project. Domain terminology is maintained in `CONTEXT.md` at the repository root. Architecture decisions are maintained in `docs/adr/`.

## Consumer rules

- Before implementing a feature, read the relevant parts of `CONTEXT.md` and any applicable ADRs.
- Before changing application code, read the relevant ticket, the repository knowledge guide, and the generated Understand Anything wiki when it is available.
- Use glossary terms consistently in specifications, tickets, code, and tests.
- If a decision conflicts with an ADR, surface the conflict rather than silently overriding it.
- If the relevant context or ADR does not exist, proceed without treating its absence as an error.

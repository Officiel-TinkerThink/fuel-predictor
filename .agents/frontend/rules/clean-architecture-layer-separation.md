# Frontend clean architecture layer separation

Apply when deciding file location or imports.

## Layers

```
domain ← application ← { infrastructure, presentation } ← app/
                   ← ports ← infrastructure
```

| Layer | Holds | Never |
|---|---|---|
| `domain/` | API contracts, schemas, pure types/predicates | React, fetch, framework, browser globals |
| `ports/` | consumer-owned gateway interfaces | URLs, HTTP verbs, `Response` |
| `application/` | one intent per file, view-model/error mapping | JSX, hooks, direct fetch |
| `infrastructure/` | HTTP/BFF, storage, gateway adapters | business decisions, JSX |
| `presentation/` | components, hooks, local UI state | backend URLs, credentials, transport details |
| `app/` | routes, layouts, route handlers, route-only composition | reusable feature logic |
| `shared/` | dependency-light formatting/result helpers | domain or feature logic |

## Rules

- Backend is source of truth for business decisions. Client validation only prevents obviously invalid input; server result is authoritative.
- Ports are small, intent-named interfaces defined by their consumer. Every port has a typed fake for tests.
- Server/client component boundary is execution concern, not another architecture layer.
- Enforce import direction with ESLint boundaries or equivalent. `any` at a boundary is a failure, not flexibility.

## Worked example

```ts
// application/projects/archiveProject.ts
export async function archiveProject(gateway: ProjectGateway, id: string) {
  return gateway.archive(id)
}

// Bad: component talks transport directly.
await fetch('https://api.example.test/projects/1/archive', { method: 'POST' })
```

## Never

- Components directly calling external backend URLs or handling credentials.
- Domain importing presentation/framework code.
- A generic `services/` or `lib/` dumping ground.

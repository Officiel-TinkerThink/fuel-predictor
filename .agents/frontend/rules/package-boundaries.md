# Frontend package boundaries

Apply when importing across directories/features.

## Allowed dependency direction

`app → presentation/application → ports/domain/shared` and `infrastructure → ports/domain/shared`.

Presentation may call application through hooks. Application depends on ports/domain. Infrastructure implements ports. Domain/shared are leaf layers.

## Rules

- Features may import their own files and public common/shared contracts only.
- Cross-feature behavior uses an application port, public feature contract, or common component — never private deep import.
- Alias imports must preserve visible layer ownership.
- Configure `eslint-plugin-boundaries` (or equivalent) to fail forbidden imports in CI.
- Avoid barrel exports across feature/layer boundaries; direct imports make dependency graph clear.

## Never

- `presentation` importing `infrastructure` directly.
- `domain` importing `app`, React, Next.js, or browser APIs.
- A shared package depending on a feature.

## Worked example

```ts
// Allowed: presentation hook uses application intent.
import { archiveProject } from '@/application/projects/archiveProject'

// Forbidden: presentation reaches transport adapter directly.
import { HttpProjectGateway } from '@/infrastructure/http/HttpProjectGateway'
```

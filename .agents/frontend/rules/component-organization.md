# Component organization

Apply when adding/splitting React components.

## Placement

| Kind | Location |
|---|---|
| Route-only composition | `app/**/page.tsx` |
| Feature component | `presentation/components/<feature>/` |
| Cross-feature composition | `presentation/components/common/` |
| Design-system primitive | `presentation/components/ui/` |

## Rules

- One exported component per file. Filename, component, and export name match.
- Keep component below roughly 200 lines. Split by responsibility, not arbitrary file halves.
- Promote feature component to `common/` only after real second consumer appears.
- Props are explicit, readonly, and narrow. Avoid entity spreads, untyped records, boolean soup, and more than roughly seven interacting props.
- Keep business/transport logic out. Component renders supplied view state and emits user intent.
- Keep pure non-DOM helpers in `.ts`, test them separately, and colocate component tests.
- Do not import another feature's private component. Move true reuse to common.

## Worked example

```tsx
// presentation/components/projects/ProjectCard.tsx
export function ProjectCard({ name, onOpen }: Readonly<{ name: string; onOpen(): void }>) {
  return <button type="button" onClick={onOpen}>{name}</button>
}

// Bad: <ProjectCard {...project} /> exposes every present/future field as UI API.
```

## Never

- Barrel files that hide import origin.
- `div` with click handler instead of semantic control.
- Inline currency/date business formatting; use shared formatter.

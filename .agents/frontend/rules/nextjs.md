# Next.js rules

Apply to App Router routes, layouts, route handlers, metadata, server/client components, caching, and navigation.

## Rules

- Default to Server Components. Add `'use client'` only at smallest interactive leaf requiring state, effects, browser API, or event handlers.
- Keep routes thin: compose presentation/application code; do not place reusable logic in `app/`.
- Route handlers are server adapters: parse/authenticate/authorize/call application intent/serialize. They do not contain business logic.
- Use framework metadata APIs for title, description, canonical, robots, and social metadata. Treat external content as untrusted.
- Declare cache/revalidation behavior deliberately. Never cache authenticated, personalized, or rapidly changing data as public response.
- Handle loading, error, not-found, and redirect states at route boundary. Preserve correlation ID and safe error handling.
- Keep secrets server-only. Browser receives only explicitly public configuration.
- Use server-side BFF/proxy boundary where browser must call private backend; enforce authorization again server-side.

## Never

- Fetch secrets or private provider APIs from client component.
- Mark a high-level layout client just to support one interactive child.
- Depend on client-side authorization for protection.

## Worked example

```tsx
// Server route composes; interactive leaf owns browser state.
export default async function Page() {
  const project = await getProjectForPage()
  return <ProjectDetails project={project} />
}

// `ProjectRenameForm.tsx` becomes a client component only when it needs form state.
```

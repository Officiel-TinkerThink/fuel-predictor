# UI component approach

Apply when choosing/building UI primitives and styling.

## Rules

- Reuse approved design-system primitive before building a new one. Keep primitives generic and domain-free.
- Compose primitives into feature components; do not introduce competing UI libraries without architecture decision.
- Use design tokens for color, typography, spacing, radius, elevation, status, and motion. Avoid arbitrary repeated values.
- Favor composition/children over expanding configuration prop lists.
- Use semantic HTML first, then accessible primitives. Keyboard, focus, labels, contrast, touch target, reduced motion, and screen-reader support are required behavior.
- Do not use color as sole carrier of meaning. Provide text/icon/table alternative for charts or visual status.
- Sanitize any rendered rich text/markdown through restricted allowlist. Treat authored and API content as untrusted.
- Design loading skeleton, empty state, validation state, error/retry state, and disabled state with bounded layout.

## Never

- `dangerouslySetInnerHTML` without approved sanitizer.
- Clickable non-semantic elements, removed focus outline, or inaccessible modal.
- Inline style/class hacks where token/variant belongs in design system.

## Worked example

```tsx
// Good: semantic control, visible name, token-based styling.
<Button variant="destructive" type="button">Archive project</Button>

// Bad: inaccessible click target and hard-coded unshared color.
<div onClick={archive} className="text-[#d00]">Archive</div>
```

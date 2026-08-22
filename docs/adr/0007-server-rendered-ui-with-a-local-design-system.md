# ADR 0007: Deliver the production UI as server-rendered templates with a local design system

## Status

Accepted

## Context

The MVP renders Indonesian HTML from f-strings inside `delivery/form.py`. That file has grown past
a thousand lines, mixes page structure with request handling, and repeats markup for headers,
fields, tables, and error summaries. The production plan requires a polished Indonesian interface
with a reusable design system, accessible components, and pages that stay usable when external
networks are unavailable.

The operator is non-technical, there are at most five users, and the target machine is a 1-2 vCPU
VM with 1-2 GB RAM. Introducing a JavaScript application would add a second runtime, a build
pipeline, and a deployment surface that nobody on this project is staffed to maintain.

## Decision

Keep one deployable FastAPI application and render the human interface on the server with Jinja2
templates. Replace the f-string rendering in `delivery/form.py` with:

- a base layout holding the application shell, navigation, and breadcrumbs;
- partial templates for the components the plan names: form fields with units, status badges,
  metric cards, data tables, confirmation dialogs, step indicators, and alert banners;
- one hand-written CSS file expressing the design tokens (color, spacing, typography, focus rings)
  and component classes.

Serve every stylesheet, script, font, and icon from the application's own `static/` directory. Do
not reference a CDN and do not add a Node build step; the CSS and the small amount of progressive-
enhancement JavaScript are authored directly in their final form.

Behaviour must work without JavaScript. Forms submit normally, validation errors render on the
server in Indonesian, and entered values survive a failed submission. JavaScript only enhances:
client-side table filtering, confirmation dialog focus management, and file-upload progress.

Templates receive plain view-model dataclasses assembled in the delivery layer. Templates never
reach into repositories, use cases, or domain objects directly.

## Research and adaptation

- [FastAPI templates](https://fastapi.tiangolo.com/advanced/templates/) documents `Jinja2Templates`
  and `StaticFiles` as the supported server-rendering path. We use exactly that, with no additional
  view framework.
- [Jinja2](https://jinja.palletsprojects.com/en/stable/templates/#template-inheritance) documents
  template inheritance and macros. Page templates extend one base layout, and reusable components
  are macros rather than copied markup.
- [WCAG 2.2](https://www.w3.org/TR/WCAG22/) informs the non-negotiable baseline we adopt: visible
  focus, contrast, semantic labels, and status conveyed by text and shape rather than colour alone.
  We adopt the specific success criteria the plan already names instead of claiming full conformance
  we cannot yet verify.

We rejected Next.js, HTMX, Tailwind, and any component library delivered by CDN. Each would either
add a second runtime, a build toolchain, or an external network dependency, and none solves a
problem this product actually has at five users. The frontend rules under `.agents/frontend/` assume
a React/Next.js codebase and therefore do not apply to this server-rendered interface; their intent
— separating presentation from business logic — is honoured by keeping use cases in the application
layer and view models in the delivery layer.

## Consequences

`delivery/form.py` becomes request handling and view-model assembly only, and page structure moves
into version-controlled templates that a designer can read. Adding a page means adding a template
plus a route, not another block of escaped markup.

The project takes on Jinja2 as a direct dependency, which FastAPI already expects for this path.
Style changes are hand-authored CSS rather than generated utility classes, so the design tokens must
stay disciplined to avoid drift. Because there is no build step, the CSS file is served as written
and must be kept small enough to remain fast without minification.

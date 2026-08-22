# Repository Knowledge Workflow

## Read before implementing

1. Read `AGENTS.md`, `CONTEXT.md`, relevant ADRs, and the assigned local ticket.
2. Read generated project-wiki material from Understand Anything when available, including the knowledge graph and onboarding output.
3. Use direct code reading only to verify the wiki or examine the narrow area that the ticket changes. The wiki is the orientation layer; code remains the final source for implementation facts.

## DeepWiki research rule

Before introducing a substantial pattern, integration, or architecture not already decided in an ADR, consult DeepWiki for one or more named relevant repositories. Capture the conclusion in the ticket or an ADR:

- what was examined;
- which practice is applicable here and why;
- what is intentionally not adopted; and
- how the adopted approach differs from the reference.

DeepWiki and open-source repositories are reference material, not implementation instructions. Agents may choose a different approach when it better fits this local Fuel Prediction MVP.

## Adopted dependencies

Use these as software dependencies when their tickets call for the capability. Do not reimplement their responsibilities:

- FastAPI for the backend API.
- MLflow for experiment tracking and the model registry.
- Evidently for data-quality, data-drift, and model-performance monitoring.

## Initial DeepWiki reference systems

DeepWiki research must name one or more of these complete ML systems, rather than asking a broad, repository-free question:

- `KonuTech/mlops-zoomcamp-project`: a used-car regression system with data preparation, batch scoring, FastAPI, MLflow, and Evidently. It is closest to the Fuel Prediction MVP's tabular prediction lifecycle.
- `nikolas-j/credit-risk-model-drift-monitoring`: an end-to-end FastAPI service with schema validation, model registry, and drift/performance monitoring. Use it for the governed lifecycle shape, not its credit-risk domain logic.
- `loganrudd/spacecraft-telemetry-anomaly-detection`: a complete ML platform whose value is the operational system surrounding a model: training, registry, monitoring, serving, dashboard, and documented evaluation. Use it only for platform boundaries and observability ideas.

Before adopting a pattern, inspect its project through DeepWiki and record why it fits the Fuel Prediction MVP. Do not copy its domain model, deployment scale, or implementation wholesale.

## Understand Anything usage

After the first application foundation is present, run `/understand` in Codex chat to create the initial repository knowledge graph. Re-run it incrementally after meaningful changes. Use `/understand-dashboard` for architecture exploration and `/understand-onboard` when refreshing onboarding material for new agents.

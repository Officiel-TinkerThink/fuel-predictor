## Agent skills

### Issue tracker

Issues and specifications live as local Markdown files under `.scratch/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Uses the default canonical triage labels. See `docs/agents/triage-labels.md`.

### Domain docs

Uses a single shared context at the repository root. See `docs/agents/domain.md`.

### Repository wiki and external references

Before changing application code, read the project wiki and relevant ticket first. When available, use Understand Anything to orient from the generated repository knowledge and refresh it after meaningful changes. Use FastAPI, MLflow, and Evidently as dependencies; do not rebuild their capabilities. Use DeepWiki only as a research aid for a named complete open-source ML system, identify practices that fit this project, and explain any adaptation or rejection. Do not copy an external implementation or treat it as authoritative. See `docs/agents/repository-knowledge.md`.

### Engineering standards

Build a clean, domain-driven, data-contract-first modular application. Define behavior with tests before or alongside implementation, keep business rules independent of delivery/UI infrastructure, remove duplication instead of accumulating near-copies, and prefer small cohesive modules with explicit interfaces. Emit and handle domain events when they represent meaningful lifecycle changes; do not introduce event infrastructure merely for style. See `docs/agents/engineering-standards.md`.

### Project rules

Use the rules in `.agents/` when changing application code. Start with the relevant backend or frontend topic, then apply only the guidance that fits the change. These rules describe outcomes and boundaries; follow the project’s existing tooling, structure, and contracts rather than introducing a prescribed framework or architecture.

- Backend: `.agents/backend/rules/`
- Frontend: `.agents/frontend/rules/`

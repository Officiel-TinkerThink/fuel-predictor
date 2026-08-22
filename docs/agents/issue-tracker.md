# Issue tracker: Local Markdown

Issues and specifications for this project live as Markdown files in `.scratch/`.

## Conventions

- One feature per directory: `.scratch/<feature-slug>/`
- The specification is `.scratch/<feature-slug>/spec.md`
- Implementation issues are one file per ticket at `.scratch/<feature-slug>/issues/<NN>-<slug>.md`, numbered from `01`
- Triage state is recorded as a `Status:` line near the top of each issue file; see `triage-labels.md` for role strings
- Comments and conversation history append to the bottom of the issue under a `## Comments` heading

## Publishing and reading

When an engineering skill says to publish to the issue tracker, create the appropriate file under `.scratch/<feature-slug>/`.

When an engineering skill says to fetch a ticket, read the referenced file path or issue number.

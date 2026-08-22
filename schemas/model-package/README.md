# Model package schemas

Published contracts for the model package format defined in
[ADR 0009](../../docs/adr/0009-external-model-package-format.md). The external
training environment's packager and this production application both validate
against these files, so the contract has exactly one definition.

- `manifest.schema.json` — the shape of `manifest.json` inside a package archive.
  Validated in Python by `JsonSchemaManifestValidator`
  (`src/fuel_predictor/infrastructure/jsonschema_manifest_validator.py`), which
  is used from `ParseModelPackageManifest`
  (`src/fuel_predictor/application/model_package_ingestion.py`).

Not yet published: `input-schema.json`'s own schema, and the `smoke-tests.json`
and `reference-statistics.json` contracts. Those land with the archive-handling
and isolated-loading work — see `docs/production/implementation-progress.md`.

Schema-shape validation (does this look like a manifest?) and business-rule
validation (is this manifest's feature contract one production actually
supports right now?) are deliberately separate: the schema can be checked by
any tool in any language, including the packager itself before it ever
uploads anything; which feature-contract and runtime versions are currently
*supported* is a fact only the running production application knows.

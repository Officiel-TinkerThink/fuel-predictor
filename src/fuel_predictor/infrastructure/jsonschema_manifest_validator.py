import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

SCHEMA_DIRECTORY = Path(__file__).resolve().parents[3] / "schemas" / "model-package"

MANIFEST_SCHEMA = SCHEMA_DIRECTORY / "manifest.schema.json"
SMOKE_TESTS_SCHEMA = SCHEMA_DIRECTORY / "smoke-tests.schema.json"
REFERENCE_STATISTICS_SCHEMA = SCHEMA_DIRECTORY / "reference-statistics.schema.json"


class JsonSchemaValidator:
    """Validates a raw dict against one of the published package schemas.

    The schema is checked for validity at construction, so a malformed schema
    file fails fast at startup rather than silently accepting every package.
    """

    def __init__(self, schema_path: Path) -> None:
        with schema_path.open(encoding="utf-8") as handle:
            schema = json.load(handle)
        Draft202012Validator.check_schema(schema)
        self._validator = Draft202012Validator(schema)

    def validate(self, raw: Mapping[str, Any]) -> list[str]:
        return sorted(_format(error) for error in self._validator.iter_errors(raw))


class JsonSchemaManifestValidator(JsonSchemaValidator):
    """Convenience binding for the manifest schema, the most-used one."""

    def __init__(self, schema_path: Path = MANIFEST_SCHEMA) -> None:
        super().__init__(schema_path)


def _format(error: ValidationError) -> str:
    location = "/".join(str(part) for part in error.path) or "(root)"
    return f"{location}: {error.message}"

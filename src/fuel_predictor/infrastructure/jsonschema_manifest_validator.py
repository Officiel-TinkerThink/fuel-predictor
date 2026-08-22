import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

_DEFAULT_SCHEMA_PATH = (
    Path(__file__).resolve().parents[3] / "schemas" / "model-package" / "manifest.schema.json"
)


class JsonSchemaManifestValidator:
    """Validates a raw manifest dict against the published JSON Schema."""

    def __init__(self, schema_path: Path = _DEFAULT_SCHEMA_PATH) -> None:
        with schema_path.open(encoding="utf-8") as handle:
            schema = json.load(handle)
        Draft202012Validator.check_schema(schema)
        self._validator = Draft202012Validator(schema)

    def validate(self, raw_manifest: Mapping[str, Any]) -> list[str]:
        messages = [_format(error) for error in self._validator.iter_errors(raw_manifest)]
        return sorted(messages)


def _format(error: ValidationError) -> str:
    location = "/".join(str(part) for part in error.path) or "(root)"
    return f"{location}: {error.message}"

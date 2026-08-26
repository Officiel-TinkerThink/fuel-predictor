"""Data files the application needs must ship inside the installed package.

Regression test. Both the model-package JSON Schemas and the demo CSV were
located by walking up from `__file__` (`parents[3]`). That resolves to the
repository root from a source checkout and to site-packages' *parent* once the
package is pip-installed, so the application died at startup in the container
with:

    FileNotFoundError: '/usr/local/lib/python3.12/schemas/model-package/manifest.schema.json'

The whole test suite passed throughout, because tests only ever run from a
checkout. Nothing here can catch that by reading a path — so these tests assert
the property that actually matters: the files are reachable as *package data*,
and no module resolves a runtime data file by climbing out of the package.
"""

import json
from importlib import resources
from pathlib import Path

import pytest

from fuel_predictor.infrastructure.jsonschema_manifest_validator import (
    MANIFEST_SCHEMA,
    REFERENCE_STATISTICS_SCHEMA,
    SMOKE_TESTS_SCHEMA,
    JsonSchemaManifestValidator,
    JsonSchemaValidator,
)

_PACKAGE_ROOT = Path(str(resources.files("fuel_predictor")))


def _escapes_the_package(path: Path) -> bool:
    """Look for the pattern in code only.

    Comments and docstrings are excluded deliberately — this very file's
    explanation of the bug mentions the pattern, and a test that cannot tell
    prose from code would fail on the documentation of its own reason.
    """
    import io
    import tokenize

    source = path.read_text(encoding="utf-8")
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):  # pragma: no cover
        return "parents[3]" in source
    code = "".join(
        token.string
        for token in tokens
        if token.type not in (tokenize.COMMENT, tokenize.STRING)
    )
    return "parents[3]" in code.replace(" ", "")


@pytest.mark.parametrize(
    "schema_path",
    [MANIFEST_SCHEMA, SMOKE_TESTS_SCHEMA, REFERENCE_STATISTICS_SCHEMA],
    ids=["manifest", "smoke-tests", "reference-statistics"],
)
def test_each_schema_is_readable_package_data(schema_path: Path) -> None:
    assert schema_path.is_file(), schema_path
    json.loads(schema_path.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "schema_path",
    [MANIFEST_SCHEMA, SMOKE_TESTS_SCHEMA, REFERENCE_STATISTICS_SCHEMA],
    ids=["manifest", "smoke-tests", "reference-statistics"],
)
def test_each_schema_lives_inside_the_package(schema_path: Path) -> None:
    """Inside the package directory is what makes it survive installation."""
    assert _PACKAGE_ROOT in schema_path.parents, (
        f"{schema_path} is outside {_PACKAGE_ROOT}; it will not be installed"
    )


def test_the_demo_dataset_is_packaged() -> None:
    from fuel_predictor.delivery.historical_dataset_pages import _DEMO_HISTORICAL_DATA

    assert _DEMO_HISTORICAL_DATA.is_file()
    assert _PACKAGE_ROOT in _DEMO_HISTORICAL_DATA.parents
    assert _DEMO_HISTORICAL_DATA.read_text(encoding="utf-8").strip()


def test_the_validators_construct_from_packaged_schemas() -> None:
    """Construction parses and checks the schema, so this proves it is real."""
    JsonSchemaManifestValidator()
    JsonSchemaValidator(SMOKE_TESTS_SCHEMA)
    JsonSchemaValidator(REFERENCE_STATISTICS_SCHEMA)


def test_no_module_resolves_a_data_file_by_climbing_out_of_the_package() -> None:
    """The pattern itself is the bug, so ban it rather than its instances.

    `Path(__file__).resolve().parents[3]` escapes the package. Anything doing
    that is reaching for a file that will not exist in an installed
    deployment — which is exactly how this shipped unnoticed twice.
    """
    offenders = [
        path.relative_to(_PACKAGE_ROOT)
        for path in _PACKAGE_ROOT.rglob("*.py")
        if _escapes_the_package(path)
    ]

    assert offenders == [], (
        "these modules locate files outside the installed package: " f"{offenders}"
    )

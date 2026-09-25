"""Every column of a template the app hands out is read back when uploaded.

The bulk prediction template's "Kendaraan (opsional)" normalised to
"kendaraan opsional", which the importer did not know: a sheet filled in from
the app's own template lost every vehicle without a word - no vehicle feature
for the model, no vehicle in the operation code, no lifting check.
"""

import pytest

from fuel_predictor.application.bulk_actual_fuel import _HEADER_ALIASES as ACTUAL_ALIASES
from fuel_predictor.application.bulk_operation_predictions import (
    _HEADER_ALIASES as PREDICTION_ALIASES,
)
from fuel_predictor.application.historical_datasets import normalize_header
from fuel_predictor.infrastructure.actual_fuel_template import BULK_ACTUAL_FUEL_TEMPLATE_HEADERS
from fuel_predictor.infrastructure.bulk_prediction_template import (
    BULK_PREDICTION_TEMPLATE_HEADERS,
)


@pytest.mark.parametrize(
    ("headers", "aliases"),
    [
        (BULK_PREDICTION_TEMPLATE_HEADERS, PREDICTION_ALIASES),
        (BULK_ACTUAL_FUEL_TEMPLATE_HEADERS, ACTUAL_ALIASES),
    ],
)
def test_every_template_header_maps_to_a_field(
    headers: tuple[str, ...], aliases: dict[str, set[str]]
) -> None:
    known = {alias for spellings in aliases.values() for alias in spellings}

    assert [header for header in headers if normalize_header(header) not in known] == []

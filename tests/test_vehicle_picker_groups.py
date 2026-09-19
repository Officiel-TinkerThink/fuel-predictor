"""The vehicle picker groups the fleet by kind of machine.

Twenty-odd units in one flat list, each suffixed with its group, read as a
wall; the browser's own <optgroup> puts Crane, Truck, Forklift and Vacuum
Truck under their own headings so the eye finds the unit by kind first.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from fuel_predictor.infrastructure.packaged_vehicle_catalog import PackagedVehicleCatalog
from fuel_predictor.main import create_app


def test_units_sit_under_their_group(tmp_path: Path) -> None:
    with TestClient(
        create_app(
            database_path=tmp_path / "operations.sqlite3",
            vehicle_catalog=PackagedVehicleCatalog(),
        )
    ) as client:
        form = client.get("/prediksi").text

    assert '<optgroup label="Truck">' in form
    assert '<optgroup label="Crane">' in form
    start = form.index('<optgroup label="Truck">')
    truck_group = form[start : form.index("</optgroup>", start)]
    assert '<option value="Prime Mover">Prime Mover</option>' in truck_group
    # The group is the heading now, not a suffix on every option.
    assert "Prime Mover — Truck" not in form

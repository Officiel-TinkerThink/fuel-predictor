"""Monitoring pages say what they found, and do not claim checks that never ran.

With too little data, Pergeseran Data showed "Belum tersedia" for the drifted
share and, right under it, "Tidak ada ciri yang bergeser melewati batas" -
a verdict nobody had computed. The audit trail named operations by their
OPR- id alone, not linked and without the code people use.
"""

from pathlib import Path
from urllib.parse import urlencode

from fastapi.testclient import TestClient

from fuel_predictor.main import create_app


def test_drift_without_enough_data_says_it_was_not_computed(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        page = client.get("/pemantauan/pergeseran-data").text

    assert "Belum dihitung" in page
    assert "Tidak ada ciri yang bergeser" not in page


def test_the_audit_trail_names_a_planned_operation_by_code_and_links_it(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        form = client.get("/prediksi").text
        marker = 'name="csrf_token" value="'
        start = form.index(marker) + len(marker)
        token = form[start : form.index('"', start)]
        client.post(
            "/operasi-harian",
            content=urlencode(
                [
                    ("vehicle_category", "ANGBER"),
                    ("activity_mode", "transport"),
                    ("total_distance_km", "30"),
                    ("distance_source", "manual"),
                    ("csrf_token", token),
                ]
            ),
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        audit = client.get("/audit").text

    assert "kode operasi" in audit
    assert 'href="/operasi-harian/OPR-' in audit

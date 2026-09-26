"""Fixing a bulk plan never plans an operation twice.

The result page and the guide said to fix the bad rows in the original file
and upload it again, "rows already done are not counted twice" - but every
row is planned afresh on upload, so each accepted operation got a duplicate.
The page now hands back only the rows to fix, in the template's columns with
the problem beside them; that file, fixed and uploaded, adds just those.
"""

import csv
import re
from io import StringIO
from pathlib import Path
from urllib.parse import unquote

from fastapi.testclient import TestClient

from fuel_predictor.infrastructure.packaged_vehicle_catalog import PackagedVehicleCatalog
from fuel_predictor.main import create_app
from tests.test_actual_fuel_outcomes import _train_baseline

_PLAN = (
    "Kendaraan,Aktivitas (wajib),Jarak Total (km) (wajib),Jam Lifting (opsional),"
    "Urutan Pemberhentian (opsional)\n"
    "VT 01,Mobilisasi,42,,\n"
    "VT 05,Mobilisasi,bukan angka,,\n"
    "VT 03,Mobilisasi + lifting,30,2,\n"
)


def _upload(client: TestClient, name: str, content: str) -> str:
    response = client.post(
        "/prediksi-operasi-massal",
        files={"file": (name, content.encode(), "text/csv")},
    )
    assert response.status_code == 200, response.text
    page: str = response.text
    return page


def _corrections(page: str) -> list[list[str]]:
    link = re.search(
        r'download="perbaiki-[^"]+"\s+href="data:text/csv;charset=utf-8,([^"]+)"', page
    )
    assert link is not None
    return list(csv.reader(StringIO(unquote(link.group(1)))))


def _operation_count(tmp_path: Path) -> int:
    from sqlalchemy import create_engine, text

    url = f"sqlite+pysqlite:///{(tmp_path / 'operations.sqlite3').as_posix()}"
    with create_engine(url).connect() as db:
        count: int = db.execute(text("SELECT COUNT(*) FROM daily_operations")).scalar_one()
    return count


def test_only_the_rows_to_fix_come_back_and_fixing_them_adds_only_those(
    tmp_path: Path,
) -> None:
    app = create_app(
        database_path=tmp_path / "operations.sqlite3", vehicle_catalog=PackagedVehicleCatalog()
    )
    with TestClient(app) as client:
        _train_baseline(client)
        first = _upload(client, "rencana.csv", _PLAN)
        rows = _corrections(first)
        # Fix the two rows the way a planner would, in that file.
        rows[1][2] = "35"
        rows[2][1] = "Mobilisasi"
        rows[2][3] = ""
        fixed = StringIO()
        csv.writer(fixed).writerows(rows)
        second = _upload(client, "perbaiki-rencana.csv", fixed.getvalue())

    assert "1 operasi mendapat kode dan estimasi." in first
    assert "2 baris perlu diperbaiki" in first
    # The template's columns plus the problem; the accepted row is not there.
    assert rows[0] == [
        "Kendaraan",
        "Aktivitas (wajib)",
        "Jarak Total (km) (wajib)",
        "Jam Lifting (opsional)",
        "Urutan Pemberhentian (opsional)",
        "Masalah",
    ]
    assert [row[0] for row in rows[1:]] == ["VT 05", "VT 03"]
    assert "lifting" in rows[2][5].lower()
    # The fixed file adds exactly the two missing operations, no duplicates.
    assert "2 operasi mendapat kode dan estimasi." in second
    assert _operation_count(tmp_path) == 3


def test_a_clean_upload_offers_no_corrections(tmp_path: Path) -> None:
    app = create_app(
        database_path=tmp_path / "operations.sqlite3", vehicle_catalog=PackagedVehicleCatalog()
    )
    with TestClient(app) as client:
        _train_baseline(client)
        page = _upload(client, "rencana.csv", _PLAN.split("VT 05")[0])

    assert "perlu diperbaiki" not in page
    assert 'download="perbaiki-' not in page
    # The results sheet speaks the form's words, not internal codes.
    results = re.search(r'href="data:text/csv;charset=utf-8,([^"]+)">Unduh hasil', page)
    assert results is not None
    text = unquote(results.group(1))
    assert "Mobilisasi" in text and ",transport," not in text

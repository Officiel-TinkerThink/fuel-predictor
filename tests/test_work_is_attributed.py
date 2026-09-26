"""Every operation and every actual-fuel record says who made it.

An administrator asked to "monitor" the people using the system had nothing
to look at: operations and actual records carried no author. They now carry
the signed-in username (or the agent client's name over MCP), and operations
carry the moment they were created, so a person's recent work can be listed
and counted.
"""

from pathlib import Path
from urllib.parse import urlencode

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from fuel_predictor.main import create_app

_ADMIN = ("admin", "kata-sandi-admin-1")


def _csrf(html: str) -> str:
    marker = 'name="csrf_token" value="'
    start = html.index(marker) + len(marker)
    return html[start : html.index('"', start)]


def _signed_in(tmp_path: Path) -> TestClient:
    client = TestClient(
        create_app(database_path=tmp_path / "operations.sqlite3", bootstrap_administrator=_ADMIN)
    )
    client.__enter__()
    page = client.get("/masuk")
    client.post(
        "/masuk",
        data={"username": _ADMIN[0], "password": _ADMIN[1], "csrf_token": _csrf(page.text)},
        follow_redirects=False,
    )
    return client


def test_an_operation_and_its_actual_record_name_the_person(tmp_path: Path) -> None:
    client = _signed_in(tmp_path)
    try:
        token = _csrf(client.get("/prediksi").text)
        saved = client.post(
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
        # The page names the operation by the code people write down.
        code = saved.text.split('class="operation-code">', 1)[1].split("<", 1)[0]
        recorded = client.post(
            f"/api/v1/daily-operations/{code}/actual-fuel",
            json={"actual_fuel_liters": 25, "measurement_source": "fuel_meter"},
        )
    finally:
        client.__exit__(None, None, None)

    assert saved.status_code == 200, saved.text
    assert recorded.status_code == 201, recorded.text
    url = f"sqlite+pysqlite:///{(tmp_path / 'operations.sqlite3').as_posix()}"
    with create_engine(url).connect() as db:
        operation = db.execute(
            text(
                "SELECT operation_id, created_by, created_at FROM daily_operations "
                "WHERE operation_code = :code"
            ),
            {"code": code},
        ).one()
        actual = db.execute(
            text("SELECT recorded_by FROM actual_fuel_records WHERE operation_id = :id"),
            {"id": operation.operation_id},
        ).one()
    assert operation.created_by == "admin"
    assert operation.created_at is not None
    assert actual.recorded_by == "admin"

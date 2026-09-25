"""A mistaken or duplicate operation can be cancelled, with a reason.

A double submission, or a plan that never ran, stayed "waiting for actual
fuel" for good: on the waiting list, counted as overdue by monitoring. It can
now be cancelled - by whoever plans, with the reason written down - as long as
no actual fuel was recorded for it. A cancelled operation leaves the waiting
list and the overdue count, refuses actual fuel, and says so in the history.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from fuel_predictor.delivery.security import ROUTE_CAPABILITIES
from fuel_predictor.domain.identity import Capability
from fuel_predictor.main import create_app
from tests.test_actual_fuel_outcomes import _operation_with_prediction, _train_baseline


def _csrf(html: str) -> str:
    marker = 'name="csrf_token" value="'
    start = html.index(marker) + len(marker)
    return html[start : html.index('"', start)]


def _cancel(client: TestClient, operation_id: str, reason: str) -> str:
    page = client.get(f"/operasi-harian/{operation_id}").text
    response = client.post(
        f"/operasi-harian/{operation_id}/batalkan",
        data={"reason": reason, "csrf_token": _csrf(page)},
    )
    return f"{response.status_code}\n{response.text}"


def test_a_cancelled_operation_leaves_the_waiting_list_and_says_why(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_baseline(client)
        operation = _operation_with_prediction(client, 24)["operation"]
        code = operation["operation_code"]

        outcome = _cancel(client, operation["operation_id"], "Tertekan dua kali")
        waiting = client.get("/bahan-bakar-aktual").text
        history = client.get("/riwayat-prediksi").text
        page = client.get(f"/operasi-harian/{operation['operation_id']}").text
        audit = client.get("/audit").text

    assert outcome.startswith("200"), outcome
    assert f'operation_id={code}"' not in waiting
    assert "Dibatalkan" in history
    assert "Operasi dibatalkan" in page and "Tertekan dua kali" in page
    # The page stops asking for what no longer applies.
    assert "catat kode ini" not in page and "dibatalkan, jangan dipakai" in page
    assert "Setelah operasi selesai, catat bahan bakar aktualnya" not in page
    assert "Tertekan dua kali" in audit


def test_a_cancelled_operation_refuses_actual_fuel(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_baseline(client)
        operation = _operation_with_prediction(client, 24)["operation"]
        _cancel(client, operation["operation_id"], "Tidak jadi berangkat")

        recorded = client.post(
            f"/api/v1/daily-operations/{operation['operation_code']}/actual-fuel",
            json={"actual_fuel_liters": 20, "measurement_source": "fuel_meter"},
        )

    assert recorded.status_code == 409
    assert "dibatalkan" in recorded.text


def test_an_operation_with_actual_fuel_cannot_be_cancelled(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_baseline(client)
        operation = _operation_with_prediction(client, 24)["operation"]
        client.post(
            f"/api/v1/daily-operations/{operation['operation_id']}/actual-fuel",
            json={"actual_fuel_liters": 20, "measurement_source": "fuel_meter"},
        )

        outcome = _cancel(client, operation["operation_id"], "Salah input")

    assert outcome.startswith("409"), outcome
    assert "sudah punya BBM aktual" in outcome


def test_a_reason_is_required(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_baseline(client)
        operation = _operation_with_prediction(client, 24)["operation"]

        outcome = _cancel(client, operation["operation_id"], "  ")
        waiting = client.get("/bahan-bakar-aktual").text

    assert outcome.startswith("422"), outcome
    assert operation["operation_code"] in waiting


def test_whoever_plans_may_cancel() -> None:
    assert (
        "POST",
        "/operasi-harian/*/batalkan",
        Capability.CREATE_PREDICTION,
    ) in ROUTE_CAPABILITIES

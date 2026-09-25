"""No page an operator reaches offers a link the operator may not open.

Twice a page linked every user to the model performance page, which an
operator is refused - once on Catat Aktual, once on the page after saving
actual fuel. This walks an operator's whole day, the pages a POST answers
with included, and checks every link on every page against the guard's own
rule.
"""

import re
from pathlib import Path

from fastapi.testclient import TestClient

from fuel_predictor.application.identity import ActiveCaller
from fuel_predictor.delivery.security import may_open
from fuel_predictor.domain.identity import UserRole
from fuel_predictor.main import create_app
from tests.test_two_roles import (
    _ADMIN,
    _OPERATOR,
    _csrf,
    _sign_in,
    _sign_out,
    _train_baseline_with_csrf,
)

_LINK = re.compile(r'href="(/[^"#]*)"')


class _Operator:
    """Enough of a signed-in operator for `may_open`."""

    def allows(self, capability: object) -> bool:
        from fuel_predictor.domain.identity import role_allows

        return role_allows(UserRole.OPERATOR, capability)  # type: ignore[arg-type]


def _dead_links(page: str) -> set[str]:
    operator: ActiveCaller = _Operator()  # type: ignore[assignment]
    return {
        link
        for link in _LINK.findall(page)
        if not link.startswith("/statis/") and not may_open(operator, link)
    }


def test_an_operator_s_day_offers_only_links_they_may_open(tmp_path: Path) -> None:
    database = tmp_path / "operations.sqlite3"
    pages: dict[str, str] = {}
    with TestClient(create_app(database_path=database, bootstrap_administrator=_ADMIN)) as client:
        _sign_in(client, *_ADMIN)
        client.post(
            "/api/v1/users",
            json={
                "username": _OPERATOR[0],
                "full_name": "Andi",
                "password": _OPERATOR[1],
                "role": "operator",
            },
        )
        _train_baseline_with_csrf(client)
        _sign_out(client)
        _sign_in(client, *_OPERATOR)
        token = _csrf(client.get("/prediksi").text)

        for path in (
            "/",
            "/prediksi",
            "/riwayat-prediksi",
            "/armada",
            "/bahan-bakar-aktual",
            "/bahan-bakar-aktual-massal",
            "/prediksi-operasi-massal",
            "/akun",
            "/agen-saya",
        ):
            pages[path] = client.get(path).text
        planned = client.post(
            "/operasi-harian",
            data={
                "vehicle_category": "ANGBER",
                "activity_mode": "transport",
                "total_distance_km": "40",
                "distance_source": "manual",
                "csrf_token": token,
            },
        )
        pages["estimate after saving"] = planned.text
        code = re.search(r'class="operation-code">([^<]+)<', planned.text)
        assert code is not None
        pages["estimate reopened"] = client.get(f"/operasi-harian/{code.group(1)}").text
        pages["slip"] = client.get(f"/operasi-harian/{code.group(1)}/slip").text
        pages["actual saved"] = client.post(
            "/bahan-bakar-aktual",
            data={
                "operation_id": code.group(1),
                "actual_fuel_liters": "25",
                "measurement_source": "fuel_meter",
                "csrf_token": token,
            },
        ).text
        pages["bulk plan result"] = client.post(
            "/prediksi-operasi-massal",
            data={"csrf_token": token},
            files={
                "file": (
                    "rencana.csv",
                    b"Aktivitas (wajib),Jarak Total (km) (wajib)\n"
                    b"Mobilisasi,30\nMobilisasi,bukan angka\n",
                    "text/csv",
                )
            },
        ).text
        pages["bulk actual result"] = client.post(
            "/bahan-bakar-aktual-massal",
            data={"csrf_token": token},
            files={
                "file": (
                    "aktual.csv",
                    b"Kode Operasi (wajib),Bahan Bakar Aktual (L) (wajib)\nTIDAK-ADA,5\n",
                    "text/csv",
                )
            },
        ).text
        pages["history"] = client.get("/riwayat-prediksi").text

    dead = {name: links for name, page in pages.items() if (links := _dead_links(page))}
    assert dead == {}

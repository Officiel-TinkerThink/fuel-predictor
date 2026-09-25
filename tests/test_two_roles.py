"""Two roles: an operator plans and reports, an administrator does everything.

The plan's third role, manager, sat between the two with one extra menu
(Catatan Audit) and nothing else to justify a separate account type. It is
gone; accounts that held it become operators, the narrower of the two,
and an administrator can promote any of them.

An operator's whole job is on two menus - Operasi Harian and BBM Aktual -
and the overview shows them only that part. Monitoring, models and every
settings page answer 403, and so does the OAuth consent screen, since an
agent connected there would act with the operator's own access.
"""

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from fuel_predictor.delivery.rendering import NAVIGATION
from fuel_predictor.domain.identity import Capability, UserRole, capabilities_for
from fuel_predictor.main import create_app

_ADMIN = ("admin", "kata-sandi-admin-1")
_OPERATOR = ("andi", "kata-sandi-andi-01")


def _csrf(html: str) -> str:
    marker = 'name="csrf_token" value="'
    start = html.index(marker) + len(marker)
    return html[start : html.index('"', start)]


def _sign_in(client: TestClient, username: str, password: str) -> None:
    page = client.get("/masuk")
    client.post(
        "/masuk",
        data={"username": username, "password": password, "csrf_token": _csrf(page.text)},
        follow_redirects=False,
    )


def _sign_out(client: TestClient) -> None:
    client.post("/keluar", data={"csrf_token": _csrf(client.get("/").text)}, follow_redirects=False)


@pytest.fixture
def operator_client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(database_path=tmp_path / "operations.sqlite3", bootstrap_administrator=_ADMIN)
    with TestClient(app) as client:
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
        _sign_out(client)
        _sign_in(client, *_OPERATOR)
        yield client


def test_there_are_exactly_two_roles() -> None:
    assert {role.value for role in UserRole} == {"operator", "administrator"}


def test_an_operator_plans_and_reports_and_nothing_else() -> None:
    assert capabilities_for(UserRole.OPERATOR) == frozenset(
        {
            Capability.CREATE_PREDICTION,
            Capability.IMPORT_OPERATIONS,
            Capability.RECORD_ACTUAL_FUEL,
            Capability.MANAGE_OWN_ACCOUNT,
        }
    )
    assert capabilities_for(UserRole.ADMINISTRATOR) == frozenset(Capability)


def test_an_operators_menu_is_the_two_daily_groups(operator_client: TestClient) -> None:
    page = operator_client.get("/prediksi").text

    assert "Buat Prediksi" in page and "Catat Aktual" in page and "Riwayat Prediksi" in page
    for hidden in ("Pemantauan", "Pengelolaan Model", "Pengaturan", "Agen Saya", "Pengguna"):
        assert f">{hidden}<" not in page
    # The sidebar still offers the one account action everyone has.
    assert 'href="/akun"' in page


def test_pages_outside_the_operators_job_are_refused(operator_client: TestClient) -> None:
    refused = [
        "/pemantauan/kesehatan-sistem",
        "/pemantauan/kinerja-model",
        "/pengelolaan-model",
        "/impor-data-historis",
        "/agen-saya",
        "/integrasi-agen",
        "/pengguna",
        "/audit",
    ]
    for path in refused:
        assert operator_client.get(path).status_code == 403, path
    for path in (
        "/",
        "/prediksi",
        "/prediksi-operasi-massal",
        "/riwayat-prediksi",
        "/bahan-bakar-aktual",
        "/bahan-bakar-aktual-massal",
        "/akun",
    ):
        assert operator_client.get(path).status_code == 200, path


def test_the_overview_shows_an_operator_only_their_part(operator_client: TestClient) -> None:
    page = operator_client.get("/").text

    # Their two jobs: plan, and report what was used.
    main = page.split("<main ", 1)[1]
    assert 'href="/prediksi"' in main and "Buat prediksi" in main
    assert "Menunggu BBM aktual" in main
    for admin_only in (
        "Model aktif",
        "Pergeseran data",
        "Rekomendasi model",
        "Siapkan model pertama",
    ):
        assert admin_only not in page


def test_an_operator_cannot_connect_an_agent_through_consent(operator_client: TestClient) -> None:
    registration = operator_client.post(
        "/oauth/register",
        json={"client_name": "Claude Code", "redirect_uris": ["http://127.0.0.1:52341/callback"]},
    ).json()
    page = operator_client.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": registration["client_id"],
            "redirect_uri": "http://127.0.0.1:52341/callback",
            "code_challenge": "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
            "code_challenge_method": "S256",
            "scope": "fuel:predict",
            "resource": "http://testserver/mcp",
        },
    )

    assert page.status_code == 403
    assert "administrator" in page.text.lower()


def test_every_navigation_group_an_operator_cannot_open_is_absent_from_navigation_for_them() -> (
    None
):
    operator = capabilities_for(UserRole.OPERATOR)
    for group in NAVIGATION:
        if group.title in ("Pemantauan", "Model", "Pengaturan"):
            assert all(item.capability not in operator for item in group.items), group.title


def test_a_manager_account_left_by_an_older_version_becomes_an_operator(tmp_path: Path) -> None:
    """The migration rewrites the role; the app must then treat the account as an operator."""
    database = tmp_path / "operations.sqlite3"
    app = create_app(database_path=database, bootstrap_administrator=_ADMIN)
    with TestClient(app) as client:
        _sign_in(client, *_ADMIN)
        client.post(
            "/api/v1/users",
            json={
                "username": "budi",
                "full_name": "Budi",
                "password": "kata-sandi-budi-01",
                "role": "operator",
            },
        )
    with create_engine(f"sqlite+pysqlite:///{database.as_posix()}").begin() as connection:
        connection.execute(text("UPDATE users SET role = 'manager' WHERE username = 'budi'"))
        # What the migration does, applied to this test schema.
        connection.execute(text("UPDATE users SET role = 'operator' WHERE role = 'manager'"))
    with TestClient(create_app(database_path=database, bootstrap_administrator=_ADMIN)) as client:
        _sign_in(client, "budi", "kata-sandi-budi-01")
        assert client.get("/prediksi").status_code == 200
        assert client.get("/audit").status_code == 403


def test_the_overview_lists_an_operators_operations_waiting_for_actual_fuel(
    operator_client: TestClient, tmp_path: Path
) -> None:
    # The administrator trains a model; the operator predicts and comes back later.
    with TestClient(
        create_app(database_path=tmp_path / "operations.sqlite3", bootstrap_administrator=_ADMIN)
    ) as admin:
        _sign_in(admin, *_ADMIN)
        _train_baseline_with_csrf(admin)
    page = operator_client.get("/prediksi")
    token = _csrf(page.text)
    operator_client.post(
        "/operasi-harian",
        data={
            "vehicle_category": "ANGBER",
            "activity_mode": "transport",
            "total_distance_km": "40",
            "distance_source": "manual",
            "csrf_token": token,
        },
    )

    overview = operator_client.get("/").text

    assert "Menunggu BBM aktual" in overview
    # Offered by the code the operator wrote down (ADR 0016).
    assert re.search(r'href="/bahan-bakar-aktual\?operation_id=\d{6}-\d{4}', overview)
    assert "HARI INI" in overview


def _train_baseline_with_csrf(admin: TestClient) -> None:
    """Like tests.test_actual_fuel_outcomes._train_baseline, for a provisioned
    system: a signed-in administrator's uploads carry the CSRF token."""
    token = _csrf(admin.get("/prediksi").text)
    history = (
        "Kategori ANGBER,Mode Aktivitas,Jam Lifting,Jarak Total (km),"
        "Bahan Bakar Disiapkan (L),Sumber Jarak\n"
        "ANGBER,transport,,20,18,manual\n"
        "ANGBER,transport,,40,28,manual\n"
        "ANGBER,lifting,2,20,25,manual\n"
    )
    dataset = admin.post(
        "/api/v1/historical-datasets",
        files={"file": ("riwayat.csv", history.encode(), "text/csv")},
        data={"csrf_token": token},
    ).json()["dataset_version"]
    candidate = admin.post(
        f"/api/v1/dataset-versions/{dataset['dataset_version_id']}/baseline-candidates"
    ).json()
    promoted = admin.post(f"/api/v1/model-candidates/{candidate['model_version_id']}/promote")
    assert promoted.status_code == 200, promoted.text


def test_the_overview_counts_the_whole_backlog_and_says_when_nothing_waits(
    operator_client: TestClient, tmp_path: Path
) -> None:
    """The count on the overview was the length of a list cut at eight, so a
    backlog of twenty read as eight; and with nothing waiting the section
    vanished instead of saying all was recorded."""
    nothing_yet = operator_client.get("/").text
    with TestClient(
        create_app(database_path=tmp_path / "operations.sqlite3", bootstrap_administrator=_ADMIN)
    ) as admin:
        _sign_in(admin, *_ADMIN)
        _train_baseline_with_csrf(admin)
    token = _csrf(operator_client.get("/prediksi").text)
    for distance in range(20, 29):
        operator_client.post(
            "/operasi-harian",
            data={
                "vehicle_category": "ANGBER",
                "activity_mode": "transport",
                "total_distance_km": str(distance),
                "distance_source": "manual",
                "csrf_token": token,
            },
        )

    overview = operator_client.get("/").text

    assert "Tidak ada yang menunggu" in nothing_yet
    assert "9 operasi sudah diprediksi" in overview
    # Only the newest few are listed on the overview itself.
    assert overview.count('href="/bahan-bakar-aktual?operation_id=') == 4


def test_an_operator_is_not_offered_a_link_that_would_be_refused(
    operator_client: TestClient, tmp_path: Path
) -> None:
    """Catat Aktual linked every user to the model performance page, which an
    operator may not open; the link now follows the guard's own rule."""
    for_operator = operator_client.get("/bahan-bakar-aktual").text
    with TestClient(
        create_app(database_path=tmp_path / "operations.sqlite3", bootstrap_administrator=_ADMIN)
    ) as admin:
        _sign_in(admin, *_ADMIN)
        for_admin = admin.get("/bahan-bakar-aktual").text

    assert operator_client.get("/pemantauan/kinerja-model").status_code == 403
    assert 'href="/pemantauan/kinerja-model"' not in for_operator
    assert 'href="/pemantauan/kinerja-model"' in for_admin


def test_the_operator_s_overview_does_not_compute_the_administrator_s_figures(
    operator_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-scoring every actual for figures an operator is never shown made
    their overview take seconds after each restart."""
    from fuel_predictor.application.model_lifecycle import GetModelGovernanceDashboard
    from fuel_predictor.application.monitoring import GetMonitoringDashboard

    def not_for_operators(*_args: object) -> None:
        raise AssertionError("computed for an operator")

    monkeypatch.setattr(GetModelGovernanceDashboard, "execute", not_for_operators)
    monkeypatch.setattr(GetMonitoringDashboard, "execute", not_for_operators)

    assert operator_client.get("/").status_code == 200

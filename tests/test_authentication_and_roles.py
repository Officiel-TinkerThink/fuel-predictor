from pathlib import Path

from fastapi.testclient import TestClient

from fuel_predictor.main import create_app

_ADMIN = ("admin", "kata-sandi-admin-1")


def _app(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(
            database_path=tmp_path / "operations.sqlite3",
            bootstrap_administrator=_ADMIN,
        )
    )


def _sign_in(client: TestClient, username: str, password: str) -> object:
    page = client.get("/masuk")
    token = _csrf_token(page.text)
    return client.post(
        "/masuk",
        data={"username": username, "password": password, "csrf_token": token},
        follow_redirects=False,
    )


def _csrf_token(html: str) -> str:
    marker = 'name="csrf_token" value="'
    start = html.index(marker) + len(marker)
    return html[start : html.index('"', start)]


def test_protected_pages_require_a_session_and_say_so_in_indonesian(tmp_path: Path) -> None:
    with _app(tmp_path) as client:
        page = client.get("/", follow_redirects=False)
        api = client.get("/api/v1/monitoring-dashboard")

    assert page.status_code == 303
    assert page.headers["location"] == "/masuk?tujuan=%2F"
    assert api.status_code == 401
    assert "masuk" in api.json()["error"]["message"].lower()


def test_correct_credentials_start_an_http_only_session(tmp_path: Path) -> None:
    with _app(tmp_path) as client:
        response = _sign_in(client, *_ADMIN)
        cookie = response.headers.get("set-cookie", "")
        dashboard = client.get("/")

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert "httponly" in cookie.lower()
    assert "samesite=lax" in cookie.lower()
    assert dashboard.status_code == 200


def test_wrong_password_is_rejected_without_starting_a_session(tmp_path: Path) -> None:
    with _app(tmp_path) as client:
        response = _sign_in(client, "admin", "kata-sandi-salah")
        dashboard = client.get("/", follow_redirects=False)

    assert response.status_code == 401
    assert "tidak cocok" in response.text.lower()
    assert dashboard.status_code == 303


def test_form_submission_without_a_csrf_token_is_rejected(tmp_path: Path) -> None:
    with _app(tmp_path) as client:
        _sign_in(client, *_ADMIN)
        response = client.post(
            "/operasi-harian",
            data={
                "vehicle_category": "ANGBER",
                "activity_mode": "transport",
                "total_distance_km": "20",
                "distance_source": "manual",
            },
        )

    assert response.status_code == 403
    assert "sesi" in response.text.lower()


def test_operator_cannot_reach_administrator_only_actions(tmp_path: Path) -> None:
    with _app(tmp_path) as client:
        _sign_in(client, *_ADMIN)
        created = client.post(
            "/api/v1/users",
            json={
                "username": "operator1",
                "full_name": "Operator Satu",
                "password": "kata-sandi-operator-1",
                "role": "operator",
            },
        )
        client.post("/keluar", data={"csrf_token": _csrf_token(client.get("/").text)})
        _sign_in(client, "operator1", "kata-sandi-operator-1")
        promotion = client.post("/api/v1/model-candidates/MDL-unknown/promote")
        user_list = client.get("/api/v1/users")
        prediction_page = client.get("/prediksi")

    assert created.status_code == 201
    assert promotion.status_code == 403
    assert user_list.status_code == 403
    assert prediction_page.status_code == 200


def test_signing_out_ends_the_session_immediately(tmp_path: Path) -> None:
    with _app(tmp_path) as client:
        _sign_in(client, *_ADMIN)
        signed_out = client.post(
            "/keluar",
            data={"csrf_token": _csrf_token(client.get("/").text)},
            follow_redirects=False,
        )
        after = client.get("/", follow_redirects=False)

    assert signed_out.status_code == 303
    assert after.status_code == 303


def test_authentication_and_privileged_actions_are_audited(tmp_path: Path) -> None:
    with _app(tmp_path) as client:
        _sign_in(client, "admin", "kata-sandi-salah")
        _sign_in(client, *_ADMIN)
        client.post(
            "/api/v1/users",
            json={
                "username": "manajer1",
                "full_name": "Manajer Satu",
                "password": "kata-sandi-manajer-1",
                "role": "manager",
            },
        )
        audit = client.get("/api/v1/audit-records")

    assert audit.status_code == 200
    actions = [record["action"] for record in audit.json()["records"]]
    assert "sign_in_failed" in actions
    assert "sign_in_succeeded" in actions
    assert "user_created" in actions
    for record in audit.json()["records"]:
        assert record["occurred_at"]
        assert "outcome" in record


def test_legacy_form_pages_carry_a_working_csrf_token_once_provisioned(tmp_path: Path) -> None:
    """Regression test: the original f-string-rendered forms (form.py) never
    included a csrf_token field. Once a system is provisioned (an admin
    exists), the session middleware enforces CSRF on every form POST, so
    without this fix every one of those forms became permanently unusable.
    """
    with _app(tmp_path) as client:
        _sign_in(client, *_ADMIN)
        page = client.get("/prediksi")
        token = _csrf_token(page.text)

        with_token = client.post(
            "/operasi-harian",
            data={
                "vehicle_category": "ANGBER",
                "activity_mode": "transport",
                "total_distance_km": "20",
                "distance_source": "manual",
                "csrf_token": token,
            },
        )
        without_token = client.post(
            "/operasi-harian",
            data={
                "vehicle_category": "ANGBER",
                "activity_mode": "transport",
                "total_distance_km": "20",
                "distance_source": "manual",
            },
        )

    assert with_token.status_code == 201
    assert without_token.status_code == 403

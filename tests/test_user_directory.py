"""Pengguna is a directory an administrator can run the team from.

The page was a bare table with three buttons per row and a form underneath.
It is now a directory: a count of who is active, a search box, one card per
person showing when they last signed in and how much they planned and
reported lately, "Tambah pengguna" as a dialog rather than a permanent form,
and a page per person - profile (name, email, role, editable), the account
actions, activity figures, their recent operations and their audit trail.
An administrator may change anyone's role except their own: demoting the
account you are signed in with is how a system ends up with no administrator.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from fuel_predictor.main import create_app
from tests.test_two_roles import _train_baseline_with_csrf

_ADMIN = ("admin", "kata-sandi-admin-1")


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


def _admin(tmp_path: Path) -> TestClient:
    client = TestClient(
        create_app(database_path=tmp_path / "operations.sqlite3", bootstrap_administrator=_ADMIN)
    )
    client.__enter__()
    _sign_in(client, *_ADMIN)
    return client


def _add_budi(client: TestClient) -> str:
    client.post(
        "/api/v1/users",
        json={
            "username": "budi",
            "full_name": "Budi Santoso",
            "email": "budi@example.com",
            "password": "kata-sandi-budi-01",
            "role": "operator",
        },
    )
    users = client.get("/api/v1/users").json()["users"]
    user_id: str = next(user["user_id"] for user in users if user["username"] == "budi")
    return user_id


def _budi_plans_one(client: TestClient) -> str:
    """Signed in as Budi: plan one operation and report its actual fuel."""
    _sign_out(client)
    _sign_in(client, "budi", "kata-sandi-budi-01")
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
    operation_id: str = saved.text.split("<dt>ID operasi</dt><dd><strong>", 1)[1].split(
        "</strong>"
    )[0]
    client.post(
        f"/api/v1/daily-operations/{operation_id}/actual-fuel",
        json={"actual_fuel_liters": 25, "measurement_source": "fuel_meter"},
    )
    _sign_out(client)
    _sign_in(client, *_ADMIN)
    return operation_id


def test_the_directory_shows_who_is_active_and_what_they_did_lately(tmp_path: Path) -> None:
    client = _admin(tmp_path)
    try:
        _train_baseline_with_csrf(client)
        user_id = _add_budi(client)
        _budi_plans_one(client)
        page = client.get("/pengguna").text
    finally:
        client.__exit__(None, None, None)

    assert "2 pengguna" in page and "2 aktif" in page
    assert 'name="cari"' in page and 'name="status"' in page
    assert f'href="/pengguna/{user_id}"' in page
    # Budi's card: signed in just now, planned one, reported one.
    budi = page[
        page.index('data-user="budi"') : page.index("</li>", page.index('data-user="budi"'))
    ]
    assert "Terakhir masuk" in budi and "Belum pernah masuk" not in budi
    assert "1 prediksi" in budi and "1 aktual" in budi
    # Adding is a dialog, not a permanent form.
    assert 'data-dialog="tambah-pengguna"' in page


def test_a_persons_page_shows_profile_activity_operations_and_trail(tmp_path: Path) -> None:
    client = _admin(tmp_path)
    try:
        _train_baseline_with_csrf(client)
        user_id = _add_budi(client)
        operation_id = _budi_plans_one(client)
        page = client.get(f"/pengguna/{user_id}").text
        missing = client.get("/pengguna/USR-tidak-ada")
    finally:
        client.__exit__(None, None, None)

    assert "Budi Santoso" in page and "budi@example.com" in page
    assert 'name="full_name"' in page and 'name="email"' in page and 'name="role"' in page
    assert "Atur ulang kata sandi" in page and "Nonaktifkan" in page
    assert f'href="/operasi-harian/{operation_id}"' in page
    assert "Pengguna dibuat" in page  # the audit trail, in words
    assert "Operasi direncanakan" in page and "BBM aktual dicatat" in page
    assert missing.status_code == 404


def test_an_administrator_edits_name_email_and_role_but_not_their_own_role(
    tmp_path: Path,
) -> None:
    client = _admin(tmp_path)
    try:
        user_id = _add_budi(client)
        token = _csrf(client.get(f"/pengguna/{user_id}").text)
        edited = client.post(
            f"/pengguna/{user_id}/profil",
            data={
                "full_name": "Budi S.",
                "email": "Budi.S@Example.com",
                "role": "administrator",
                "csrf_token": token,
            },
            follow_redirects=False,
        )
        after = client.get(f"/pengguna/{user_id}").text
        users = client.get("/api/v1/users").json()["users"]
        me = next(user for user in users if user["username"] == "admin")
        demote_self = client.post(
            f"/pengguna/{me['user_id']}/profil",
            data={
                "full_name": "Administrator",
                "email": "",
                "role": "operator",
                "csrf_token": token,
            },
        )
        still_admin = client.get("/pengguna").status_code
    finally:
        client.__exit__(None, None, None)

    assert edited.status_code == 303, edited.text
    assert "Budi S." in after and "budi.s@example.com" in after
    budi = next(user for user in users if user["username"] == "budi")
    assert budi["role"] == "administrator"
    assert demote_self.status_code == 422
    assert "peran Anda sendiri" in demote_self.text
    assert still_admin == 200


def test_activity_counts_only_the_last_thirty_days(tmp_path: Path) -> None:
    client = _admin(tmp_path)
    try:
        _train_baseline_with_csrf(client)
        user_id = _add_budi(client)
        operation_id = _budi_plans_one(client)
        with create_engine(
            f"sqlite+pysqlite:///{(tmp_path / 'operations.sqlite3').as_posix()}"
        ).begin() as db:
            db.execute(
                text("UPDATE daily_operations SET created_at = :at WHERE operation_id = :id"),
                {"at": datetime.now(UTC) - timedelta(days=40), "id": operation_id},
            )
        page = client.get(f"/pengguna/{user_id}").text
    finally:
        client.__exit__(None, None, None)

    # Total still one; the 30-day figure is zero.
    assert "30 hari terakhir" in page
    assert 'data-stat="operations-30d">0<' in page
    assert 'data-stat="operations-total">1<' in page

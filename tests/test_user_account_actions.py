"""An administrator can reset a password and switch an account off; anyone can
change their own password.

Both use cases (ChangePassword, SetUserActivation) existed in the application
layer and were wired to nothing: the sign-in page said "hubungi administrator"
for a forgotten password and the administrator had no button to press. The
Pengguna page now offers both per account, and every signed-in user has a
Kata Sandi page that asks for the current password before accepting a new one.
"""

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from fuel_predictor.main import create_app

_ADMIN = ("admin", "kata-sandi-admin-1")


def _csrf(html: str) -> str:
    marker = 'name="csrf_token" value="'
    start = html.index(marker) + len(marker)
    return html[start : html.index('"', start)]


def _sign_in(client: TestClient, username: str, password: str) -> Any:
    page = client.get("/masuk")
    return client.post(
        "/masuk",
        data={"username": username, "password": password, "csrf_token": _csrf(page.text)},
        follow_redirects=False,
    )


def _app(tmp_path: Path) -> Any:
    return create_app(database_path=tmp_path / "operations.sqlite3", bootstrap_administrator=_ADMIN)


def _create_operator(client: TestClient) -> str:
    token = _csrf(client.get("/pengguna").text)
    client.post(
        "/pengguna",
        data={
            "username": "budi",
            "full_name": "Budi",
            "password": "kata-sandi-budi-1",
            "role": "operator",
            "csrf_token": token,
        },
    )
    return _user_id(client.get("/pengguna").text, "budi")


def _user_id(page: str, username: str) -> str:
    """The data-user-id of the directory row that lists this username."""
    row = page.index(f'data-user="{username}"')
    start = page.index('data-user-id="', row) + len('data-user-id="')
    return page[start : page.index('"', start)]


def test_an_administrator_can_reset_someone_elses_password(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as admin, TestClient(_app(tmp_path)) as budi:
        _sign_in(admin, *_ADMIN)
        user_id = _create_operator(admin)

        reset = admin.post(
            f"/pengguna/{user_id}/kata-sandi",
            data={
                "password": "kata-sandi-baru-99",
                "csrf_token": _csrf(admin.get("/pengguna").text),
            },
            follow_redirects=False,
        )
        old = _sign_in(budi, "budi", "kata-sandi-budi-1")
        new = _sign_in(budi, "budi", "kata-sandi-baru-99")

    assert reset.status_code == 303, reset.text
    assert old.status_code == 401
    assert new.status_code == 303


def test_a_deactivated_account_cannot_sign_in_and_can_be_switched_back_on(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as admin, TestClient(_app(tmp_path)) as budi:
        _sign_in(admin, *_ADMIN)
        user_id = _create_operator(admin)
        token = _csrf(admin.get("/pengguna").text)

        off = admin.post(
            f"/pengguna/{user_id}/status",
            data={"is_active": "false", "csrf_token": token},
            follow_redirects=False,
        )
        while_off = _sign_in(budi, "budi", "kata-sandi-budi-1")
        on = admin.post(
            f"/pengguna/{user_id}/status",
            data={"is_active": "true", "csrf_token": token},
            follow_redirects=False,
        )
        while_on = _sign_in(budi, "budi", "kata-sandi-budi-1")

    assert off.status_code == 303 and on.status_code == 303
    assert while_off.status_code == 401
    assert while_on.status_code == 303


def test_an_administrator_cannot_switch_off_their_own_account(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as admin:
        _sign_in(admin, *_ADMIN)
        page = admin.get("/pengguna").text
        own_id = page[page.index('data-user-id="') + len('data-user-id="') :]
        own_id = own_id[: own_id.index('"')]

        response = admin.post(
            f"/pengguna/{own_id}/status",
            data={"is_active": "false", "csrf_token": _csrf(page)},
        )

    assert response.status_code == 422
    assert "akun Anda sendiri" in response.text


def test_a_user_changes_their_own_password_with_the_current_one(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        _sign_in(client, *_ADMIN)
        form = client.get("/akun")
        token = _csrf(form.text)

        wrong = client.post(
            "/akun",
            data={
                "current_password": "bukan-kata-sandinya",
                "new_password": "kata-sandi-baru-99",
                "confirm_password": "kata-sandi-baru-99",
                "csrf_token": token,
            },
        )
        right = client.post(
            "/akun",
            data={
                "current_password": _ADMIN[1],
                "new_password": "kata-sandi-baru-99",
                "confirm_password": "kata-sandi-baru-99",
                "csrf_token": token,
            },
            follow_redirects=False,
        )
        after = client.get("/", follow_redirects=False)
        signed_in_again = _sign_in(client, _ADMIN[0], "kata-sandi-baru-99")

    assert form.status_code == 200
    assert wrong.status_code == 422
    assert "Kata sandi saat ini salah" in wrong.text
    assert right.status_code == 303
    # Every session ends with the old password; the sign-in page says why.
    assert after.status_code == 303 and after.headers["location"].startswith("/masuk")
    assert signed_in_again.status_code == 303


def test_a_new_password_has_to_be_typed_twice_and_has_to_be_new(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        _sign_in(client, *_ADMIN)
        token = _csrf(client.get("/akun").text)

        mistyped = client.post(
            "/akun",
            data={
                "current_password": _ADMIN[1],
                "new_password": "kata-sandi-baru-99",
                "confirm_password": "kata-sandi-baru-98",
                "csrf_token": token,
            },
        )
        unchanged = client.post(
            "/akun",
            data={
                "current_password": _ADMIN[1],
                "new_password": _ADMIN[1],
                "confirm_password": _ADMIN[1],
                "csrf_token": token,
            },
        )
        # Neither attempt may have taken: the old password still signs in.
        client.post("/keluar", data={"csrf_token": token}, follow_redirects=False)
        still_works = _sign_in(client, *_ADMIN)

    assert mistyped.status_code == 422
    assert "Ulangi kata sandi baru yang sama." in mistyped.text
    assert unchanged.status_code == 422
    assert "harus berbeda dari kata sandi saat ini" in unchanged.text
    assert still_works.status_code == 303


def test_the_sidebar_links_to_the_account_page(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        _sign_in(client, *_ADMIN)
        page = client.get("/")

    assert 'href="/akun"' in page.text

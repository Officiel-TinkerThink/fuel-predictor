"""An account has a username, a name, an optional email, and a password; a
person signs in with the username or the email.

The form used to ask for "nama pengguna, nama lengkap, kata sandi awal" and
nothing else, and sign-in accepted the username only. Email is what people
actually remember, so it is stored (normalised, unique when present) and
either identifier opens the door. It stays optional: an account for a
shared desk or a service has no address to give.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from fuel_predictor.main import create_app

_ADMIN = ("admin", "kata-sandi-admin-1")


def _csrf(html: str) -> str:
    marker = 'name="csrf_token" value="'
    start = html.index(marker) + len(marker)
    return html[start : html.index('"', start)]


def _sign_in(client: TestClient, identifier: str, password: str) -> int:
    page = client.get("/masuk")
    response = client.post(
        "/masuk",
        data={"username": identifier, "password": password, "csrf_token": _csrf(page.text)},
        follow_redirects=False,
    )
    status: int = response.status_code
    return status


def _sign_out(client: TestClient) -> None:
    client.post("/keluar", data={"csrf_token": _csrf(client.get("/").text)}, follow_redirects=False)


def _admin(tmp_path: Path) -> TestClient:
    client = TestClient(
        create_app(database_path=tmp_path / "operations.sqlite3", bootstrap_administrator=_ADMIN)
    )
    client.__enter__()
    _sign_in(client, *_ADMIN)
    return client


def _create(client: TestClient, **fields: str) -> int:
    page = client.get("/pengguna")
    data = {
        "username": "budi",
        "full_name": "Budi Santoso",
        "email": "",
        "password": "kata-sandi-budi-01",
        "role": "operator",
        "csrf_token": _csrf(page.text),
    }
    data.update(fields)
    status: int = client.post("/pengguna", data=data, follow_redirects=False).status_code
    return status


def test_the_form_asks_for_username_name_optional_email_and_password(tmp_path: Path) -> None:
    client = _admin(tmp_path)
    try:
        page = client.get("/pengguna").text
    finally:
        client.__exit__(None, None, None)

    assert 'name="username"' in page and 'name="full_name"' in page
    assert 'name="email"' in page and 'type="email"' in page
    assert 'name="password"' in page
    # Email is the one optional field.
    email_field = page[page.index('id="field-email"') : page.index('id="field-password"')]
    assert "required" not in email_field
    assert "opsional" in email_field.lower()


def test_a_person_signs_in_with_username_or_email(tmp_path: Path) -> None:
    client = _admin(tmp_path)
    try:
        assert _create(client, email="  Budi.Santoso@Example.com ") == 303
        page = client.get("/pengguna").text
        _sign_out(client)

        by_username = _sign_in(client, "budi", "kata-sandi-budi-01")
        client.post(
            "/keluar", data={"csrf_token": _csrf(client.get("/").text)}, follow_redirects=False
        )
        by_email = _sign_in(client, "budi.santoso@example.com", "kata-sandi-budi-01")
        client.post(
            "/keluar", data={"csrf_token": _csrf(client.get("/").text)}, follow_redirects=False
        )
        by_email_any_case = _sign_in(client, "BUDI.SANTOSO@example.com", "kata-sandi-budi-01")
    finally:
        client.__exit__(None, None, None)

    assert by_username == 303
    assert by_email == 303
    assert by_email_any_case == 303
    # The list shows the address as stored: lower-cased and trimmed.
    assert "budi.santoso@example.com" in page


def test_email_is_optional_but_must_be_an_address_and_unique(tmp_path: Path) -> None:
    client = _admin(tmp_path)
    try:
        without = _create(client, username="tanpa", email="")
        malformed = _create(client, username="salah", email="bukan-alamat")
        first = _create(client, username="satu", email="sama@example.com")
        duplicate = _create(client, username="dua", email="Sama@Example.com")
        page = client.get("/pengguna").text
    finally:
        client.__exit__(None, None, None)

    assert without == 303
    assert malformed == 422
    assert first == 303
    assert duplicate == 422
    assert "tanpa" in page and "satu" in page and "dua" not in page


def test_the_json_api_carries_the_email_too(tmp_path: Path) -> None:
    client = _admin(tmp_path)
    try:
        created = client.post(
            "/api/v1/users",
            json={
                "username": "citra",
                "full_name": "Citra",
                "email": "Citra@Example.com",
                "password": "kata-sandi-citra-1",
                "role": "operator",
            },
        )
        listed = client.get("/api/v1/users").json()["users"]
    finally:
        client.__exit__(None, None, None)

    assert created.status_code == 201, created.text
    assert created.json()["email"] == "citra@example.com"
    assert any(
        user["username"] == "citra" and user["email"] == "citra@example.com" for user in listed
    )


def test_the_sign_in_page_says_either_identifier_works(tmp_path: Path) -> None:
    with TestClient(
        create_app(database_path=tmp_path / "operations.sqlite3", bootstrap_administrator=_ADMIN)
    ) as client:
        page = client.get("/masuk").text

    assert "Nama pengguna atau email" in page

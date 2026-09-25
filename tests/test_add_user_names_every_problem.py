"""Adding a user names every problem with the form at once.

An empty form was answered with "Nama pengguna wajib diisi." alone; the
missing name and password surfaced one resubmission at a time.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fuel_predictor.application.identity import CreateUser
from fuel_predictor.domain.identity import IdentityValidationError, UserRole
from fuel_predictor.main import create_app
from tests.test_two_roles import _ADMIN, _csrf, _sign_in


def _add(client: TestClient, **values: str) -> tuple[int, str]:
    token = _csrf(client.get("/pengguna").text)
    response = client.post("/pengguna", data={"csrf_token": token, "role": "operator", **values})
    return response.status_code, response.text


@pytest.fixture
def admin(tmp_path: Path) -> Iterator[TestClient]:
    with TestClient(
        create_app(database_path=tmp_path / "operations.sqlite3", bootstrap_administrator=_ADMIN)
    ) as client:
        _sign_in(client, *_ADMIN)
        yield client


def test_an_empty_form_names_every_missing_field(admin: TestClient) -> None:
    status, page = _add(admin)

    assert status == 422
    for field in ("username", "full_name", "password"):
        assert f'href="#field-{field}"' in page, field
    assert "Nama pengguna wajib diisi." in page
    assert "Nama lengkap wajib diisi." in page
    assert "Kata sandi" in page and "12 karakter" in page


def test_the_form_label_matches_the_message(admin: TestClient) -> None:
    page = admin.get("/pengguna").text

    assert "Nama lengkap" in page


def test_one_problem_is_still_named_alone(admin: TestClient) -> None:
    status, page = _add(admin, username="sari", full_name="Sari Dewi", password="pendek")

    assert status == 422
    assert "Kata sandi minimal 12 karakter." in page
    assert 'href="#field-username"' not in page
    # What was typed stays, except the password.
    assert 'value="sari"' in page and 'value="Sari Dewi"' in page


def test_a_taken_username_is_refused(admin: TestClient) -> None:
    _add(admin, username="sari", full_name="Sari Dewi", password="kata-sandi-panjang-1")
    status, page = _add(
        admin, username="Sari", full_name="Sari Lain", password="kata-sandi-panjang-2"
    )

    assert status == 422
    assert "sudah digunakan" in page


def test_a_complete_form_creates_the_user(admin: TestClient) -> None:
    token = _csrf(admin.get("/pengguna").text)
    created = admin.post(
        "/pengguna",
        data={
            "csrf_token": token,
            "username": "sari",
            "full_name": "Sari Dewi",
            "password": "kata-sandi-panjang-1",
            "role": "operator",
        },
        follow_redirects=False,
    )

    assert created.status_code == 303
    assert "Sari Dewi" in admin.get(created.headers["location"]).text


def test_the_use_case_reports_all_problems_and_the_first_as_before() -> None:
    """Callers that read one field and message still get the first problem."""
    create = CreateUser(
        user_repository=None,  # type: ignore[arg-type]
        password_hasher=None,  # type: ignore[arg-type]
        record_audit=None,  # type: ignore[arg-type]
    )

    with pytest.raises(IdentityValidationError) as refused:
        create.execute(
            username="", full_name=" ", password="", role=UserRole.OPERATOR, created_by="admin"
        )

    assert refused.value.field == "username"
    assert [problem.field for problem in refused.value.problems] == [
        "username",
        "full_name",
        "password",
    ]


def test_the_api_lists_every_problem_too(admin: TestClient) -> None:
    refused = admin.post(
        "/api/v1/users",
        json={"username": "", "full_name": "", "password": "", "role": "operator"},
    )

    assert refused.status_code == 422
    assert [error["field"] for error in refused.json()["errors"]] == [
        "username",
        "full_name",
        "password",
    ]

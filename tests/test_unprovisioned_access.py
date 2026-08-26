"""An empty users table must not mean "let everyone in" in production.

`is_system_provisioned()` was `bool(list_users())`, and its docstring argued
the empty case "is never reached once a system is actually deployed". That is
an assumption, not an enforcement. A restore predating the accounts, a botched
migration, or a manual cleanup all reach it — and the application would then
serve every page and every API route with full administrator capability and no
sign-in at all.

`.env.example` makes it likelier still: it tells operators to remove the
bootstrap credentials once the first account exists, so nothing would recreate
the missing administrator on the next restart.

Being unable to sign in is a loud, recoverable failure. Silently serving an
unauthenticated administrator session is neither.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fuel_predictor.main import create_app

# Routes worth checking individually: a page, a read API, and a write API.
_PROTECTED = ("/", "/pengelolaan-model", "/api/v1/monitoring-dashboard")


def _client(tmp_path: Path, *, allow: bool) -> TestClient:
    return TestClient(
        create_app(
            database_path=tmp_path / "operations.sqlite3",
            allow_unprovisioned_access=allow,
        )
    )


@pytest.mark.parametrize("path", _PROTECTED)
def test_an_empty_users_table_denies_access_by_default(tmp_path: Path, path: str) -> None:
    """The production default. No accounts means no access, not total access."""
    with _client(tmp_path, allow=False) as client:
        response = client.get(path, follow_redirects=False)

    assert response.status_code in (303, 401), f"{path} was served without authentication"


def test_the_legacy_open_mode_still_works_when_explicitly_enabled(tmp_path: Path) -> None:
    """The original local MVP behaviour, kept but now opt-in rather than implied."""
    with _client(tmp_path, allow=True) as client:
        response = client.get("/", follow_redirects=False)

    assert response.status_code == 200


def test_losing_every_account_locks_the_door_rather_than_opening_it(tmp_path: Path) -> None:
    """The scenario that matters: a system that *had* accounts and lost them.

    This is what a restore from before the accounts existed looks like.
    """
    database = tmp_path / "operations.sqlite3"
    app = create_app(
        database_path=database,
        bootstrap_administrator=("admin", "kata-sandi-admin-1"),
        allow_unprovisioned_access=False,
    )
    with TestClient(app) as client:
        page = client.get("/masuk")
        marker = 'name="csrf_token" value="'
        start = page.text.index(marker) + len(marker)
        token = page.text[start : page.text.index('"', start)]
        client.post(
            "/masuk",
            data={
                "username": "admin",
                "password": "kata-sandi-admin-1",
                "csrf_token": token,
            },
            follow_redirects=False,
        )
        assert client.get("/").status_code == 200

    # Every account disappears, exactly as an unlucky restore would leave it.
    import sqlalchemy

    engine = sqlalchemy.create_engine(f"sqlite+pysqlite:///{database.as_posix()}")
    with engine.begin() as connection:
        connection.execute(sqlalchemy.text("DELETE FROM user_sessions"))
        connection.execute(sqlalchemy.text("DELETE FROM users"))

    with TestClient(
        create_app(database_path=database, allow_unprovisioned_access=False)
    ) as client:
        after = client.get("/", follow_redirects=False)

    assert after.status_code in (303, 401), (
        "an application that lost its accounts served an unauthenticated request"
    )


def test_the_same_loss_would_have_opened_the_door_under_the_old_behaviour(
    tmp_path: Path,
) -> None:
    """Pins what the fix actually prevents, so the test above cannot pass vacuously."""
    database = tmp_path / "operations.sqlite3"
    with TestClient(
        create_app(database_path=database, allow_unprovisioned_access=True)
    ) as client:
        assert client.get("/", follow_redirects=False).status_code == 200

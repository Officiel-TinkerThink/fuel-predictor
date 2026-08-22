from pathlib import Path

from fastapi.testclient import TestClient

from fuel_predictor.delivery.rendering import NAVIGATION
from fuel_predictor.main import create_app

_ADMIN = ("admin", "kata-sandi-admin-1")


def _csrf_token(html: str) -> str:
    marker = 'name="csrf_token" value="'
    start = html.index(marker) + len(marker)
    return html[start : html.index('"', start)]


def test_every_navigation_link_visible_to_an_administrator_resolves(tmp_path: Path) -> None:
    """Regression test: NAVIGATION previously listed several aspirational paths
    (/prediksi-massal, /bbm-aktual, /model, ...) that had no matching route,
    so an administrator's sidebar contained dead links. NAVIGATION must only
    ever name a route that actually exists.
    """
    app = create_app(
        database_path=tmp_path / "operations.sqlite3",
        bootstrap_administrator=_ADMIN,
    )
    with TestClient(app) as client:
        page = client.get("/masuk")
        token = _csrf_token(page.text)
        client.post(
            "/masuk",
            data={"username": _ADMIN[0], "password": _ADMIN[1], "csrf_token": token},
        )

        broken = []
        for group in NAVIGATION:
            for item in group.items:
                response = client.get(item.href, follow_redirects=False)
                if response.status_code == 404:
                    broken.append(item.href)

    assert broken == []

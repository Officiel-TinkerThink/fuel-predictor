"""The files a browser asks a site for by name, and how long it may keep them.

/favicon.ico redirected to the sign-in page, so tabs, bookmarks and a
phone's home screen showed no icon; nothing told a search engine to leave
an internal tool alone; and the stylesheet and scripts, though addressed by
a hash of their content, were kept only as long as the CDN's default.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from fuel_predictor.delivery.rendering import static_version
from fuel_predictor.main import create_app

_ADMIN = ("admin", "kata-sandi-admin-1")


def _provisioned(tmp_path: Path) -> TestClient:
    """A system with a user, where an unknown visitor is sent to sign in."""
    return TestClient(
        create_app(database_path=tmp_path / "operations.sqlite3", bootstrap_administrator=_ADMIN)
    )


def test_the_icons_a_browser_asks_for_are_served_to_anyone(tmp_path: Path) -> None:
    with _provisioned(tmp_path) as client:
        icon = client.get("/favicon.ico", follow_redirects=False)
        touch = client.get("/apple-touch-icon.png", follow_redirects=False)
        manifest = client.get("/statis/manifest.webmanifest")

    assert icon.status_code == 200 and icon.headers["content-type"] == "image/vnd.microsoft.icon"
    assert touch.status_code == 200 and touch.headers["content-type"] == "image/png"
    assert manifest.status_code == 200
    body = manifest.json()
    assert body["name"] == "Fuel Matrix Calculation"
    assert {icon["sizes"] for icon in body["icons"]} == {"192x192", "512x512"}


def test_every_page_links_its_icons_and_manifest(tmp_path: Path) -> None:
    with _provisioned(tmp_path) as client:
        sign_in = client.get("/masuk").text

    assert 'rel="apple-touch-icon"' in sign_in
    assert 'rel="manifest"' in sign_in
    assert '<meta name="theme-color"' in sign_in


def test_search_engines_are_asked_to_stay_out(tmp_path: Path) -> None:
    with _provisioned(tmp_path) as client:
        robots = client.get("/robots.txt", follow_redirects=False)

    assert robots.status_code == 200
    assert "Disallow: /" in robots.text


def test_a_hashed_static_file_is_kept_for_a_year_and_an_unhashed_one_is_not(
    tmp_path: Path,
) -> None:
    with _provisioned(tmp_path) as client:
        hashed = client.get(f"/statis/app.css?v={static_version('app.css')}")
        plain = client.get("/statis/app.css")

    assert hashed.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert "immutable" not in plain.headers.get("cache-control", "")

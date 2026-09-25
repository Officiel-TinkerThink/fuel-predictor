"""Static files are addressed by their contents.

They are served behind a CDN that keeps them for hours. With a fixed address,
a deploy's new pages loaded the previous deploy's stylesheet - new markup,
old styles - until the cached copy expired.
"""

import hashlib
import re
from pathlib import Path

from fastapi.testclient import TestClient

from fuel_predictor.delivery.rendering import STATIC_DIRECTORY, TEMPLATE_DIRECTORY
from fuel_predictor.main import create_app


def test_every_static_reference_in_a_template_carries_a_version() -> None:
    for path in TEMPLATE_DIRECTORY.glob("*.html"):
        unversioned = re.findall(r'"/statis/[^"?]+"', path.read_text())
        assert unversioned == [], f"{path.name}: {unversioned}"


def test_a_page_asks_for_the_stylesheet_by_its_contents(tmp_path: Path) -> None:
    expected = hashlib.sha256((STATIC_DIRECTORY / "app.css").read_bytes()).hexdigest()[:12]
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        page = client.get("/masuk").text
        address = re.search(r'href="(/statis/app\.css\?v=[0-9a-f]+)"', page)
        assert address is not None
        stylesheet = client.get(address.group(1))

    assert address.group(1).endswith(f"?v={expected}")
    assert stylesheet.status_code == 200

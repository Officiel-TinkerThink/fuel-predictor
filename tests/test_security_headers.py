"""Every response tells the browser what the page may do.

The live site sent no security headers at all: any page could be framed by
another site, a script injected into one would have run with the page's
authority, and responses carried no referrer or content-type policy. Now:

- a Content-Security-Policy that allows the app's own scripts and styles,
  the two inline scripts by a per-request nonce, and the Google Maps embed
  as the only frame - FastAPI's /docs and /redoc, which load Swagger from a
  CDN, are left out of it;
- framing refused, content types not sniffed, referrers trimmed to the
  origin across sites, powerful browser features switched off;
- Strict-Transport-Security once the request came over HTTPS.
"""

import re
from pathlib import Path

from fastapi.testclient import TestClient

from fuel_predictor.main import create_app
from tests.test_actual_fuel_outcomes import _operation_with_prediction, _train_baseline


def _client(tmp_path: Path, base_url: str = "http://testserver") -> TestClient:
    return TestClient(create_app(database_path=tmp_path / "operations.sqlite3"), base_url=base_url)


def test_a_page_carries_the_policy_and_its_inline_scripts_the_nonce(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        first = client.get("/prediksi")
        second = client.get("/prediksi")

    policy = first.headers["content-security-policy"]
    nonce = re.search(r"'nonce-([^']+)'", policy)
    assert nonce is not None
    assert "script-src 'self' 'nonce-" in policy
    assert "frame-ancestors 'none'" in policy
    assert "object-src 'none'" in policy
    assert "https://www.google.com" in policy  # the route map's embed
    # Every inline script the page holds is the nonce's; none without it.
    inline = re.findall(r"<script(?![^>]*\bsrc=)([^>]*)>", first.text)
    assert inline and all(f'nonce="{nonce.group(1)}"' in attributes for attributes in inline)
    # A nonce is used once.
    assert second.headers["content-security-policy"] != policy

    assert first.headers["x-content-type-options"] == "nosniff"
    assert first.headers["x-frame-options"] == "DENY"
    assert first.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "camera=()" in first.headers["permissions-policy"]


def test_no_page_relies_on_what_the_policy_forbids(tmp_path: Path) -> None:
    """Inline event handlers and style attributes do not run or apply under
    the policy; no page may lean on them."""
    with _client(tmp_path) as client:
        _train_baseline(client)
        operation = _operation_with_prediction(client, 24)["operation"]
        code = operation["operation_code"]
        pages = [
            client.get(path).text
            for path in (
                "/",
                "/masuk",
                "/lupa-kata-sandi",
                "/prediksi",
                "/riwayat-prediksi",
                "/armada",
                "/bahan-bakar-aktual",
                "/bahan-bakar-aktual-massal",
                "/prediksi-operasi-massal",
                "/pemantauan/kinerja-model",
                "/pemantauan/pergeseran-data",
                "/pemantauan/kesehatan-sistem",
                "/pengelolaan-model",
                "/impor-data-historis",
                f"/operasi-harian/{code}",
                f"/operasi-harian/{code}/slip",
            )
        ]

    for page in pages:
        assert not re.search(r"\son[a-z]+=", page), re.search(r"\son[a-z]+=[^>]*", page)
        assert ' style="' not in page


def test_https_asks_the_browser_to_stay_on_https(tmp_path: Path) -> None:
    with _client(tmp_path, "https://testserver") as secure:
        over_https = secure.get("/masuk")
    with _client(tmp_path) as plain:
        over_http = plain.get("/masuk")

    assert over_https.headers["strict-transport-security"] == "max-age=31536000"
    assert "strict-transport-security" not in over_http.headers


def test_the_api_documentation_keeps_working_without_the_page_policy(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        docs = client.get("/docs")
        api = client.get("/sehat")

    assert docs.status_code == 200
    assert "content-security-policy" not in docs.headers
    assert docs.headers["x-content-type-options"] == "nosniff"
    assert api.headers["x-content-type-options"] == "nosniff"

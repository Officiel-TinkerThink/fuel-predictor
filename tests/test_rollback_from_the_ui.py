"""Rolling back to the previous model is a button, not an API call.

The activation path already accepted a retired version whose package bytes
were retained (ADR 0010), and the operator guide told people to "activate
the previous version again from the same page" - but no page offered it.
Pengelolaan Model now lists every version with its status, and a retired
version with retained bytes gets "Aktifkan kembali"; versions trained
in-process, which have no package to reload, are shown without one.
"""

from typing import Any

from fastapi.testclient import TestClient

from tests.test_retained_package_activation import (
    _csrf,
    _model_version_id,
    _package,
    _upload,
    client,  # noqa: F401  (fixture)
)


def _activate(test_client: TestClient, model_version_id: str) -> Any:
    return test_client.post(
        f"/kandidat-model/{model_version_id}/promosikan",
        data={"csrf_token": _csrf(test_client.get("/pengelolaan-model").text)},
    )


def test_a_retired_package_can_be_reactivated_from_the_page(client: TestClient) -> None:  # noqa: F811
    assert _upload(client, _package("fuel-model-2026.08.25.1")).status_code in (200, 201)
    first = _model_version_id(client)
    assert _activate(client, first).status_code == 200

    assert _upload(client, _package("fuel-model-2026.09.01.1")).status_code in (200, 201)
    second = _model_version_id(client)
    assert _activate(client, second).status_code == 200

    page = client.get("/pengelolaan-model").text
    assert "Semua versi" in page
    # The retired first version offers a way back; the active one does not.
    assert "Aktifkan kembali" in page
    assert f'action="/kandidat-model/{first}/promosikan"' in page
    assert f'action="/kandidat-model/{second}/promosikan"' not in page

    rolled_back = _activate(client, first)
    assert rolled_back.status_code == 200, rolled_back.text
    dashboard = client.get("/api/v1/model-governance-dashboard").json()
    assert dashboard["active_model"]["model_version_id"] == first

"""An activated package keeps serving after the app restarts, and can be measured.

The activated package lived only in the running process's memory. After a
restart - every deploy is one - predictions fell back to the MLflow store,
which cannot load a package, so every estimate failed while a package was the
active model. The model management page and the overview failed the same way
as soon as one actual fuel was recorded: they re-score the actuals with the
active model through that same store, reloading it once per actual.

Both now go through a scorer that loads a retained package from its own
checksummed bytes, and any model only once.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from fuel_predictor.main import create_app
from tests.test_retained_package_activation import _ADMIN, _csrf, _model_version_id, _package


def _signed_in(tmp_path: Path) -> TestClient:
    client = TestClient(
        create_app(database_path=tmp_path / "operations.sqlite3", bootstrap_administrator=_ADMIN)
    )
    client.__enter__()
    client.post(
        "/masuk",
        data={
            "username": _ADMIN[0],
            "password": _ADMIN[1],
            "csrf_token": _csrf(client.get("/masuk").text),
        },
        follow_redirects=False,
    )
    return client


@pytest.fixture
def activated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("FUEL_PREDICTOR_MODEL_ARTIFACT_DIRECTORY", str(tmp_path / "packages"))
    client = _signed_in(tmp_path)
    try:
        upload = client.post(
            "/model/unggah",
            files={"file": ("paket.zip", _package(), "application/zip")},
            data={"csrf_token": _csrf(client.get("/model/unggah").text)},
        )
        assert upload.status_code == 201, upload.text
        promoted = client.post(
            f"/kandidat-model/{_model_version_id(client)}/promosikan",
            data={"csrf_token": _csrf(client.get("/pengelolaan-model").text)},
        )
        assert promoted.status_code == 200, promoted.text
    finally:
        client.__exit__(None, None, None)
    yield tmp_path


def _predict(client: TestClient, distance: float, lifting: float) -> dict[str, Any]:
    operation = client.post(
        "/api/v1/daily-operations",
        json={
            "vehicle_category": "ANGBER",
            "activity_mode": "transport",
            "total_distance_km": distance,
            "lifting_hours": lifting or None,
            "distance_source": "manual",
        },
    ).json()
    prediction = client.post(f"/api/v1/daily-operations/{operation['operation_id']}/predictions")
    assert prediction.status_code == 201, prediction.text
    return {"operation": operation, "prediction": prediction.json()}


def test_the_active_package_still_predicts_after_a_restart(activated: Path) -> None:
    restarted = _signed_in(activated)
    try:
        result = _predict(restarted, 30, 0)
    finally:
        restarted.__exit__(None, None, None)

    # The package's own arithmetic: 0.5 x 30 km.
    assert result["prediction"]["estimated_fuel_requirement_liters"] == pytest.approx(
        15.0, abs=0.05
    )
    assert result["prediction"]["model"]["model_version_id"] == "fuel-model-2026.08.25.1"


def test_the_model_pages_measure_an_active_package_against_actuals(activated: Path) -> None:
    restarted = _signed_in(activated)
    try:
        result = _predict(restarted, 40, 0)
        recorded = restarted.post(
            f"/api/v1/daily-operations/{result['operation']['operation_id']}/actual-fuel",
            json={"actual_fuel_liters": 22, "measurement_source": "fuel_meter"},
        )
        assert recorded.status_code == 201, recorded.text

        management = restarted.get("/pengelolaan-model")
        overview = restarted.get("/")
    finally:
        restarted.__exit__(None, None, None)

    assert management.status_code == 200, management.text
    assert overview.status_code == 200, overview.text
    # |0.5 x 40 - 22| = 2 L, re-scored by the package itself.
    assert "2 L" in management.text

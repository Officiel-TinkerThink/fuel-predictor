"""Activating an ingested package through the governance page (ADR 0010).

The point of this test is the seam the unit tests cannot reach: a package
uploaded through the web UI is retained on disk, and activating it later must
rebuild the loader from *those* bytes, run the ordered sequence, and leave the
in-process holder serving predictions from the new model.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import skops.io as skops_io
from fastapi.testclient import TestClient
from sklearn.linear_model import LinearRegression

from fuel_predictor.main import create_app
from fuel_predictor.packaging.model_packager import ModelPackageBuilder

_ADMIN = ("admin", "kata-sandi-admin-1")

# The app's own feature contract, so the activated model can actually serve a
# real prediction rather than only satisfying the package schema.
_FEATURES = ("total_distance_km", "lifting_hours")


def _model_bytes() -> bytes:
    rows = [[d, h] for d in (10.0, 20.0, 30.0, 40.0) for h in (0.0, 1.0, 2.0)]
    targets = [0.5 * d + 2.0 * h for d, h in rows]
    return bytes(skops_io.dumps(LinearRegression().fit(rows, targets)))


def _package(model_version: str = "fuel-model-2026.08.25.1") -> bytes:
    builder = ModelPackageBuilder(
        model_version=model_version,
        model_format="skops",
        runtime_compatibility_version="skops-0.11",
        feature_contract_version="baseline-v1",
        feature_schema=[{"name": name, "type": "number"} for name in _FEATURES],
        target_name="prepared_fuel_liters",
        target_unit="liters",
        training_dataset_version="DSV-000001",
        trained_at=datetime(2026, 8, 25, tzinfo=UTC),
        source_revision="abc123",
        metrics={
            "overall": {
                "mae": 1.0,
                "rmse": 1.5,
                "smape_percent": 5.0,
                "interval_coverage_percent": 95.0,
            }
        },
        test_set_size=50,
        training_row_count=400,
        expected_memory_bytes=10_000_000,
    )
    return builder.build(
        model_bytes=_model_bytes(),
        reference_statistics=_statistics(),
        smoke_tests=_smoke_tests(),
    )


def _statistics() -> dict[str, Any]:
    return {
        "row_count": 120,
        "features": {
            "total_distance_km": {
                "kind": "numeric",
                "minimum": 10.0,
                "maximum": 40.0,
                "mean": 25.0,
                "standard_deviation": 11.0,
            },
            "lifting_hours": {
                "kind": "numeric",
                "minimum": 0.0,
                "maximum": 2.0,
                "mean": 1.0,
                "standard_deviation": 0.8,
            },
        },
    }


def _smoke_tests() -> dict[str, Any]:
    return {
        "cases": [
            {
                "name": "angkut 30 km dengan 1 jam lifting",
                "features": {"total_distance_km": 30.0, "lifting_hours": 1.0},
                "expected_prediction": 17.0,
                "tolerance": 0.01,
            }
        ]
    }


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("FUEL_PREDICTOR_MODEL_ARTIFACT_DIRECTORY", str(tmp_path / "packages"))
    with TestClient(
        create_app(database_path=tmp_path / "operations.sqlite3", bootstrap_administrator=_ADMIN)
    ) as test_client:
        test_client.post(
            "/masuk",
            data={
                "username": _ADMIN[0],
                "password": _ADMIN[1],
                "csrf_token": _csrf(test_client.get("/masuk").text),
            },
            follow_redirects=False,
        )
        yield test_client


def _csrf(html: str) -> str:
    marker = 'name="csrf_token" value="'
    start = html.index(marker) + len(marker)
    return html[start : html.index('"', start)]


def _token(test_client: TestClient) -> str:
    return _csrf(test_client.get("/model/unggah").text)


def _upload(test_client: TestClient, archive: bytes) -> Any:
    return test_client.post(
        "/model/unggah",
        files={"file": ("paket.zip", archive, "application/zip")},
        data={"csrf_token": _token(test_client)},
    )


def _model_version_id(test_client: TestClient) -> str:
    candidates = test_client.get("/api/v1/model-candidates")
    if candidates.status_code == 200:
        return str(candidates.json()["candidates"][0]["model_version_id"])
    page = test_client.get("/pengelolaan-model").text
    marker = 'action="/kandidat-model/'
    start = page.index(marker) + len(marker)
    return page[start : page.index("/promosikan", start)]


def test_an_uploaded_package_can_be_activated_and_then_serves_predictions(
    client: TestClient,
) -> None:
    upload = _upload(client, _package())
    assert upload.status_code in (200, 201), upload.text

    model_version_id = _model_version_id(client)
    activation = client.post(
        f"/kandidat-model/{model_version_id}/promosikan",
        data={"csrf_token": _csrf(client.get("/pengelolaan-model").text)},
    )
    assert activation.status_code == 200, activation.text

    operation = client.post(
        "/api/v1/daily-operations",
        json={
            "vehicle_category": "ANGBER",
            "activity_mode": "transport_and_lifting",
            "lifting_hours": 1,
            "total_distance_km": 30,
            "distance_source": "manual",
        },
    ).json()
    prediction = client.post(
        f"/api/v1/daily-operations/{operation['operation_id']}/predictions"
    )

    assert prediction.status_code == 201, prediction.text
    body = prediction.json()
    # 0.5 * 30 + 2.0 * 1 = 17.0, which is the packaged model's own arithmetic —
    # proof the prediction came from the activated package rather than from a
    # model this process trained.
    assert body["estimated_fuel_requirement_liters"] == pytest.approx(17.0, abs=0.05)
    assert body["model"]["model_version_id"] == "fuel-model-2026.08.25.1"


def test_a_package_whose_retained_bytes_were_tampered_with_is_not_activated(
    client: TestClient, tmp_path: Path
) -> None:
    """Retained bytes must prove themselves again, not coast on upload-time trust."""
    assert _upload(client, _package()).status_code in (200, 201)
    model_version_id = _model_version_id(client)

    retained = tmp_path / "packages"
    artefact = next(retained.rglob("model.skops"))
    artefact.write_bytes(artefact.read_bytes() + b"tambahan")

    activation = client.post(
        f"/kandidat-model/{model_version_id}/promosikan",
        data={"csrf_token": _csrf(client.get("/pengelolaan-model").text)},
    )

    assert activation.status_code == 409
    assert "checksum" in activation.text.lower() or "berkas" in activation.text.lower()


def test_a_package_whose_manifest_no_longer_matches_its_bytes_is_refused(
    client: TestClient, tmp_path: Path
) -> None:
    assert _upload(client, _package()).status_code in (200, 201)
    model_version_id = _model_version_id(client)

    retained = tmp_path / "packages"
    manifest_path = next(retained.rglob("manifest.json"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["expected_memory_bytes"] = 10_000_000_000_000
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    activation = client.post(
        f"/kandidat-model/{model_version_id}/promosikan",
        data={"csrf_token": _csrf(client.get("/pengelolaan-model").text)},
    )

    # Either the checksum catches the edited manifest or the capacity check
    # refuses the absurd footprint. Both are correct refusals; what must not
    # happen is a successful activation.
    assert activation.status_code == 409


def test_the_training_row_count_survives_into_the_registered_model(
    client: TestClient, tmp_path: Path
) -> None:
    """It used to be recorded as 0 because the manifest did not carry the figure.

    Never borrowed from test_set_size: that counts the held-out rows the metrics
    were computed from, and putting it in a field named for the training size
    would mislabel one number as another.
    """
    assert _upload(client, _package()).status_code in (200, 201)

    recorded = _training_row_count(tmp_path / "operations.sqlite3", _model_version_id(client))

    assert recorded == 400
    assert recorded != 50, "test_set_size leaked into the training count"


def test_a_package_without_the_field_still_validates_and_registers(
    client: TestClient, tmp_path: Path
) -> None:
    """Packages built before the field existed must keep working.

    The field is optional in the schema for exactly this reason; only the
    packager in this repository requires it.
    """
    archive = _package_without_training_row_count()

    upload = _upload(client, archive)

    assert upload.status_code in (200, 201), upload.text
    recorded = _training_row_count(tmp_path / "operations.sqlite3", _model_version_id(client))
    assert recorded == 0


def _training_row_count(database: Path, model_version_id: str) -> int:
    import sqlalchemy

    engine = sqlalchemy.create_engine(f"sqlite+pysqlite:///{database.as_posix()}")
    with engine.connect() as connection:
        return int(
            connection.execute(
                sqlalchemy.text(
                    "SELECT training_row_count FROM model_versions"
                    " WHERE model_version_id = :id"
                ),
                {"id": model_version_id},
            ).scalar_one()
        )


def _package_without_training_row_count() -> bytes:
    """Rebuild a valid package with the field stripped from the manifest."""
    import io
    import json as _json
    import zipfile

    original = _package(model_version="fuel-model-2026.08.27.2")
    with zipfile.ZipFile(io.BytesIO(original)) as source:
        members = {name: source.read(name) for name in source.namelist()}

    manifest = _json.loads(members["manifest.json"].decode("utf-8"))
    manifest.pop("training_row_count", None)
    members["manifest.json"] = _json.dumps(
        manifest, indent=2, sort_keys=True, ensure_ascii=False
    ).encode("utf-8")
    # Checksums cover the other members, not the manifest itself, so editing the
    # manifest alone keeps the package internally consistent.
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as rebuilt:
        for name in sorted(members):
            rebuilt.writestr(name, members[name])
    return buffer.getvalue()

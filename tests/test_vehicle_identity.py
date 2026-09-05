"""The individual vehicle as a prediction feature.

`vehicle_category` has one value, so as a feature it was a constant column that
told the model nothing. The unit that actually ran the operation is named
throughout the operational sheets, and two cranes of the same model do not
consume alike once one is older.

These tests cover the part that is easy to get wrong: that inputs still match
what a model was trained on, in both directions, so predictions keep coming out.
"""

from pathlib import Path
from urllib.parse import urlencode

from fastapi.testclient import TestClient

from fuel_predictor.application.prediction_features import FEATURE_VERSION, feature_values
from fuel_predictor.domain.daily_operation import (
    ActivityMode,
    DailyOperation,
    DistanceSource,
    VehicleCategory,
)
from fuel_predictor.infrastructure.packaged_vehicle_catalog import PackagedVehicleCatalog
from fuel_predictor.main import create_app

_WITH_VEHICLE = (
    b"Kategori ANGBER,Kendaraan,Mode Aktivitas,Jam Lifting,Jarak Total (km),"
    b"Bahan Bakar Disiapkan (L),Sumber Jarak\n"
    b"ANGBER,Truck Crane 01,transport,,20,18,manual\n"
    b"ANGBER,Truck Crane 01,transport,,40,28,manual\n"
    b"ANGBER,Prime Mover,transport,,20,26,manual\n"
    b"ANGBER,Prime Mover,transport,,40,44,manual\n"
)

_WITHOUT_VEHICLE = (
    b"Kategori ANGBER,Mode Aktivitas,Jam Lifting,Jarak Total (km),"
    b"Bahan Bakar Disiapkan (L),Sumber Jarak\n"
    b"ANGBER,transport,,20,18,manual\n"
    b"ANGBER,transport,,40,28,manual\n"
)


def _train_and_promote(client: TestClient, historical_csv: bytes) -> None:
    dataset = client.post(
        "/api/v1/historical-datasets",
        files={"file": ("riwayat.csv", historical_csv, "text/csv")},
    ).json()["dataset_version"]
    candidate = client.post(
        f"/api/v1/dataset-versions/{dataset['dataset_version_id']}/baseline-candidates"
    )
    assert candidate.status_code == 201, candidate.text
    promoted = client.post(
        f"/api/v1/model-candidates/{candidate.json()['model_version_id']}/promote"
    )
    assert promoted.status_code == 200, promoted.text


def _operation(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "vehicle_category": "ANGBER",
        "vehicle": "Truck Crane 01",
        "activity_mode": "transport",
        "total_distance_km": 30,
        "distance_source": "manual",
    }
    body.update(overrides)
    return body


def test_the_feature_contract_carries_the_vehicle_and_names_a_new_version() -> None:
    operation = DailyOperation(
        operation_id="OPR-FEATURES",
        vehicle_category=VehicleCategory.ANGBER,
        vehicle="Truck Crane 01",
        activity_mode=ActivityMode.TRANSPORT,
        lifting_hours=None,
        total_distance_km=30.0,
        distance_source=DistanceSource.MANUAL,
    )

    features = feature_values(operation)

    assert features["vehicle"] == "Truck Crane 01"
    # The contract changed, so the version has to move with it.
    assert FEATURE_VERSION == "baseline-v2"


def test_an_operation_without_a_named_vehicle_is_its_own_category() -> None:
    """Unrecorded is a value the model can learn from, not a hole."""
    operation = DailyOperation(
        operation_id="OPR-UNKNOWN",
        vehicle_category=VehicleCategory.ANGBER,
        activity_mode=ActivityMode.TRANSPORT,
        lifting_hours=None,
        total_distance_km=30.0,
        distance_source=DistanceSource.MANUAL,
    )

    assert feature_values(operation)["vehicle"] == "tidak diketahui"


def test_a_prediction_comes_out_when_the_model_learned_the_vehicle(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_and_promote(client, _WITH_VEHICLE)
        operation = client.post("/api/v1/daily-operations", json=_operation())
        prediction = client.post(
            f"/api/v1/daily-operations/{operation.json()['operation_id']}/predictions"
        )

    assert operation.status_code == 201, operation.text
    assert operation.json()["vehicle"] == "Truck Crane 01"
    assert prediction.status_code == 201, prediction.text
    assert prediction.json()["estimated_fuel_requirement_liters"] > 0
    assert prediction.json()["feature_values"]["vehicle"] == "Truck Crane 01"


def test_the_model_tells_the_vehicles_apart(tmp_path: Path) -> None:
    """The point of the feature: identical journeys, different trucks, different answers."""
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_and_promote(client, _WITH_VEHICLE)
        estimates = {}
        for vehicle in ("Truck Crane 01", "Prime Mover"):
            operation = client.post("/api/v1/daily-operations", json=_operation(vehicle=vehicle))
            prediction = client.post(
                f"/api/v1/daily-operations/{operation.json()['operation_id']}/predictions"
            )
            assert prediction.status_code == 201, prediction.text
            estimates[vehicle] = prediction.json()["estimated_fuel_requirement_liters"]

    # The training rows gave the Prime Mover a heavier burn per kilometre.
    assert estimates["Prime Mover"] > estimates["Truck Crane 01"]


def test_a_model_trained_before_the_vehicle_existed_still_predicts(tmp_path: Path) -> None:
    """The compatibility that makes this safe to roll out.

    Scoring maps feature names to columns, so a model fitted without the vehicle
    ignores the extra key rather than failing on it. Without this, adding a
    feature would break every model already in production.
    """
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_and_promote(client, _WITHOUT_VEHICLE)
        operation = client.post("/api/v1/daily-operations", json=_operation())
        prediction = client.post(
            f"/api/v1/daily-operations/{operation.json()['operation_id']}/predictions"
        )

    assert prediction.status_code == 201, prediction.text
    assert prediction.json()["estimated_fuel_requirement_liters"] > 0


def test_an_operation_recorded_without_a_vehicle_still_predicts(tmp_path: Path) -> None:
    """And the other direction: a model that knows vehicles, an input that does not."""
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_and_promote(client, _WITH_VEHICLE)
        body = _operation()
        del body["vehicle"]
        operation = client.post("/api/v1/daily-operations", json=body)
        prediction = client.post(
            f"/api/v1/daily-operations/{operation.json()['operation_id']}/predictions"
        )

    assert operation.status_code == 201, operation.text
    # The API omits optional fields that were never set, rather than nulling them.
    assert "vehicle" not in operation.json()
    assert prediction.status_code == 201, prediction.text


def test_an_unrecognised_vehicle_name_is_quarantined_with_the_valid_ones(tmp_path: Path) -> None:
    historical = (
        b"Kategori ANGBER,Kendaraan,Mode Aktivitas,Jam Lifting,Jarak Total (km),"
        b"Bahan Bakar Disiapkan (L),Sumber Jarak\n"
        b"ANGBER,Helikopter,transport,,20,18,manual\n"
    )
    with TestClient(
        create_app(
            database_path=tmp_path / "operations.sqlite3",
            vehicle_catalog=PackagedVehicleCatalog(),
        )
    ) as client:
        response = client.post(
            "/api/v1/historical-datasets",
            files={"file": ("riwayat.csv", historical, "text/csv")},
        )

    assert response.status_code == 201, response.text
    reasons = str(response.json()["correction_report"])
    assert "Truck Crane 01" in reasons


def test_sheets_that_never_named_the_unit_still_import(tmp_path: Path) -> None:
    """Existing history predates the column and must not be rejected over it."""
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        response = client.post(
            "/api/v1/historical-datasets",
            files={"file": ("riwayat.csv", _WITHOUT_VEHICLE, "text/csv")},
        )

    assert response.status_code == 201, response.text
    assert response.json()["dataset_version"]["valid_operation_count"] == 2


def test_the_form_offers_the_fleet_and_records_the_choice(tmp_path: Path) -> None:
    with TestClient(
        create_app(
            database_path=tmp_path / "operations.sqlite3",
            vehicle_catalog=PackagedVehicleCatalog(),
        )
    ) as client:
        form = client.get("/prediksi")
        saved = client.post(
            "/operasi-harian",
            content=urlencode(
                [
                    ("vehicle_category", "ANGBER"),
                    ("vehicle", "Wheel Crane"),
                    ("activity_mode", "transport"),
                    ("total_distance_km", "30"),
                    ("distance_source", "manual"),
                ]
            ),
            headers={"content-type": "application/x-www-form-urlencoded"},
        )

    assert form.status_code == 200
    assert 'value="Truck Crane 01"' in form.text
    assert 'value="Winch Truck"' in form.text
    # The stop sequence and its route map are untouched by this change.
    assert 'name="stop_sequence"' in form.text
    assert 'id="route-map"' in form.text
    assert saved.status_code == 201, saved.text
    assert "Wheel Crane" in saved.text


def test_the_fleet_comes_from_the_sheet_export_not_from_code() -> None:
    """The fleet is reference data the planner maintains, not a code constant."""
    catalog = PackagedVehicleCatalog()

    options = catalog.options()
    names = {option.name for option in options}

    assert len(options) > 15
    assert {"Prime Mover", "Truck Crane 01", "Wheel Crane", "VT 01"} <= names
    assert {option.group for option in options} == {
        "Crane",
        "Forklift",
        "Truck",
        "Vacuum Truck",
    }


def test_the_names_the_sheets_actually_use_resolve_to_one_vehicle() -> None:
    """History is written inconsistently; the workbook's own alias map fixes it."""
    catalog = PackagedVehicleCatalog()

    assert catalog.find("PM 01") is not None
    assert catalog.find("PM 01").name == "Prime Mover"
    assert catalog.find("T CRANE 01").name == "Truck Crane 01"
    assert catalog.find("WHELL CRANE").name == "Wheel Crane"
    assert catalog.find("OFT").name == "Oil Field Truck"
    # Case and spacing vary just as much as the names themselves.
    assert catalog.find("  vt01 ").name == "VT 01"
    assert catalog.find("Helikopter") is None


def test_imported_history_lands_on_the_canonical_vehicle_name(tmp_path: Path) -> None:
    """Otherwise "PM 01" and "Prime Mover" become two vehicles, and the feature
    fragments across the ways people write the same truck."""
    catalog = PackagedVehicleCatalog()
    historical = (
        b"Kategori ANGBER,Kendaraan,Mode Aktivitas,Jam Lifting,Jarak Total (km),"
        b"Bahan Bakar Disiapkan (L),Sumber Jarak\n"
        b"ANGBER,PM 01,transport,,20,26,manual\n"
        b"ANGBER,Prime Mover,transport,,40,44,manual\n"
    )
    with TestClient(
        create_app(database_path=tmp_path / "operations.sqlite3", vehicle_catalog=catalog)
    ) as client:
        response = client.post(
            "/api/v1/historical-datasets",
            files={"file": ("riwayat.csv", historical, "text/csv")},
        )

    assert response.status_code == 201, response.text
    written = {row["vehicle"] for row in response.json()["valid_operations"]}
    assert written == {"Prime Mover"}


def test_history_still_imports_before_the_fleet_has_been_loaded(tmp_path: Path) -> None:
    """A fresh database has an empty vehicles table until `import-vehicles` runs.

    Quarantining every row that names a truck would make the importer unusable
    on a new installation, so an unloaded catalog takes names as written.
    """
    historical = (
        b"Kategori ANGBER,Kendaraan,Mode Aktivitas,Jam Lifting,Jarak Total (km),"
        b"Bahan Bakar Disiapkan (L),Sumber Jarak\n"
        b"ANGBER,Prime Mover,transport,,20,26,manual\n"
        b"ANGBER,Prime Mover,transport,,40,44,manual\n"
    )
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        response = client.post(
            "/api/v1/historical-datasets",
            files={"file": ("riwayat.csv", historical, "text/csv")},
        )

    assert response.status_code == 201, response.text
    assert response.json()["dataset_version"]["valid_operation_count"] == 2

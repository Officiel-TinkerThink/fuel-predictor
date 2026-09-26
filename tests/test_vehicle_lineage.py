"""The vehicle lineage: instance, type, group (ADR 0015).

The planner names a unit; the catalog says what type and group it belongs to;
the feature contract and the similar-operations ranking are handed that
lineage at the moment they need it. None of it is asked of the planner, and
baseline-v2's features do not change.
"""

from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from alembic import command
from fuel_predictor.application.prediction_features import (
    FEATURE_VERSION,
    LINEAGE_AWARE_FEATURE_VERSIONS,
    feature_values,
    input_snapshot,
)
from fuel_predictor.application.similar_operations import (
    FindSimilarOperations,
    HistoricalOperationRecord,
    HistorySource,
    SimilarOperationsQuery,
    VehicleMatch,
)
from fuel_predictor.application.vehicles import (
    UNKNOWN_VEHICLE,
    VehicleLineage,
    VehicleOption,
    catalog_fingerprint,
)
from fuel_predictor.domain.daily_operation import (
    ActivityMode,
    DailyOperation,
    DistanceSource,
    VehicleCategory,
)
from fuel_predictor.infrastructure.database import (
    build_engine,
    build_session_factory,
    create_schema_for_tests,
)
from fuel_predictor.infrastructure.packaged_vehicle_catalog import PackagedVehicleCatalog
from fuel_predictor.infrastructure.sqlalchemy_vehicles import SqlAlchemyVehicleRepository
from fuel_predictor.main import create_app

# --- the catalog --------------------------------------------------------------


def test_units_the_owner_has_not_typed_keep_their_group_as_their_type() -> None:
    """The Data Ratio sheet types most of the fleet (test_fleet_taxonomy); the
    units it does not list keep the placeholder: their type is their group."""
    catalog = PackagedVehicleCatalog()

    for name in ("VT 14", "VT 15", "Forklift SCM", "Wheel Loader Forklift"):
        option = catalog.find(name)
        assert option is not None
        assert option.type == option.group, name


def test_a_sheet_without_the_type_column_still_imports(tmp_path: Path) -> None:
    sheet = tmp_path / "kendaraan.csv"
    sheet.write_text(
        "nama_kendaraan,grup,alias\nVT 01,Vacuum Truck,\nForklift SCM,Forklift,FORKLIFT\n",
        encoding="utf-8",
    )
    catalog = PackagedVehicleCatalog(sheet)

    assert catalog.lineage_of("vt01") == VehicleLineage("VT 01", "Vacuum Truck", "Vacuum Truck")
    assert catalog.lineage_of("forklift") == VehicleLineage("Forklift SCM", "Forklift", "Forklift")


def test_a_blank_type_cell_names_the_type_after_the_group(tmp_path: Path) -> None:
    sheet = tmp_path / "kendaraan.csv"
    sheet.write_text(
        "nama_kendaraan,grup,tipe,alias\nVT 01,Vacuum Truck,VT A,\nVT 09,Vacuum Truck,,\n",
        encoding="utf-8",
    )
    catalog = PackagedVehicleCatalog(sheet)

    assert catalog.lineage_of("VT 01") == VehicleLineage("VT 01", "VT A", "Vacuum Truck")
    assert catalog.lineage_of("VT 09") == VehicleLineage("VT 09", "Vacuum Truck", "Vacuum Truck")


def test_an_unknown_or_missing_name_is_unknown_at_every_level_and_never_raises() -> None:
    catalog = PackagedVehicleCatalog()

    for written in ("Bulldozer", "", None):
        assert catalog.lineage_of(written) == VehicleLineage.unknown()
    assert VehicleLineage.unknown() == VehicleLineage(
        UNKNOWN_VEHICLE, UNKNOWN_VEHICLE, UNKNOWN_VEHICLE
    )


def test_the_type_round_trips_through_the_vehicles_table(tmp_path: Path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{(tmp_path / 'fleet.sqlite3').as_posix()}")
    create_schema_for_tests(engine)
    repository = SqlAlchemyVehicleRepository(build_session_factory(engine))

    repository.replace_all(
        (
            VehicleOption("VT 01", "Vacuum Truck", (), type="VT A"),
            VehicleOption("Truck Crane 01", "Crane", ("T CRANE 01",)),
        )
    )

    assert repository.lineage_of("t crane 01") == VehicleLineage("Truck Crane 01", "Crane", "Crane")
    assert repository.lineage_of("VT 01") == VehicleLineage("VT 01", "VT A", "Vacuum Truck")
    assert repository.lineage_of("VT 99") == VehicleLineage.unknown()


def test_the_migration_backfills_the_type_from_the_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A populated deployment upgrades with every unit's type named after its group."""
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'migration.sqlite3').as_posix()}"
    monkeypatch.setenv("FUEL_PREDICTOR_DATABASE_URL", database_url)
    config = Config("alembic.ini")
    command.upgrade(config, "20260918_19")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO vehicles (name, vehicle_group, aliases) "
                "VALUES ('VT 01', 'Vacuum Truck', '[]'), ('Prime Mover', 'Truck', '[\"PM 01\"]')"
            )
        )

    command.upgrade(config, "head")

    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT name, vehicle_group, vehicle_type FROM vehicles ORDER BY name")
        ).all()
    assert [tuple(row) for row in rows] == [
        ("Prime Mover", "Truck", "Truck"),
        ("VT 01", "Vacuum Truck", "Vacuum Truck"),
    ]


# --- the feature contract ----------------------------------------------------------


def _operation(vehicle: str | None = "Truck Crane 01") -> DailyOperation:
    return DailyOperation(
        operation_id="OPR-LINEAGE",
        vehicle_category=VehicleCategory.ANGBER,
        vehicle=vehicle,
        activity_mode=ActivityMode.TRANSPORT_AND_LIFTING,
        lifting_hours=2.5,
        total_distance_km=30.0,
        distance_source=DistanceSource.MANUAL,
        stop_sequence=("POOL LIMAU", "SP-II", "POOL LIMAU"),
    )


def test_baseline_v2_features_are_exactly_what_they_were_whatever_the_lineage_says() -> None:
    """The lineage is handed in; this contract does not read it. The keys and
    values a v2 model was fitted on must not move under it."""
    expected = {
        "vehicle_category": "ANGBER",
        "vehicle": "Truck Crane 01",
        "activity_mode": "transport_and_lifting",
        "distance_source": "manual",
        "total_distance_km": 30.0,
        "lifting_hours": 2.5,
    }

    for lineage in (
        PackagedVehicleCatalog().lineage_of("Truck Crane 01"),
        VehicleLineage("Truck Crane 01", "Crane besar", "Crane"),
        VehicleLineage.unknown(),
    ):
        assert feature_values(_operation(), lineage) == expected
    assert FEATURE_VERSION == "baseline-v2"
    assert FEATURE_VERSION not in LINEAGE_AWARE_FEATURE_VERSIONS


def test_the_snapshot_records_the_lens_that_was_applied() -> None:
    snapshot = input_snapshot(_operation(), VehicleLineage("Truck Crane 01", "Crane", "Crane"))

    assert snapshot["vehicle"] == "Truck Crane 01"
    assert snapshot["vehicle_type"] == "Crane"
    assert snapshot["vehicle_group"] == "Crane"
    assert input_snapshot(_operation(None), VehicleLineage.unknown())["vehicle_group"] == (
        UNKNOWN_VEHICLE
    )


_HISTORY = (
    b"Kategori ANGBER,Kendaraan,Mode Aktivitas,Jam Lifting,Jarak Total (km),"
    b"Bahan Bakar Disiapkan (L),Sumber Jarak\n"
    b"ANGBER,Truck Crane 01,transport,,20,18,manual\n"
    b"ANGBER,Truck Crane 01,transport,,40,28,manual\n"
    b"ANGBER,Prime Mover,transport,,20,26,manual\n"
    b"ANGBER,Prime Mover,transport,,40,44,manual\n"
)


def test_a_planner_names_only_the_unit_and_the_stored_prediction_carries_its_lineage(
    tmp_path: Path,
) -> None:
    app = create_app(
        database_path=tmp_path / "operations.sqlite3", vehicle_catalog=PackagedVehicleCatalog()
    )
    with TestClient(app) as client:
        dataset = client.post(
            "/api/v1/historical-datasets", files={"file": ("riwayat.csv", _HISTORY, "text/csv")}
        ).json()["dataset_version"]
        candidate = client.post(
            f"/api/v1/dataset-versions/{dataset['dataset_version_id']}/baseline-candidates"
        ).json()
        assert (
            client.post(
                f"/api/v1/model-candidates/{candidate['model_version_id']}/promote"
            ).status_code
            == 200
        )

        # The request names the unit and nothing else about it — here by an
        # alias, as the sheets write it. The operation records the canonical
        # name (ADR 0015), as the form's select and an agent's words already
        # did; the lineage resolves from it.
        operation = client.post(
            "/api/v1/daily-operations",
            json={
                "vehicle_category": "ANGBER",
                "vehicle": "t crane 01",
                "activity_mode": "transport",
                "total_distance_km": 30,
                "distance_source": "manual",
            },
        )
        assert operation.status_code == 201, operation.text
        prediction = client.post(
            f"/api/v1/daily-operations/{operation.json()['operation_id']}/predictions"
        )

    assert prediction.status_code == 201, prediction.text
    body = prediction.json()
    assert body["input_snapshot"]["vehicle"] == "Truck Crane 01"
    assert body["input_snapshot"]["vehicle_type"] == "Scania P410B 8x4"
    assert body["input_snapshot"]["vehicle_group"] == "Crane"
    assert "vehicle_type" not in body["feature_values"]
    assert "vehicle_group" not in body["feature_values"]


# --- similar operations ------------------------------------------------------------


class _Fleet:
    def __init__(self, *options: VehicleOption) -> None:
        self._options = options

    def options(self) -> tuple[VehicleOption, ...]:
        return self._options

    def find(self, name: str) -> VehicleOption | None:
        wanted = name.strip().casefold().replace(" ", "")
        for option in self._options:
            if wanted in {s.casefold().replace(" ", "") for s in (option.name, *option.aliases)}:
                return option
        return None

    def lineage_of(self, name: str | None) -> VehicleLineage:
        found = self.find(name) if name else None
        return found.lineage if found is not None else VehicleLineage.unknown()


class _History:
    def __init__(self, *rows: HistoricalOperationRecord) -> None:
        self._rows = rows

    def dataset_operations(
        self, vehicle_category: VehicleCategory
    ) -> tuple[HistoricalOperationRecord, ...]:
        return self._rows

    def recorded_operations(
        self, vehicle_category: VehicleCategory
    ) -> tuple[HistoricalOperationRecord, ...]:
        return ()


def _row(operation_id: str, vehicle: str | None) -> HistoricalOperationRecord:
    return HistoricalOperationRecord(
        source=HistorySource.DATASET,
        operation_id=operation_id,
        vehicle=vehicle,
        vehicle_category=VehicleCategory.ANGBER,
        activity_mode=ActivityMode.TRANSPORT,
        lifting_hours=None,
        total_distance_km=30.0,
        distance_source=DistanceSource.MANUAL,
        prepared_fuel_liters=20.0,
    )


def test_with_two_types_in_a_group_the_same_type_outranks_the_same_group() -> None:
    fleet = _Fleet(
        VehicleOption("VT 01", "Vacuum Truck", (), type="VT A"),
        VehicleOption("VT 02", "Vacuum Truck", (), type="VT A"),
        VehicleOption("VT 09", "Vacuum Truck", (), type="VT B"),
        VehicleOption("Prime Mover", "Truck", ()),
    )
    history = _History(
        _row("truck", "Prime Mover"),
        _row("vt-b", "VT 09"),
        _row("vt-a-other", "VT 02"),
        _row("this", "VT 01"),
        _row("unnamed", None),
    )

    results = FindSimilarOperations(history, fleet).execute(
        SimilarOperationsQuery(vehicle="vt 01", total_distance_km=30)
    )

    assert [item.record.operation_id for item in results] == ["this", "vt-a-other", "vt-b"]
    assert [item.match.vehicle for item in results] == [
        VehicleMatch.SAME,
        VehicleMatch.SAME_TYPE,
        VehicleMatch.SAME_GROUP,
    ]
    assert (results[1].vehicle_type, results[1].vehicle_group) == ("VT A", "Vacuum Truck")
    assert (results[2].vehicle_type, results[2].vehicle_group) == ("VT B", "Vacuum Truck")


def test_with_one_type_per_group_the_ranking_and_its_labels_are_what_they_were() -> None:
    """Today's fleet: the type is the group, so a type match would say nothing
    a group match does not. Existing clients keep seeing `same_group`."""
    fleet = _Fleet(
        VehicleOption("Truck Crane 01", "Crane", ("T CRANE 01",)),
        VehicleOption("Truck Crane 02", "Crane", ()),
        VehicleOption("Prime Mover", "Truck", ()),
    )
    history = _History(
        _row("truck", "Prime Mover"),
        _row("other-crane", "Truck Crane 02"),
        _row("this", "Truck Crane 01"),
    )

    results = FindSimilarOperations(history, fleet).execute(
        SimilarOperationsQuery(vehicle="truck crane 01", total_distance_km=30)
    )

    assert [item.record.operation_id for item in results] == ["this", "other-crane"]
    assert results[1].match.vehicle is VehicleMatch.SAME_GROUP


# --- the catalog fingerprint and the taxonomy alert --------------------------------


def test_the_fingerprint_ignores_row_and_alias_order_and_notices_a_retyping() -> None:
    a = VehicleOption("VT 01", "Vacuum Truck", ("VT01", "VT-01"))
    b = VehicleOption("Truck Crane 01", "Crane", ("T CRANE 01",))

    same = catalog_fingerprint((b, VehicleOption("VT 01", "Vacuum Truck", ("VT-01", "VT01"))))
    retyped = catalog_fingerprint((a, VehicleOption("Truck Crane 01", "Crane", (), type="Crane B")))

    assert catalog_fingerprint((a, b)) == same
    assert catalog_fingerprint((a, b)) != retyped
    assert len(same) == 64


def test_a_model_trained_here_records_the_fingerprint(tmp_path: Path) -> None:
    catalog = PackagedVehicleCatalog()
    app = create_app(database_path=tmp_path / "operations.sqlite3", vehicle_catalog=catalog)
    with TestClient(app) as client:
        dataset = client.post(
            "/api/v1/historical-datasets", files={"file": ("riwayat.csv", _HISTORY, "text/csv")}
        ).json()["dataset_version"]
        candidate = client.post(
            f"/api/v1/dataset-versions/{dataset['dataset_version_id']}/baseline-candidates"
        )

    assert candidate.status_code == 201, candidate.text
    assert candidate.json()["catalog_fingerprint"] == catalog_fingerprint(catalog.options())


class _EditableFleet(_Fleet):
    """A catalog the owner edits after a model was trained on it."""

    def retype(self, name: str, new_type: str) -> None:
        self._options = tuple(
            VehicleOption(o.name, o.group, o.aliases, type=new_type) if o.name == name else o
            for o in self._options
        )


def _trained_app_with(fleet: _EditableFleet, tmp_path: Path) -> TestClient:
    app = create_app(database_path=tmp_path / "operations.sqlite3", vehicle_catalog=fleet)
    client = TestClient(app)
    client.__enter__()
    dataset = client.post(
        "/api/v1/historical-datasets", files={"file": ("riwayat.csv", _HISTORY, "text/csv")}
    ).json()["dataset_version"]
    candidate = client.post(
        f"/api/v1/dataset-versions/{dataset['dataset_version_id']}/baseline-candidates"
    ).json()
    promoted = client.post(f"/api/v1/model-candidates/{candidate['model_version_id']}/promote")
    assert promoted.status_code == 200, promoted.text
    return client


def _fleet() -> _EditableFleet:
    return _EditableFleet(
        VehicleOption("Truck Crane 01", "Crane", ("T CRANE 01",)),
        VehicleOption("Prime Mover", "Truck", ()),
    )


def _alert_kinds(client: TestClient) -> set[str]:
    dashboard = client.get("/api/v1/monitoring-dashboard")
    assert dashboard.status_code == 200, dashboard.text
    return {alert["kind"] for alert in dashboard.json()["active_alerts"]}


def test_retyping_the_fleet_under_a_lineage_aware_model_raises_the_alert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import fuel_predictor.application.monitoring as monitoring

    monkeypatch.setattr(monitoring, "LINEAGE_AWARE_FEATURE_VERSIONS", frozenset({FEATURE_VERSION}))
    fleet = _fleet()
    with _trained_app_with(fleet, tmp_path) as client:
        assert "vehicle_taxonomy" not in _alert_kinds(client)

        fleet.retype("Truck Crane 01", "Crane besar")

        assert "vehicle_taxonomy" in _alert_kinds(client)
        page = client.get("/pemantauan/kesehatan-sistem")
    assert "Penggolongan kendaraan berubah sejak model dilatih" in page.text


def test_retyping_the_fleet_under_baseline_v2_is_silent(tmp_path: Path) -> None:
    """v2 reads the unit alone; a re-typing cannot change what it predicts."""
    fleet = _fleet()
    with _trained_app_with(fleet, tmp_path) as client:
        fleet.retype("Truck Crane 01", "Crane besar")

        assert "vehicle_taxonomy" not in _alert_kinds(client)


# --- the estimate page shows what the unit needed before ------------------------------


def _save_operation(client: TestClient, vehicle: str, distance: str = "30") -> Any:
    return client.post(
        "/operasi-harian",
        content=urlencode(
            [
                ("vehicle_category", "ANGBER"),
                ("vehicle", vehicle),
                ("activity_mode", "transport"),
                ("total_distance_km", distance),
                ("distance_source", "manual"),
            ]
        ),
        headers={"content-type": "application/x-www-form-urlencoded"},
    )


def test_the_estimate_page_lists_similar_operations_with_why_they_are_shown(
    tmp_path: Path,
) -> None:
    catalog = _Fleet(
        VehicleOption("Truck Crane 01", "Crane", ("T CRANE 01",)),
        VehicleOption("Truck Crane 02", "Crane", ()),
        VehicleOption("Prime Mover", "Truck", ()),
    )
    app = create_app(database_path=tmp_path / "operations.sqlite3", vehicle_catalog=catalog)
    with TestClient(app) as client:
        dataset = client.post(
            "/api/v1/historical-datasets", files={"file": ("riwayat.csv", _HISTORY, "text/csv")}
        ).json()["dataset_version"]
        candidate = client.post(
            f"/api/v1/dataset-versions/{dataset['dataset_version_id']}/baseline-candidates"
        ).json()
        promoted = client.post(f"/api/v1/model-candidates/{candidate['model_version_id']}/promote")
        assert promoted.status_code == 200, promoted.text

        # The first plan for the other crane has only the imported history to
        # lean on; the second plan for the same unit also sees the first.
        first = _save_operation(client, "Truck Crane 02", "35")
        second = _save_operation(client, "Truck Crane 02", "36")

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert "Operasi serupa sebelumnya" in first.text
    assert "Grup yang sama" in first.text  # Truck Crane 01 rows from the dataset
    assert "Unit yang sama" not in first.text
    assert "Unit yang sama" in second.text  # the plan saved a moment ago
    assert "35 km" in second.text
    assert "dicatat" in second.text and "riwayat" in second.text


def test_a_unit_with_no_kin_in_history_is_told_so_rather_than_shown_other_machines(
    tmp_path: Path,
) -> None:
    catalog = _Fleet(
        VehicleOption("Forklift SCM", "Forklift", ()),
        VehicleOption("Truck Crane 01", "Crane", ()),
        VehicleOption("Prime Mover", "Truck", ()),
    )
    app = create_app(database_path=tmp_path / "operations.sqlite3", vehicle_catalog=catalog)
    with TestClient(app) as client:
        dataset = client.post(
            "/api/v1/historical-datasets", files={"file": ("riwayat.csv", _HISTORY, "text/csv")}
        ).json()["dataset_version"]
        candidate = client.post(
            f"/api/v1/dataset-versions/{dataset['dataset_version_id']}/baseline-candidates"
        ).json()
        assert (
            client.post(
                f"/api/v1/model-candidates/{candidate['model_version_id']}/promote"
            ).status_code
            == 200
        )
        page = _save_operation(client, "Forklift SCM")

    assert page.status_code == 200, page.text
    # No forklift has ever been recorded. Cranes and a prime mover are not
    # comparable, so the page says there is nothing yet instead of listing them.
    assert "Operasi serupa sebelumnya" in page.text
    assert "Belum ada catatan untuk unit ini" in page.text
    assert "Truck Crane 01" not in page.text.split("Operasi serupa sebelumnya", 1)[1]

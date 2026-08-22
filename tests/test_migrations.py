from pathlib import Path

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import inspect

from alembic import command
from fuel_predictor.main import create_app


def test_migrations_create_daily_operation_dataset_and_prediction_lineage_tables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'migration.sqlite3').as_posix()}"
    monkeypatch.setenv("FUEL_PREDICTOR_DATABASE_URL", database_url)
    config = Config("alembic.ini")

    command.upgrade(config, "head")

    with TestClient(create_app(database_url=database_url)) as client:
        created = client.post(
            "/api/v1/daily-operations",
            json={
                "vehicle_category": "ANGBER",
                "activity_mode": "transport",
                "lifting_hours": None,
                "total_distance_km": 15,
                "distance_source": "manual",
            },
        )
        imported = client.post(
            "/api/v1/historical-datasets",
            files={
                "file": (
                    "riwayat.csv",
                    (
                        b"Kategori ANGBER,Mode Aktivitas,Jam Lifting,Jarak Total (km),"
                        b"Bahan Bakar Disiapkan (L),Sumber Jarak\n"
                        b"ANGBER,transport,,22,18,manual\n"
                    ),
                    "text/csv",
                )
            },
        )

    assert created.status_code == 201
    assert imported.status_code == 201
    assert imported.json()["dataset_version"]["dataset_version_id"] == "DSV-000001"

    from sqlalchemy import create_engine

    with create_engine(database_url).connect() as connection:
        table_names = set(inspect(connection).get_table_names())
    assert {
        "alembic_version",
        "daily_operations",
        "daily_operation_sources",
        "daily_operation_stops",
        "dataset_versions",
        "historical_daily_operations",
        "data_quality_issues",
        "model_versions",
        "predictions",
        "actual_fuel_records",
        "monitoring_alerts",
    } <= table_names

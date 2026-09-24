"""Every model version has a code people can read, and every prediction says which
model made it.

`MDL-A4F91FE81A25440F90040335B95D45D0` identified a model to the database and
to nobody else. A model now gets `M-260924-01` when it comes out of training -
the day it finished, in site time, and its place among that day's models - so
a planner can say which model an estimate came from, and performance can be
read per model.
"""

from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from alembic import command
from fuel_predictor.domain.model_code import model_code
from fuel_predictor.domain.prediction import ModelLifecycleStatus, ModelVersion
from fuel_predictor.infrastructure.database import (
    ModelVersionRow,
    PredictionRow,
    build_engine,
    build_session_factory,
    create_schema_for_tests,
)
from fuel_predictor.infrastructure.sqlalchemy_predictions import SqlAlchemyPredictionRepository
from fuel_predictor.main import create_app
from tests.test_actual_fuel_outcomes import _operation_with_prediction, _train_baseline

_JAKARTA = ZoneInfo("Asia/Jakarta")


def test_the_code_is_the_day_training_finished_and_its_place_that_day() -> None:
    assert model_code(date(2026, 9, 24), 1) == "M-260924-01"
    assert model_code(date(2026, 9, 24), 12) == "M-260924-12"


def _repository(tmp_path: Path) -> SqlAlchemyPredictionRepository:
    engine = build_engine(f"sqlite+pysqlite:///{(tmp_path / 'models.sqlite3').as_posix()}")
    create_schema_for_tests(engine)
    return SqlAlchemyPredictionRepository(build_session_factory(engine), site_timezone=_JAKARTA)


def _model(model_version_id: str, trained_at: datetime) -> ModelVersion:
    return ModelVersion(
        model_version_id=model_version_id,
        version=0,
        dataset_version_id="DSV-000001",
        feature_version="baseline-v2",
        algorithm="linear_regression",
        artifact_uri="memory://model",
        trained_at=trained_at,
        training_row_count=10,
        uncertainty_liters=3.0,
        lifecycle_status=ModelLifecycleStatus.CANDIDATE,
    )


def test_models_finished_the_same_site_day_are_numbered_in_order(tmp_path: Path) -> None:
    repository = _repository(tmp_path)

    first = repository.create(_model("MDL-A", datetime(2026, 9, 24, 2, 0, tzinfo=UTC)))
    second = repository.create(_model("MDL-B", datetime(2026, 9, 24, 9, 0, tzinfo=UTC)))
    # 23:30 UTC on the 23rd is already the 24th in Jakarta.
    third = repository.create(_model("MDL-C", datetime(2026, 9, 23, 23, 30, tzinfo=UTC)))
    other_day = repository.create(_model("MDL-D", datetime(2026, 9, 25, 2, 0, tzinfo=UTC)))

    assert [first.model_code, second.model_code, third.model_code] == [
        "M-260924-01",
        "M-260924-02",
        "M-260924-03",
    ]
    assert other_day.model_code == "M-260925-01"
    stored = repository.get("MDL-B")
    assert stored is not None
    assert stored.model_code == "M-260924-02"


def test_a_package_may_be_named_as_long_as_its_contract_allows(tmp_path: Path) -> None:
    """The manifest allows 64 characters; the columns used to hold 40, so a
    longer name validated and then failed to register on PostgreSQL."""
    name = "rule-data-ratio-reserve-DSV-20260924-8485d134"
    assert len(name) > 40

    repository = _repository(tmp_path)
    repository.create(_model(name, datetime(2026, 9, 24, tzinfo=UTC)))

    assert repository.get(name) is not None
    for column in (
        ModelVersionRow.__table__.c.model_version_id,
        PredictionRow.__table__.c.model_version_id,
    ):
        assert column.type.length >= 64  # type: ignore[attr-defined]


def test_a_prediction_names_its_model_by_code(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_baseline(client)
        prediction = _operation_with_prediction(client, 24)["prediction"]
        history = client.get("/riwayat-prediksi").text

    code = prediction["model"]["model_code"]
    assert code.startswith("M-")
    assert code in history


def test_the_migration_codes_existing_models_in_the_order_they_were_made(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'migration.sqlite3').as_posix()}"
    monkeypatch.setenv("FUEL_PREDICTOR_DATABASE_URL", database_url)
    monkeypatch.delenv("FUEL_PREDICTOR_SITE_TIMEZONE", raising=False)
    config = Config("alembic.ini")
    command.upgrade(config, "20260924_29")
    engine = create_engine(database_url)
    insert = text(
        "INSERT INTO model_versions (model_version_id, dataset_version_id, feature_version,"
        " algorithm, artifact_uri, trained_at, training_row_count, uncertainty_liters,"
        " lifecycle_status) VALUES (:id, 'DSV-1', 'baseline-v2', 'linear_regression', 'x',"
        " :trained_at, 10, 3.0, 'candidate')"
    )
    with engine.begin() as connection:
        for model_version_id, trained_at in (
            ("MDL-FIRST", "2026-09-11 02:00:00"),
            ("MDL-SECOND", "2026-09-11 05:00:00"),
            ("MDL-LATER", "2026-09-20 23:30:00"),
        ):
            connection.execute(insert, {"id": model_version_id, "trained_at": trained_at})

    command.upgrade(config, "head")

    with engine.connect() as connection:
        codes = dict(
            connection.execute(text("SELECT model_version_id, model_code FROM model_versions"))
            .tuples()
            .all()
        )
    assert codes == {
        "MDL-FIRST": "M-260911-01",
        "MDL-SECOND": "M-260911-02",
        # 23:30 UTC is the next morning in Jakarta.
        "MDL-LATER": "M-260921-01",
    }

    command.downgrade(config, "20260924_29")
    with engine.connect() as connection:
        columns = [row[1] for row in connection.execute(text("PRAGMA table_info(model_versions)"))]
    assert "model_code" not in columns

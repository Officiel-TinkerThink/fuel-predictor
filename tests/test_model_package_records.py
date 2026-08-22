"""Persisted validation verdicts (plan validation step 9)."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from fuel_predictor.application.model_package_records import (
    ModelPackageValidationRecord,
    ValidationOutcome,
)
from fuel_predictor.infrastructure.database import (
    build_engine,
    build_session_factory,
    create_schema_for_tests,
)
from fuel_predictor.infrastructure.sqlalchemy_model_package_records import (
    SqlAlchemyModelPackageValidationRepository,
)

_NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


@pytest.fixture
def repository(tmp_path: Path) -> SqlAlchemyModelPackageValidationRepository:
    engine = build_engine(f"sqlite+pysqlite:///{(tmp_path / 'records.sqlite3').as_posix()}")
    create_schema_for_tests(engine)
    return SqlAlchemyModelPackageValidationRepository(build_session_factory(engine))


def _record(
    validation_id: str = "VAL-1",
    outcome: ValidationOutcome = ValidationOutcome.VALIDATED,
    **overrides: object,
) -> ModelPackageValidationRecord:
    values: dict[str, object] = {
        "validation_id": validation_id,
        "model_version": "fuel-model-2026.08.22.1",
        "validated_at": _NOW,
        "actor": "admin",
        "outcome": outcome,
        "eligible": outcome is ValidationOutcome.VALIDATED,
        "reasons": (),
        "warnings": (),
        "manifest": {"model_version": "fuel-model-2026.08.22.1"},
        "artifact_path": "/models/fuel-model-2026.08.22.1/model.skops",
    }
    values.update(overrides)
    return ModelPackageValidationRecord(**values)  # type: ignore[arg-type]


def test_a_validated_package_round_trips(
    repository: SqlAlchemyModelPackageValidationRepository,
) -> None:
    repository.add(_record())

    stored = repository.get("VAL-1")

    assert stored is not None
    assert stored.was_accepted is True
    assert stored.actor == "admin"
    assert stored.validated_at == _NOW
    assert stored.manifest == {"model_version": "fuel-model-2026.08.22.1"}


def test_a_rejection_is_recorded_with_its_reasons(
    repository: SqlAlchemyModelPackageValidationRepository,
) -> None:
    """Why a package was refused must survive; that is the question asked later."""
    repository.add(
        _record(
            validation_id="VAL-2",
            outcome=ValidationOutcome.REJECTED,
            reasons=("checksum model.skops tidak cocok",),
            eligible=False,
        )
    )

    stored = repository.get("VAL-2")

    assert stored is not None
    assert stored.was_accepted is False
    assert stored.reasons == ("checksum model.skops tidak cocok",)


def test_a_package_rejected_before_its_manifest_parsed_still_records(
    repository: SqlAlchemyModelPackageValidationRepository,
) -> None:
    """No manifest to store is not a reason to store nothing."""
    repository.add(
        _record(
            validation_id="VAL-3",
            outcome=ValidationOutcome.REJECTED,
            model_version="(tidak diketahui)",
            manifest=None,
            artifact_path=None,
            reasons=("Berkas bukan arsip ZIP yang valid.",),
            eligible=False,
        )
    )

    stored = repository.get("VAL-3")

    assert stored is not None
    assert stored.manifest is None
    assert stored.reasons == ("Berkas bukan arsip ZIP yang valid.",)


def test_recent_records_come_back_newest_first(
    repository: SqlAlchemyModelPackageValidationRepository,
) -> None:
    for index, offset_hours in enumerate((0, 5, 2)):
        repository.add(
            _record(
                validation_id=f"VAL-{index}",
                validated_at=_NOW.replace(hour=1 + offset_hours),
            )
        )

    recent = repository.list_recent(limit=10)

    assert [record.validation_id for record in recent] == ["VAL-1", "VAL-2", "VAL-0"]


def test_the_limit_is_respected(
    repository: SqlAlchemyModelPackageValidationRepository,
) -> None:
    for index in range(5):
        repository.add(_record(validation_id=f"VAL-{index}"))

    assert len(repository.list_recent(limit=2)) == 2


def test_an_unknown_validation_id_returns_nothing(
    repository: SqlAlchemyModelPackageValidationRepository,
) -> None:
    assert repository.get("VAL-NEVER") is None


def test_the_migration_creates_the_same_shape_the_orm_expects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Guards against the ORM model and the Alembic revision drifting apart.

    They are written by hand in two places, so nothing but a check like this
    stops a column added to one from being missing in the other.

    Sets the URL through the environment rather than Alembic's config,
    because `alembic/env.py` deliberately reads it from `ApplicationSettings`
    and would otherwise override whatever the config said and try to reach
    the real PostgreSQL.
    """
    from alembic.config import Config

    from alembic import command

    database = tmp_path / "migrated.sqlite3"
    database_url = f"sqlite+pysqlite:///{database.as_posix()}"
    monkeypatch.setenv("FUEL_PREDICTOR_DATABASE_URL", database_url)
    command.upgrade(Config("alembic.ini"), "head")

    factory: sessionmaker[Session] = build_session_factory(build_engine(database_url))
    repository = SqlAlchemyModelPackageValidationRepository(factory)

    repository.add(_record(validation_id="VAL-MIGRATED"))

    stored = repository.get("VAL-MIGRATED")
    assert stored is not None
    assert stored.model_version == "fuel-model-2026.08.22.1"

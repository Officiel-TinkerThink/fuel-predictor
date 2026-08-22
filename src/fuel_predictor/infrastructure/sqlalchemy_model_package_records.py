from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import select

from fuel_predictor.application.model_package_records import (
    ModelPackageValidationRecord,
    ValidationOutcome,
)
from fuel_predictor.infrastructure.database import ModelPackageValidationRow, SessionFactory


class SqlAlchemyModelPackageValidationRepository:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def add(self, record: ModelPackageValidationRecord) -> None:
        with self._session_factory.begin() as session:
            session.add(
                ModelPackageValidationRow(
                    validation_id=record.validation_id,
                    model_version=record.model_version,
                    validated_at=record.validated_at,
                    actor=record.actor,
                    outcome=str(record.outcome),
                    eligible=record.eligible,
                    reasons=list(record.reasons),
                    warnings=list(record.warnings),
                    manifest=record.manifest,
                    artifact_path=record.artifact_path,
                )
            )

    def list_recent(self, limit: int) -> tuple[ModelPackageValidationRecord, ...]:
        with self._session_factory() as session:
            rows = (
                session.execute(
                    select(ModelPackageValidationRow)
                    .order_by(
                        ModelPackageValidationRow.validated_at.desc(),
                        ModelPackageValidationRow.validation_id.desc(),
                    )
                    .limit(limit)
                )
                .scalars()
                .all()
            )
        return tuple(_record(row) for row in rows)

    def get(self, validation_id: str) -> ModelPackageValidationRecord | None:
        with self._session_factory() as session:
            row = session.get(ModelPackageValidationRow, validation_id)
            return _record(row) if row is not None else None


def _record(row: ModelPackageValidationRow) -> ModelPackageValidationRecord:
    return ModelPackageValidationRecord(
        validation_id=row.validation_id,
        model_version=row.model_version,
        validated_at=_aware(row.validated_at),
        actor=row.actor,
        outcome=ValidationOutcome(row.outcome),
        eligible=row.eligible,
        reasons=tuple(row.reasons),
        warnings=tuple(row.warnings),
        manifest=cast("dict[str, Any] | None", row.manifest),
        artifact_path=row.artifact_path,
    )


def _aware(moment: datetime) -> datetime:
    """SQLite loses the timezone PostgreSQL preserves; normalise to UTC."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)

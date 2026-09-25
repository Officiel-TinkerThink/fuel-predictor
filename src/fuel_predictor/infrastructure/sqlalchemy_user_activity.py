from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select

from fuel_predictor.application.user_directory import RecentOperation
from fuel_predictor.infrastructure.database import (
    ActualFuelRecordRow,
    DailyOperationRow,
    SessionFactory,
)


class SqlAlchemyUserActivityRepository:
    """Per-author counts over the operations and actual records people made."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def operation_counts(self, since: datetime | None) -> dict[str, int]:
        query = (
            select(DailyOperationRow.created_by, func.count())
            .where(DailyOperationRow.created_by.is_not(None))
            .group_by(DailyOperationRow.created_by)
        )
        if since is not None:
            query = query.where(DailyOperationRow.created_at >= since)
        with self._session_factory() as session:
            return {author: int(count) for author, count in session.execute(query).all()}

    def actual_counts(self, since: datetime | None) -> dict[str, int]:
        query = (
            select(ActualFuelRecordRow.recorded_by, func.count())
            .where(ActualFuelRecordRow.recorded_by.is_not(None))
            .group_by(ActualFuelRecordRow.recorded_by)
        )
        if since is not None:
            query = query.where(ActualFuelRecordRow.recorded_at >= since)
        with self._session_factory() as session:
            return {author: int(count) for author, count in session.execute(query).all()}

    def recent_operations_by(self, username: str, limit: int) -> Sequence[RecentOperation]:
        with self._session_factory() as session:
            rows = session.execute(
                select(
                    DailyOperationRow.operation_id,
                    DailyOperationRow.operation_code,
                    DailyOperationRow.created_at,
                    DailyOperationRow.vehicle,
                    DailyOperationRow.total_distance_km,
                    ActualFuelRecordRow.operation_id.is_not(None).label("has_actual"),
                    DailyOperationRow.cancelled_at.is_not(None).label("cancelled"),
                )
                .outerjoin(
                    ActualFuelRecordRow,
                    ActualFuelRecordRow.operation_id == DailyOperationRow.operation_id,
                )
                .where(DailyOperationRow.created_by == username)
                .order_by(
                    DailyOperationRow.created_at.desc(), DailyOperationRow.operation_id.desc()
                )
                .limit(limit)
            ).all()
        return [
            RecentOperation(
                operation_id=row.operation_id,
                created_at=row.created_at,
                vehicle=row.vehicle,
                total_distance_km=row.total_distance_km,
                has_actual=bool(row.has_actual),
                operation_code=row.operation_code,
                cancelled=bool(row.cancelled),
            )
            for row in rows
        ]

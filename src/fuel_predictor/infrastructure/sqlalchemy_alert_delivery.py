"""Persisted record of which alerts have already been sent (Phase 3)."""

from datetime import datetime

from sqlalchemy import delete, select

from fuel_predictor.infrastructure.database import AlertNotificationRow, SessionFactory


class SqlAlchemyAlertDeliveryStore:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def outstanding(self) -> dict[str, str]:
        with self._session_factory() as session:
            rows = session.execute(select(AlertNotificationRow)).scalars().all()
        return {row.alert_key: row.severity for row in rows}

    def record_sent(self, alert_key: str, severity: str, sent_at: datetime) -> None:
        with self._session_factory.begin() as session:
            row = session.get(AlertNotificationRow, alert_key)
            if row is None:
                session.add(
                    AlertNotificationRow(
                        alert_key=alert_key, severity=severity, sent_at=sent_at
                    )
                )
                return
            row.severity = severity
            row.sent_at = sent_at

    def clear(self, alert_key: str) -> None:
        with self._session_factory.begin() as session:
            session.execute(
                delete(AlertNotificationRow).where(AlertNotificationRow.alert_key == alert_key)
            )

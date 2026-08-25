"""Delivering monitoring alerts somewhere an operator will actually see them.

Recording an alert in the database is not delivery: nobody watches a dashboard
they have no reason to open. This sends a message when the alerting picture
*changes* — a new alert, one that changed severity, or one that cleared — and
stays silent otherwise, because a job that mails the same warning every hour
trains its reader to ignore it.

Delivery state is persisted rather than kept in memory: the monitoring job is a
separate short-lived process, so an in-memory record of "already told them"
would be empty on every run.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from fuel_predictor.domain.alert_remediation import remediation_for, urgency_for
from fuel_predictor.domain.monitoring import MonitoringAlert


@dataclass(frozen=True, slots=True)
class AlertNotification:
    subject: str
    body: str


class AlertNotifier(Protocol):
    """Sends one notification. Raises if it could not be delivered."""

    def send(self, notification: AlertNotification) -> None: ...

    @property
    def is_configured(self) -> bool: ...


class AlertDeliveryStore(Protocol):
    def outstanding(self) -> Mapping[str, str]:
        """Alert keys already notified, mapped to the severity last sent."""
        ...

    def record_sent(self, alert_key: str, severity: str, sent_at: datetime) -> None: ...

    def clear(self, alert_key: str) -> None: ...


@dataclass(frozen=True, slots=True)
class AlertDeliveryResult:
    sent: bool
    reason: str
    new_alerts: tuple[str, ...] = ()
    changed_alerts: tuple[str, ...] = ()
    resolved_alerts: tuple[str, ...] = ()
    error: str | None = None


@dataclass(frozen=True, slots=True)
class DeliverMonitoringAlerts:
    notifier: AlertNotifier
    store: AlertDeliveryStore

    def execute(
        self, active_alerts: Sequence[MonitoringAlert], now: datetime
    ) -> AlertDeliveryResult:
        outstanding = dict(self.store.outstanding())
        current = {alert.alert_key: alert for alert in active_alerts}

        new = tuple(key for key in current if key not in outstanding)
        changed = tuple(
            key
            for key, alert in current.items()
            if key in outstanding and outstanding[key] != str(alert.severity)
        )
        resolved = tuple(key for key in outstanding if key not in current)

        if not (new or changed or resolved):
            return AlertDeliveryResult(sent=False, reason="tidak ada perubahan")

        if not self.notifier.is_configured:
            # Said plainly rather than swallowed. An unconfigured channel is
            # the difference between "nothing is wrong" and "nobody is being
            # told", and those must never look the same in a log.
            return AlertDeliveryResult(
                sent=False,
                reason="saluran pemberitahuan belum dikonfigurasi",
                new_alerts=new,
                changed_alerts=changed,
                resolved_alerts=resolved,
            )

        notification = _compose(
            [current[key] for key in new],
            [current[key] for key in changed],
            resolved,
            now,
        )
        try:
            self.notifier.send(notification)
        except Exception as error:  # noqa: BLE001 - reported, and retried next run
            # Nothing is recorded as sent, so the next run tries again. A
            # delivery failure must not mark these alerts as handled.
            return AlertDeliveryResult(
                sent=False,
                reason="pengiriman gagal",
                new_alerts=new,
                changed_alerts=changed,
                resolved_alerts=resolved,
                error=f"{type(error).__name__}: {error}",
            )

        for key in new + changed:
            self.store.record_sent(key, str(current[key].severity), now)
        for key in resolved:
            self.store.clear(key)

        return AlertDeliveryResult(
            sent=True,
            reason="terkirim",
            new_alerts=new,
            changed_alerts=changed,
            resolved_alerts=resolved,
        )


def _compose(
    new: Sequence[MonitoringAlert],
    changed: Sequence[MonitoringAlert],
    resolved: Sequence[str],
    now: datetime,
) -> AlertNotification:
    worst = _worst_severity(list(new) + list(changed))
    subject = _subject(len(new) + len(changed), len(resolved), worst)

    lines: list[str] = [
        # Numeric, matching the rest of the application. `%B` would render an
        # English month name into an otherwise Indonesian message, because the
        # server process has no Indonesian locale to rely on.
        f"Laporan pemantauan Perencana Operasi Harian — {now:%d/%m/%Y %H:%M}.",
        "",
    ]

    for heading, alerts in (("Peringatan baru", new), ("Perubahan tingkat", changed)):
        if not alerts:
            continue
        lines.append(f"{heading}:")
        for alert in alerts:
            lines.extend(
                [
                    "",
                    f"  [{str(alert.severity).upper()}] {alert.message}",
                    f"  Mendesak: {urgency_for(alert.severity)}",
                    f"  Tindakan: {remediation_for(alert.kind)}",
                ]
            )
        lines.append("")

    if resolved:
        # Closing the loop matters as much as opening it: without this, an
        # operator has no way to know a problem they were told about is over.
        lines.append("Sudah teratasi (tidak perlu tindakan):")
        lines.extend(f"  - {key}" for key in resolved)
        lines.append("")

    lines.append("Rincian lengkap ada di halaman Pemantauan aplikasi.")
    return AlertNotification(subject=subject, body="\n".join(lines))


def _worst_severity(alerts: Sequence[MonitoringAlert]) -> str:
    if any(str(alert.severity) == "critical" for alert in alerts):
        return "KRITIS"
    if alerts:
        return "PERINGATAN"
    return "PEMBARUAN"


def _subject(active_count: int, resolved_count: int, worst: str) -> str:
    if active_count == 0:
        return f"[Pemantauan BBM] {resolved_count} peringatan teratasi"
    parts = [f"[Pemantauan BBM] {worst}: {active_count} peringatan perlu tindakan"]
    if resolved_count:
        parts.append(f"{resolved_count} teratasi")
    return ", ".join(parts)

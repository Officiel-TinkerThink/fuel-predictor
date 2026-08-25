"""Monitoring alerts must reach a person, and must not become noise (Phase 3)."""

from datetime import UTC, datetime

import pytest

from fuel_predictor.application.alert_delivery import (
    AlertNotification,
    DeliverMonitoringAlerts,
)
from fuel_predictor.domain.alert_remediation import remediation_for
from fuel_predictor.domain.monitoring import (
    MonitoringAlert,
    MonitoringAlertKind,
    MonitoringAlertSeverity,
)

_NOW = datetime(2026, 8, 25, 7, 0, tzinfo=UTC)


class _RecordingNotifier:
    def __init__(self, *, configured: bool = True, fails: bool = False) -> None:
        self.sent: list[AlertNotification] = []
        self._configured = configured
        self._fails = fails

    @property
    def is_configured(self) -> bool:
        return self._configured

    def send(self, notification: AlertNotification) -> None:
        if self._fails:
            raise RuntimeError("smtp tidak dapat dihubungi")
        self.sent.append(notification)


class _MemoryStore:
    def __init__(self) -> None:
        self.state: dict[str, str] = {}

    def outstanding(self) -> dict[str, str]:
        return dict(self.state)

    def record_sent(self, alert_key: str, severity: str, sent_at: datetime) -> None:
        self.state[alert_key] = severity

    def clear(self, alert_key: str) -> None:
        self.state.pop(alert_key, None)


def _alert(
    key: str = "drift:baseline-v1",
    kind: MonitoringAlertKind = MonitoringAlertKind.FEATURE_DRIFT,
    severity: MonitoringAlertSeverity = MonitoringAlertSeverity.WARNING,
) -> MonitoringAlert:
    return MonitoringAlert(
        alert_key=key,
        kind=kind,
        severity=severity,
        message="Pergeseran fitur melewati ambang.",
        details={},
        first_observed_at=_NOW,
        last_observed_at=_NOW,
    )


@pytest.fixture
def delivery() -> tuple[DeliverMonitoringAlerts, _RecordingNotifier, _MemoryStore]:
    notifier = _RecordingNotifier()
    store = _MemoryStore()
    return DeliverMonitoringAlerts(notifier=notifier, store=store), notifier, store


def test_a_new_alert_is_sent_with_its_remediation(delivery: tuple) -> None:
    deliver, notifier, _ = delivery

    result = deliver.execute([_alert()], _NOW)

    assert result.sent
    body = notifier.sent[0].body
    # The plan asks for remediation, not just notification: a reader must be
    # told what to do, not only that something is wrong.
    assert remediation_for(MonitoringAlertKind.FEATURE_DRIFT) in body
    assert "Tindakan:" in body


def test_the_same_alert_is_not_sent_again_on_the_next_run(delivery: tuple) -> None:
    """A job that mails the same warning hourly trains its reader to ignore it."""
    deliver, notifier, _ = delivery
    deliver.execute([_alert()], _NOW)

    second = deliver.execute([_alert()], _NOW)

    assert second.sent is False
    assert second.reason == "tidak ada perubahan"
    assert len(notifier.sent) == 1


def test_an_alert_that_escalates_is_sent_again(delivery: tuple) -> None:
    deliver, notifier, _ = delivery
    deliver.execute([_alert()], _NOW)

    result = deliver.execute([_alert(severity=MonitoringAlertSeverity.CRITICAL)], _NOW)

    assert result.sent
    assert result.changed_alerts == ("drift:baseline-v1",)
    assert "KRITIS" in notifier.sent[1].subject


def test_a_resolved_alert_closes_the_loop(delivery: tuple) -> None:
    """Without this, an operator never learns the problem they were told about ended."""
    deliver, notifier, store = delivery
    deliver.execute([_alert()], _NOW)

    result = deliver.execute([], _NOW)

    assert result.sent
    assert result.resolved_alerts == ("drift:baseline-v1",)
    assert "teratasi" in notifier.sent[1].subject.lower()
    assert store.state == {}


def test_a_failed_send_is_reported_and_retried_rather_than_marked_delivered() -> None:
    notifier = _RecordingNotifier(fails=True)
    store = _MemoryStore()
    deliver = DeliverMonitoringAlerts(notifier=notifier, store=store)

    first = deliver.execute([_alert()], _NOW)

    assert first.sent is False
    assert first.error is not None
    # Nothing recorded, so the next run tries again. Recording here would mark
    # an alert handled that nobody ever received.
    assert store.state == {}

    working = _RecordingNotifier()
    retried = DeliverMonitoringAlerts(notifier=working, store=store).execute([_alert()], _NOW)
    assert retried.sent
    assert len(working.sent) == 1


def test_an_unconfigured_channel_says_so_instead_of_looking_like_success() -> None:
    """"No alerts sent" and "nobody is listening" must never look the same."""
    notifier = _RecordingNotifier(configured=False)
    store = _MemoryStore()

    result = DeliverMonitoringAlerts(notifier=notifier, store=store).execute([_alert()], _NOW)

    assert result.sent is False
    assert result.reason == "saluran pemberitahuan belum dikonfigurasi"
    assert result.new_alerts == ("drift:baseline-v1",)
    # Not recorded as sent, so configuring a channel later delivers the backlog
    # rather than starting from a clean slate that hides existing problems.
    assert store.state == {}


def test_nothing_is_sent_when_there_is_nothing_to_say(delivery: tuple) -> None:
    deliver, notifier, _ = delivery

    result = deliver.execute([], _NOW)

    assert result.sent is False
    assert notifier.sent == []


def test_every_alert_kind_has_remediation_text() -> None:
    """A kind with no guidance would ship an alert nobody knows how to act on."""
    for kind in MonitoringAlertKind:
        assert remediation_for(kind).strip()

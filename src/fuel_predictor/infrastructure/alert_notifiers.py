"""Where monitoring alerts are actually sent (Phase 3).

Two channels, both on what the project already depends on: `smtplib` from the
standard library and `httpx`, which is already present. A self-hosted single-VM
deployment should not need a paid notification service to tell its operator that
predictions have started drifting.

Both raise on failure rather than logging and returning. The caller records an
alert as delivered only when `send` returns, so a swallowed exception here would
mark an alert handled that nobody ever received.
"""

import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import TYPE_CHECKING

import httpx

from fuel_predictor.application.alert_delivery import AlertNotification, AlertNotifier

if TYPE_CHECKING:
    from fuel_predictor.configuration import ApplicationSettings


@dataclass(frozen=True, slots=True)
class SmtpAlertNotifier:
    host: str
    port: int
    sender: str
    recipients: tuple[str, ...]
    username: str | None = None
    password: str | None = None
    use_starttls: bool = True
    timeout_seconds: float = 30.0

    @property
    def is_configured(self) -> bool:
        return bool(self.host and self.sender and self.recipients)

    def send(self, notification: AlertNotification) -> None:
        message = EmailMessage()
        message["Subject"] = notification.subject
        message["From"] = self.sender
        message["To"] = ", ".join(self.recipients)
        message.set_content(notification.body)

        with smtplib.SMTP(self.host, self.port, timeout=self.timeout_seconds) as server:
            if self.use_starttls:
                server.starttls()
            if self.username and self.password:
                server.login(self.username, self.password)
            server.send_message(message)


@dataclass(frozen=True, slots=True)
class WebhookAlertNotifier:
    """Posts the alert as JSON to a chat webhook or automation endpoint."""

    url: str
    timeout_seconds: float = 30.0

    @property
    def is_configured(self) -> bool:
        return bool(self.url)

    def send(self, notification: AlertNotification) -> None:
        response = httpx.post(
            self.url,
            json={
                "subject": notification.subject,
                # `text` as well as `body`: the common chat webhooks read a
                # field by that name, and sending both means the same payload
                # works without a per-provider adapter.
                "text": f"{notification.subject}\n\n{notification.body}",
                "body": notification.body,
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()


@dataclass(frozen=True, slots=True)
class UnconfiguredAlertNotifier:
    """Stands in when no channel is set up.

    `send` raises rather than doing nothing: the delivery use case checks
    `is_configured` first and reports the gap plainly, so reaching `send` here
    would mean that check was bypassed — a bug worth surfacing, not hiding.
    """

    @property
    def is_configured(self) -> bool:
        return False

    def send(self, notification: AlertNotification) -> None:
        raise RuntimeError(
            "Saluran pemberitahuan belum dikonfigurasi. Atur FUEL_PREDICTOR_ALERT_* "
            "sebelum mengirim peringatan."
        )


def build_notifier(settings: "ApplicationSettings") -> AlertNotifier:
    """Pick a channel from configuration.

    The webhook wins when both are set: it is the one an operator can point at
    a chat group they already watch, and a message nobody opens is not a
    delivered alert.
    """
    if settings.alert_webhook_url:
        return WebhookAlertNotifier(url=settings.alert_webhook_url)
    recipients = tuple(
        address.strip() for address in settings.alert_email_recipients.split(",") if address.strip()
    )
    if settings.alert_smtp_host and settings.alert_email_sender and recipients:
        password = settings.alert_smtp_password.get_secret_value()
        return SmtpAlertNotifier(
            host=settings.alert_smtp_host,
            port=settings.alert_smtp_port,
            sender=settings.alert_email_sender,
            recipients=recipients,
            username=settings.alert_smtp_username or None,
            password=password or None,
            use_starttls=settings.alert_smtp_use_starttls,
        )
    return UnconfiguredAlertNotifier()

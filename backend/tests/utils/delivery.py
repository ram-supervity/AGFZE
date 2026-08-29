"""Fakes for the two delivery channels  adds, installed at the modules' own seams.

Neither fake reaches a network. `_smtp_send` and `_send_webpush` are the single synchronous calls
each service makes to the outside world, and replacing exactly those keeps everything above them -
rendering, the multipart assembly, the retry schedule, the dead-subscription rule - running for
real in the suite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from email.message import EmailMessage

from app.core.config import settings
from app.services.delivery import email_service, push_service


@dataclass
class FakeRelay:
    """Records what was handed to SMTP, and can refuse a chosen number of attempts."""

    sent: list[EmailMessage] = field(default_factory=list)
    fail_times: int = 0
    attempts: int = 0
    error: Exception | None = None

    def __call__(self, message: EmailMessage) -> None:
        self.attempts += 1
        if self.attempts <= self.fail_times:
            raise self.error or ConnectionRefusedError("The relay refused the connection.")
        self.sent.append(message)

    @property
    def recipients(self) -> list[str]:
        return [message["To"] for message in self.sent]

    def body(self, index: int = 0) -> tuple[str, str]:
        """The plaintext and HTML parts of one sent message, in that order."""
        message = self.sent[index]
        return self._parts(message)

    def for_subject(self, fragment: str) -> tuple[str, str]:
        """The parts of the one message whose subject carries this fragment.

        Indexing by position would be brittle: a single business event legitimately raises more
        than one notification - a failed posting also opens an exception - and this suite should
        assert on the email it means rather than on whichever was sent first.
        """
        matches = [
            message for message in self.sent if fragment.lower() in str(message["Subject"]).lower()
        ]
        assert len(matches) == 1, f"{len(matches)} messages matched {fragment!r}"
        return self._parts(matches[0])

    @staticmethod
    def _parts(message: EmailMessage) -> tuple[str, str]:
        parts = {
            part.get_content_type(): part.get_content()
            for part in message.walk()
            if part.get_content_maintype() == "text"
        }
        return parts["text/plain"], parts["text/html"]


@dataclass
class FakePushService:
    """Records deliveries, and can answer with a status code the way a push service would."""

    delivered: list[tuple[str, str]] = field(default_factory=list)
    status_by_endpoint: dict[str, int] = field(default_factory=dict)
    attempts_by_endpoint: dict[str, int] = field(default_factory=dict)

    def __call__(self, subscription_info: dict, payload: str) -> None:
        endpoint = subscription_info["endpoint"]
        self.attempts_by_endpoint[endpoint] = self.attempts_by_endpoint.get(endpoint, 0) + 1
        status = self.status_by_endpoint.get(endpoint)
        if status is not None:
            raise push_service.PushDeliveryError(f"HTTP {status}", status_code=status)
        self.delivered.append((endpoint, payload))

    @property
    def endpoints(self) -> list[str]:
        return [endpoint for endpoint, _ in self.delivered]


def install_relay(monkeypatch, relay: FakeRelay | None = None, **overrides) -> FakeRelay:
    """Configure a relay for the process and replace the one synchronous SMTP call."""
    relay = relay or FakeRelay()
    monkeypatch.setattr(settings, "SMTP_HOST", overrides.get("host", "smtp.test"))
    monkeypatch.setattr(settings, "SMTP_PORT", overrides.get("port", 587))
    monkeypatch.setattr(settings, "SMTP_FROM_ADDRESS", "command-centre@agfze.test")
    monkeypatch.setattr(settings, "APP_BASE_URL", "https://command-centre.agfze.test")
    monkeypatch.setattr(settings, "EMAIL_RETRY_BASE_SECONDS", 0.0)
    monkeypatch.setattr(email_service, "_smtp_send", relay)
    return relay


def install_push(monkeypatch, service: FakePushService | None = None) -> FakePushService:
    service = service or FakePushService()
    monkeypatch.setattr(settings, "VAPID_PUBLIC_KEY", "test-vapid-public-key")
    monkeypatch.setattr(settings, "VAPID_PRIVATE_KEY", "test-vapid-private-key")
    monkeypatch.setattr(settings, "VAPID_SUBJECT", "mailto:ops@agfze.test")
    monkeypatch.setattr(settings, "APP_BASE_URL", "https://command-centre.agfze.test")
    monkeypatch.setattr(push_service, "_send_webpush", service)
    return service


def record_backoff(monkeypatch) -> list[float]:
    """Capture the retry schedule without waiting it out."""
    waits: list[float] = []

    async def _capture(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr(email_service, "_backoff", _capture)
    return waits


async def subscribe(session, user_id, endpoint: str, *, user_agent: str | None = None):
    return await push_service.upsert_subscription(
        session,
        user_id=user_id,
        endpoint=endpoint,
        p256dh=f"p256dh-{endpoint[-6:]}",
        auth=f"auth-{endpoint[-6:]}",
        user_agent=user_agent,
    )


async def set_channel(session, user, channel: str) -> None:
    user.notification_channel = channel
    await session.flush()

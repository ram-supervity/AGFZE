"""Real HTML email for a notification that has already been created.

Three things this module is careful about, in the order they matter:

* **It never blocks the event it is telling somebody about.** `smtplib` is synchronous, so every
  send runs on a worker thread, and every failure path ends in a logged, audited miss rather than
  an exception travelling back up into the transaction that created the notification.
* **It renders from templates, not from string concatenation.** One base layout carries the
  wordmark, the palette and the footer; each notification type is a named template extending it.
  A new type that has no template of its own falls back to a complete generic email rather than
  to no email at all.
* **It sends both parts.** A multipart/alternative with a real plaintext body, not an HTML body
  with an apology in the text part.
"""

from __future__ import annotations

import asyncio
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.core.config import settings
from app.core.disclaimer import AI_DISCLAIMER_TEXT
from app.core.logging import get_logger

logger = get_logger(__name__)

TEMPLATE_ROOT = Path(__file__).resolve().parent / "templates"

# The disclaimer itself now lives in `core.disclaimer`, imported above. Every channel that prints
# it - this one, and the reply composer - reads the same string without either importing the other,
# which matters structurally: a composer importing the SMTP module for a string would read, in the
# import graph, as a second route to a mail relay. It is not one.

# The template stem per notification type. Anything unmapped renders `generic`.
TEMPLATE_BY_TYPE: dict[str, str] = {
    "exception.opened": "exception_opened",
    "approval.requested": "approval_requested",
    "approval.decided": "approval_decided",
    "integration.attention": "integration_attention",
    "report.ready": "report_ready",
}

# Subjects live here rather than in the templates because a subject is a header, not a body, and
# because a mail client truncates it: it has to lead with what the reader needs.
SUBJECT_BY_TYPE: dict[str, str] = {
    "exception.opened": "An exception needs attention",
    "approval.requested": "A decision is waiting on you",
    "approval.decided": "Your submission has been decided",
    "integration.attention": "An integration job needs a person",
    "report.ready": "A scheduled report is ready",
}

# Which notifications concern content a model produced or read. Those carry the disclaimer; a
# failed downstream posting does not, because nothing about it was inferred.
AI_RELATED_TYPES: frozenset[str] = frozenset(
    {"exception.opened", "approval.requested", "approval.decided", "report.ready"}
)


class EmailDeliveryError(Exception):
    """The relay would not take the message. Never raised beyond this module's own retry loop."""


@dataclass(frozen=True)
class RenderedEmail:
    subject: str
    html: str
    text: str


@lru_cache
def _environment(plaintext: bool = False) -> Environment:
    """Two environments, because whitespace means opposite things in the two parts.

    HTML is rendered with block trimming, which keeps the markup from filling with the newlines
    the template's own control tags would otherwise leave behind. The plaintext part is the
    opposite case entirely: its blank lines *are* the layout, and trimming them would run the
    wordmark, the heading and the summary together into one paragraph.
    """
    return Environment(
        loader=FileSystemLoader(str(TEMPLATE_ROOT)),
        autoescape=False if plaintext else select_autoescape(["html"]),
        trim_blocks=not plaintext,
        lstrip_blocks=not plaintext,
        keep_trailing_newline=True,
    )


def absolute_url(link: str | None) -> str:
    """Turn a notification's relative in-app path into a URL a mail client can open.

    Assembled from `APP_BASE_URL` and nothing else. A link that is not a plain relative path -
    absolute, protocol-relative, or anything a future bug might put there - is refused and the
    reader is sent to their notification centre instead. An email is the one artefact this
    platform produces that it cannot recall, so it never carries an off-platform destination.
    """
    base = settings.APP_BASE_URL.rstrip("/")
    if not link or not link.startswith("/") or link.startswith("//"):
        return f"{base}/notifications"
    return f"{base}{link}"


def render_email(
    notification_type: str, *, recipient_name: str, message: str, link: str | None
) -> RenderedEmail:
    stem = TEMPLATE_BY_TYPE.get(notification_type, "generic")
    subject = SUBJECT_BY_TYPE.get(notification_type, "You have a new notification")
    base = settings.APP_BASE_URL.rstrip("/")
    context = {
        "subject": subject,
        # What a mail client previews beside the subject. The event's own sentence, so the
        # preview is never a truncated greeting.
        "preheader": message,
        "message": message,
        "url": absolute_url(link),
        "centre_url": f"{base}/notifications",
        "settings_url": f"{base}/settings",
        "recipient_name": recipient_name,
        "show_disclaimer": notification_type in AI_RELATED_TYPES,
        "disclaimer": AI_DISCLAIMER_TEXT,
    }
    return RenderedEmail(
        subject=subject,
        html=_environment().get_template(f"{stem}.html").render(context),
        text=_environment(plaintext=True).get_template(f"{stem}.txt").render(context).strip()
        + "\n",
    )


def build_message(to_address: str, rendered: RenderedEmail) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = rendered.subject
    message["From"] = formataddr((settings.SMTP_FROM_NAME, settings.SMTP_FROM_ADDRESS))
    message["To"] = to_address
    # Internal operational mail. Nothing here is a list anybody subscribed to, but an automated
    # message that does not say so is one an out-of-office will happily answer.
    message["Auto-Submitted"] = "auto-generated"
    message.set_content(rendered.text)
    message.add_alternative(rendered.html, subtype="html")
    return message


async def _backoff(seconds: float) -> None:
    """The wait between attempts, as its own seam so the suite can prove the schedule."""
    await asyncio.sleep(seconds)


def _smtp_send(message: EmailMessage) -> None:
    """One synchronous attempt against the configured relay. The seam the suite replaces."""
    with smtplib.SMTP(
        settings.SMTP_HOST, settings.SMTP_PORT, timeout=settings.SMTP_TIMEOUT_SECONDS
    ) as client:
        client.ehlo()
        if settings.SMTP_STARTTLS:
            client.starttls()
            client.ehlo()
        if settings.SMTP_USERNAME:
            client.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        client.send_message(message)


async def send_notification_email(
    *,
    to_address: str,
    recipient_name: str,
    notification_type: str,
    message: str,
    link: str | None,
) -> bool:
    """Render and deliver one notification email. Returns whether it was accepted.

    Up to `EMAIL_MAX_ATTEMPTS` attempts with exponential backoff, and then it stops: a relay that
    has refused three times is down, and holding the caller any longer would start costing the
    business event something. Every exit from this function is a boolean - there is no path out
    of it that raises.
    """
    if not settings.email_configured:
        logger.info(
            "notification.email_skipped",
            extra={"notification_type": notification_type, "reason": "smtp_not_configured"},
        )
        return False
    if not to_address:
        return False

    try:
        rendered = render_email(
            notification_type, recipient_name=recipient_name, message=message, link=link
        )
        built = build_message(to_address, rendered)
    except Exception:
        logger.exception(
            "notification.email_render_failed", extra={"notification_type": notification_type}
        )
        return False

    attempts = max(1, settings.EMAIL_MAX_ATTEMPTS)
    for attempt in range(1, attempts + 1):
        try:
            await asyncio.to_thread(_smtp_send, built)
        # Any relay failure is the same failure here: the message did not go.
        except Exception as exc:
            if attempt < attempts:
                # 2s, then 4s. Long enough for a relay to finish a restart, short enough that the
                # transaction the caller is holding open is not held for a minute.
                await _backoff(settings.EMAIL_RETRY_BASE_SECONDS * (2 ** (attempt - 1)))
                continue
            logger.error(
                "notification.email_failed",
                extra={
                    "notification_type": notification_type,
                    "attempts": attempt,
                    # The address is not logged: the failure is diagnosable from the type, the
                    # attempt count and the relay's own error.
                    "error": str(exc),
                },
            )
            return False
        else:
            return True
    return False

"""Real Web Push delivery, and the subscription lifecycle behind it.

Push is gated by one thing and one thing only: whether the recipient currently has an active row
in `push_subscriptions`. It is not gated by `users.notification_channel`, and deliberately so -
that column records a settings-page preference about email, while push is a permission a browser
granted and can withdraw without telling this platform. Reading a database preference to decide
whether to attempt a delivery the browser has already refused would be reading the wrong thing.

A subscription the push service reports as `410 Gone` or `404 Not Found` is dead: the browser was
uninstalled, the profile cleared, the permission revoked. It is deleted here rather than retried,
because retrying it costs a request per notification for the rest of the deployment's life and
will never succeed.
"""

from __future__ import annotations

import asyncio
import json
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.base import utcnow
from app.models.push import PushSubscription

logger = get_logger(__name__)

# The endpoint is gone for good. Anything else - a timeout, a 500, a rate limit - is transient
# and simply costs this one delivery.
DEAD_SUBSCRIPTION_STATUSES = frozenset({404, 410})

# Shown by the browser beside the notification body. Served from the app's own origin, and the
# same icon the installed application uses.
PUSH_ICON_PATH = "/icons/icon-192.png"
PUSH_BADGE_PATH = "/icons/badge-72.png"

TITLE_BY_TYPE: dict[str, str] = {
    "exception.opened": "Exception needs attention",
    "approval.requested": "Decision waiting on you",
    "approval.decided": "Your submission was decided",
    "integration.attention": "Integration needs a person",
    "report.ready": "Report ready",
}


class PushDeliveryError(Exception):
    """A delivery attempt failed. `status_code` is the push service's own, where it gave one."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


# --- the subscription lifecycle ------------------------------------------------------------------


async def upsert_subscription(
    session: AsyncSession,
    *,
    user_id: UUID,
    endpoint: str,
    p256dh: str,
    auth: str,
    user_agent: str | None = None,
) -> PushSubscription:
    """Register this browser, or refresh the keys on the registration it already has.

    Upsert rather than insert, keyed on (user, endpoint): a browser that re-subscribes - after a
    permission reset, a key rotation, or simply a new session - presents the same endpoint with
    new key material. Inserting would give that device two rows and then two identical pushes.
    """
    existing = await session.scalar(
        select(PushSubscription).where(
            PushSubscription.user_id == user_id, PushSubscription.endpoint == endpoint
        )
    )
    if existing is not None:
        existing.p256dh = p256dh
        existing.auth = auth
        existing.user_agent = user_agent
        await session.flush()
        return existing

    row = PushSubscription(
        user_id=user_id,
        endpoint=endpoint,
        p256dh=p256dh,
        auth=auth,
        user_agent=user_agent,
    )
    session.add(row)
    await session.flush()
    return row


async def remove_subscription(
    session: AsyncSession, *, user_id: UUID, endpoint: str | None = None
) -> int:
    """Drop one of this account's subscriptions, or all of them when no endpoint is named.

    The `user_id` predicate is part of the DELETE rather than a check performed before it, so
    there is no window in which an endpoint belonging to somebody else could be removed by
    quoting it.
    """
    statement = delete(PushSubscription).where(PushSubscription.user_id == user_id)
    if endpoint:
        statement = statement.where(PushSubscription.endpoint == endpoint)
    result = await session.execute(statement)
    await session.flush()
    return int(result.rowcount or 0)


async def active_subscriptions(session: AsyncSession, user_id: UUID) -> list[PushSubscription]:
    return list(
        (
            await session.scalars(
                select(PushSubscription)
                .where(PushSubscription.user_id == user_id)
                .order_by(PushSubscription.created_at)
            )
        ).all()
    )


async def count_for_user(session: AsyncSession, user_id: UUID) -> int:
    return len(await active_subscriptions(session, user_id))


# --- delivery -------------------------------------------------------------------------------------


def build_payload(notification_type: str, message: str, url: str) -> str:
    """What the service worker receives. Deliberately thin.

    A push payload travels through a third-party push service, so it carries the same one-line
    summary the in-app row carries and a path to open - never counterparty detail, never a figure,
    and never a token.
    """
    return json.dumps(
        {
            "title": TITLE_BY_TYPE.get(notification_type, "AGFZE Command Centre"),
            "body": message,
            "url": url,
            "icon": PUSH_ICON_PATH,
            "badge": PUSH_BADGE_PATH,
            "type": notification_type,
        },
        separators=(",", ":"),
    )


# Swapped for a fake in the one test that exercises the real signing and encryption path, so that
# the VAPID key format this platform generates is proved to be one `pywebpush` can actually sign
# with - without a request leaving the machine. None everywhere else, which is pywebpush's own
# default and means it makes the request itself.
_requests_session = None


def set_requests_session(session) -> None:
    global _requests_session
    _requests_session = session


def _send_webpush(subscription_info: dict, payload: str) -> None:
    """One synchronous, VAPID-signed delivery. The seam the suite replaces.

    `pywebpush` is imported here rather than at module scope so that the rest of this module -
    the subscription lifecycle, which the API depends on - keeps importing on a machine where the
    optional wheel is not installed.
    """
    from pywebpush import WebPushException, webpush

    try:
        webpush(
            subscription_info=subscription_info,
            data=payload,
            vapid_private_key=settings.VAPID_PRIVATE_KEY,
            # `aud` and `exp` are derived from the endpoint and the clock by pywebpush itself;
            # `sub` is the only claim this platform has an answer for.
            vapid_claims={"sub": settings.VAPID_SUBJECT},
            ttl=settings.PUSH_TTL_SECONDS,
            requests_session=_requests_session,
        )
    except WebPushException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        raise PushDeliveryError(str(exc), status_code=status) from exc


def subscription_info(row: PushSubscription) -> dict:
    return {"endpoint": row.endpoint, "keys": {"p256dh": row.p256dh, "auth": row.auth}}


async def deliver_to_subscription(
    session: AsyncSession, row: PushSubscription, payload: str
) -> bool:
    """Deliver to one endpoint. Returns whether it was accepted; never raises.

    A dead endpoint is deleted on the spot. That is the difference between a subscription table
    that stays the size of the staff list and one that grows for ever.
    """
    try:
        await asyncio.to_thread(_send_webpush, subscription_info(row), payload)
    except PushDeliveryError as exc:
        if exc.status_code in DEAD_SUBSCRIPTION_STATUSES:
            logger.info(
                "notification.push_subscription_expired",
                extra={"status_code": exc.status_code, "subscription_id": str(row.id)},
            )
            await session.delete(row)
            await session.flush()
            return False
        logger.warning(
            "notification.push_failed",
            extra={"status_code": exc.status_code, "subscription_id": str(row.id)},
        )
        return False
    # A courtesy channel may not take the caller down with it.
    except Exception:
        logger.exception("notification.push_failed", extra={"subscription_id": str(row.id)})
        return False

    row.last_used_at = utcnow()
    await session.flush()
    return True


async def push_to_user(
    session: AsyncSession,
    *,
    user_id: UUID,
    notification_type: str,
    message: str,
    url: str,
) -> int:
    """Deliver to every one of this account's browsers. Returns how many accepted it.

    Zero is an ordinary answer: nobody has to be subscribed, and a person whose only subscription
    has just been found dead is correctly recorded as having received no push.
    """
    if not settings.push_configured:
        logger.info(
            "notification.push_skipped",
            extra={"notification_type": notification_type, "reason": "vapid_not_configured"},
        )
        return 0

    rows = await active_subscriptions(session, user_id)
    if not rows:
        return 0

    payload = build_payload(notification_type, message, url)
    delivered = 0
    for row in rows:
        if await deliver_to_subscription(session, row, payload):
            delivered += 1
    return delivered

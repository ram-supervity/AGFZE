"""The background loop that keeps the mailbox flowing.

Two jobs on one timer:

* renew the change-notification subscription well before its ~3 day expiry, creating it on the
  first pass (only when a publicly reachable notification URL is configured);
* run a delta-query poll every `GRAPH_POLL_INTERVAL_SECONDS`, so a webhook delivery that never
  arrives costs at most one interval of latency rather than the message itself.

The delta link is persisted through the Step 1 storage service rather than in a new table: it is
an opaque provider token, and this step is not permitted a sixth table for it.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import AsyncSessionLocal
from app.services.email_ingestion import ingest_message
from app.services.graph_service import GraphError, get_graph_client
from app.services.storage import ObjectNotFoundError, get_storage_service

logger = get_logger(__name__)

DELTA_LINK_KEY = "graph/inbox-delta-link"
# Renewed once the subscription is inside this margin of its expiry.
RENEWAL_MARGIN = timedelta(hours=12)


async def _load_delta_link() -> str | None:
    try:
        raw = await get_storage_service().download(DELTA_LINK_KEY)
    except (ObjectNotFoundError, OSError):
        return None
    link = raw.decode("utf-8").strip()
    return link or None


async def _save_delta_link(link: str) -> None:
    await get_storage_service().upload(DELTA_LINK_KEY, link.encode("utf-8"), "text/plain")


async def poll_once() -> int:
    """Run one delta poll. Returns the number of messages newly captured."""
    graph = get_graph_client()
    delta_link = await _load_delta_link()
    page = await graph.delta(delta_link)

    ingested = 0
    for message in page.messages:
        async with AsyncSessionLocal() as session:
            try:
                result = await ingest_message(session, message.message_id, client=graph)
            except Exception:
                await session.rollback()
                logger.exception("poll_ingestion_failed")
                continue
        if result.created:
            ingested += 1

    if page.delta_link:
        await _save_delta_link(page.delta_link)
    if ingested:
        logger.info("mailbox_poll_ingested", extra={"message_count": ingested})
    return ingested


class SubscriptionKeeper:
    """Holds the current change-notification subscription and renews it before it lapses."""

    def __init__(self) -> None:
        self.subscription_id: str | None = None
        self.expires_at: datetime | None = None

    async def ensure(self) -> None:
        if not settings.GRAPH_WEBHOOK_ENABLED:
            return
        if not settings.GRAPH_WEBHOOK_NOTIFICATION_URL.strip():
            logger.warning("graph_subscription_skipped_no_notification_url")
            return

        graph = get_graph_client()
        now = datetime.now(timezone.utc)
        if self.subscription_id and self.expires_at and self.expires_at - now > RENEWAL_MARGIN:
            return

        try:
            if self.subscription_id:
                payload = await graph.renew_subscription(self.subscription_id)
            else:
                payload = await graph.create_subscription()
        except GraphError as exc:
            logger.warning("graph_subscription_failed", extra={"reason": exc.reason})
            # A failed renewal invalidates the handle; the next pass creates a fresh one.
            self.subscription_id = None
            self.expires_at = None
            return

        self.subscription_id = str(payload.get("id") or "") or None
        raw_expiry = str(payload.get("expirationDateTime") or "")
        try:
            self.expires_at = datetime.fromisoformat(raw_expiry.replace("Z", "+00:00"))
        except ValueError:
            self.expires_at = now + timedelta(minutes=settings.GRAPH_SUBSCRIPTION_TTL_MINUTES)
        logger.info(
            "graph_subscription_active",
            extra={"expires_at": self.expires_at.isoformat() if self.expires_at else None},
        )


async def run_worker(stop: asyncio.Event) -> None:
    keeper = SubscriptionKeeper()
    interval = max(30, settings.GRAPH_POLL_INTERVAL_SECONDS)
    logger.info("mailbox_worker_started", extra={"interval_seconds": interval})

    while not stop.is_set():
        try:
            await keeper.ensure()
            await poll_once()
        except GraphError as exc:
            logger.warning("mailbox_poll_failed", extra={"reason": exc.reason})
        except Exception:
            logger.exception("mailbox_worker_iteration_failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            continue
    logger.info("mailbox_worker_stopped")


def should_run() -> bool:
    """Only run where it can actually do something: real credentials, not the test harness."""
    return settings.GRAPH_POLL_ENABLED and settings.graph_configured and not settings.is_testing

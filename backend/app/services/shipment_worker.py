"""The background loop that keeps the shipment board honest.

One job on one timer, modelled on the mailbox worker Step 2 established rather than on a second
scheduling mechanism: every `SHIPMENT_TRACKING_INTERVAL_SECONDS` - six hours by default - run one
sweep.

Worth being clear about why this runs at all on a deployment with no carrier adapter registered,
which is every deployment that ships today. The sweep does two things, and only the first of them
needs an adapter. It attempts a pull, which finds nothing and honestly records that it found
nothing; and it notices the shipments nobody has established anything about for longer than the
configured threshold and opens a real, owned exception against each. The second half is the whole
value of the job for a desk tracking its cargo by hand, and switching the job off because no
carrier is reachable would remove exactly the part that helps them.
"""

from __future__ import annotations

import asyncio

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import AsyncSessionLocal
from app.services.logistics import tracking_service
from app.services.logistics.adapters import registered_adapters

logger = get_logger(__name__)


async def sweep_once() -> tracking_service.SweepResult:
    """Run one sweep in its own session and commit it. Returns what it did."""
    async with AsyncSessionLocal() as session:
        try:
            result = await tracking_service.run_sweep(
                session, limit=max(1, settings.SHIPMENT_TRACKING_BATCH_SIZE)
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
    return result


async def run_worker(stop: asyncio.Event) -> None:
    interval = max(60, settings.SHIPMENT_TRACKING_INTERVAL_SECONDS)
    logger.info(
        "shipment_worker_started",
        extra={
            "interval_seconds": interval,
            # Logged plainly at startup so an operator can see, without reading any code, that
            # the platform is tracking by hand rather than assuming an integration exists.
            "carrier_adapters": len(registered_adapters()),
        },
    )

    while not stop.is_set():
        try:
            result = await sweep_once()
            if result.considered:
                logger.info(
                    "shipment_sweep_complete",
                    extra={
                        "considered": result.considered,
                        "adapter_attempts": result.attempted,
                        "updated": result.updated,
                        "left_for_manual": result.left_for_manual,
                        "flagged_for_review": result.flagged,
                        "exceptions_opened": result.exceptions_opened,
                    },
                )
        except Exception:
            logger.exception("shipment_worker_iteration_failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            continue
    logger.info("shipment_worker_stopped")


def should_run() -> bool:
    """Only outside the test harness, which drives the sweep directly and deterministically."""
    return settings.SHIPMENT_TRACKING_POLL_ENABLED and not settings.is_testing

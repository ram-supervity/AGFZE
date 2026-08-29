"""The retry sweep, on its own timer.

The first genuinely periodic background job in this build, and the first step where one is
justified. Step 1 built the background-job service and deliberately stopped there; Step 4 was
asked for a sweep and declined, because an exception's age is computed from its own timestamp at
read time and no job was needed to keep it true. Here there is a real, time-based consequence for
a timer to drive: an attempt that failed for a transient reason has a next attempt genuinely due
at a calculable moment, and something has to be awake to make it.

Two things this sweep deliberately does not do. It never picks up a job that is waiting on a
person - there is nothing automated left to re-attempt, and re-running it would overwrite their
work with the same fallback that produced it. And it never re-opens a job that has exhausted its
attempts: that job is `failed`, its exception is open, and an administrator's explicit retry is
what starts it again.

From Step 8 this loop also carries the scheduled reports. It is not a second scheduler and the
loop below did not change shape to take them: the tick already runs every sixty seconds, so the
daily and monthly tasks are asked whether they are due on the way past. Adding a cron daemon or a
scheduling library for two questions a minute would have been a third mechanism this application
does not need. Neither task can hold up the other - each runs in its own session and its own try,
and a failure in one is logged and stepped over.
"""

from __future__ import annotations

import asyncio

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import AsyncSessionLocal
from app.services.analytics import retention
from app.services.analytics import schedule as report_schedule
from app.services.integration import integration_service

logger = get_logger(__name__)


async def sweep_once() -> integration_service.DispatchResult:
    """Run one sweep in its own session and commit it. Returns what it did."""
    async with AsyncSessionLocal() as session:
        try:
            result = await integration_service.run_sweep(
                session, limit=max(1, settings.INTEGRATION_SWEEP_BATCH_SIZE)
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
    return result


async def scheduled_reports_once() -> report_schedule.ScheduleResult:
    """Ask the report tasks whether anything is due, in a session of their own.

    Separate from the integration sweep's session on purpose: a report that cannot be produced
    must not roll back a retry that succeeded a moment earlier, and vice versa.
    """
    async with AsyncSessionLocal() as session:
        try:
            return await report_schedule.run_due(session)
        except Exception:
            await session.rollback()
            raise


async def retention_once() -> retention.RetentionResult:
    """Ask the retention sweep whether anything has aged out, in a session of its own.

    Separate from both sessions above for the same reason they are separate from each other: no
    one of the three may roll back the work of another.
    """
    async with AsyncSessionLocal() as session:
        try:
            result = await retention.run_due(session)
            await session.commit()
        except Exception:
            await session.rollback()
            raise
    return result


async def run_worker(stop: asyncio.Event) -> None:
    interval = max(15, settings.INTEGRATION_SWEEP_INTERVAL_SECONDS)
    logger.info(
        "periodic_worker_started",
        extra={
            "interval_seconds": interval,
            "max_attempts": settings.INTEGRATION_MAX_ATTEMPTS,
            "integration_sweep": settings.INTEGRATION_SWEEP_ENABLED,
            "scheduled_reports": report_schedule.should_run(),
            # False on every deployment until AGFZE confirms a retention period. Logged so an
            # operator can see at a glance that nothing is ageing documents out.
            "document_retention": retention.should_run(),
            # Logged plainly at startup so an operator can see, without reading any code, which
            # of the three targets this deployment can actually post to.
            "configured_targets": integration_service.configured_targets(),
        },
    )

    while not stop.is_set():
        try:
            # Guarded rather than assumed: the loop now also carries the scheduled reports, so it
            # can be running on a deployment that has deliberately switched the retry sweep off.
            result = (
                await sweep_once()
                if settings.INTEGRATION_SWEEP_ENABLED
                else integration_service.DispatchResult()
            )
            if result.attempted:
                logger.info(
                    "integration_sweep_complete",
                    extra={
                        "attempted": result.attempted,
                        "succeeded": result.succeeded,
                        "failed": result.failed,
                        "awaiting_manual": result.awaiting_manual,
                        "requeued": result.requeued,
                    },
                )
        except Exception:
            logger.exception("integration_worker_iteration_failed")

        if report_schedule.should_run():
            try:
                due = await scheduled_reports_once()
                if due.generated:
                    logger.info(
                        "scheduled_reports_complete",
                        extra={"generated": due.generated},
                    )
            except Exception:
                logger.exception("scheduled_report_iteration_failed")

        if retention.should_run():
            try:
                aged = await retention_once()
                if aged.flagged:
                    logger.info(
                        "retention_sweep_complete",
                        extra={
                            "considered": aged.considered,
                            "flagged": len(aged.flagged),
                            "dry_run": aged.dry_run,
                        },
                    )
            except Exception:
                logger.exception("retention_iteration_failed")

        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            continue
    logger.info("integration_worker_stopped")


def should_run() -> bool:
    """Only outside the test harness, which drives both tasks directly and deterministically.

    The loop starts where either of the things riding it has work to do, so switching the
    integration sweep off does not silently switch the scheduled reports off with it.
    """
    if settings.is_testing:
        return False
    return settings.INTEGRATION_SWEEP_ENABLED or report_schedule.should_run()

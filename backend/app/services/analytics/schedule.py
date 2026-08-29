"""When the daily and monthly reports are due, and producing them when they are.

This module holds the *tasks*, not a scheduler. There is exactly one periodic loop in this
application - the sweep  introduced for integration retries - and it is already awake every
sixty seconds. All this needs from it is to be asked, on the way past, whether anything is due;
that is what :func:`run_due` answers. Adding a cron daemon, a second worker loop or a scheduling
library here would be a third mechanism for a job that needs none of them.

Dueness is decided from the table itself, not from a stored "last run" marker. A report is due
when its scheduled moment has passed and no report of that type already covers that period. That
makes the check idempotent for free: two processes running the sweep concurrently, or one
restarting mid-tick, produce one report rather than two, and a deployment that was switched off
over the weekend produces the reports it missed on the way back up rather than losing them
silently.

Every scheduled report is a real generation with a real file behind it. Since 2 a scheduled
report is also *distributed*, to whichever recipients an administrator has configured for its type
and on whichever channel they configured - and to nobody at all where no rule has been configured,
which is the shipped state. What is distributed is a notification carrying a link to the report's
authenticated detail page. The report itself is never attached, embedded or emailed; see
`analytics/distribution.py`, which owns that boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.base import utcnow
from app.models.reporting import Report
from app.services.analytics import distribution, report_service
from app.services.analytics.kpis import Period, day_period, previous_month_period
from app.services.notification_service import notify_report_ready

logger = get_logger(__name__)

DAILY = "daily"
MONTHLY = "monthly"

# Both scheduled reports are produced as PDFs: they are read, not re-analysed. Anybody who wants
# the figures in a spreadsheet asks the builder for an XLSX over the same range.
SCHEDULED_FORMAT = "pdf"


@dataclass(frozen=True)
class DueReport:
    report_type: str
    period: Period
    due_at: datetime


@dataclass
class ScheduleResult:
    considered: int = 0
    generated: list[str] = field(default_factory=list)


def daily_due(now: datetime) -> DueReport:
    """The most recent daily run that has already come round, and the day it covers.

    The report covers the day *before* its run time, which is the only version of "the daily
    report" that is ever complete when it is produced.
    """
    scheduled = now.astimezone(timezone.utc).replace(
        hour=_hour(settings.REPORT_DAILY_HOUR_UTC),
        minute=_minute(settings.REPORT_DAILY_MINUTE_UTC),
        second=0,
        microsecond=0,
    )
    if scheduled > now:
        scheduled -= timedelta(days=1)
    return DueReport(
        report_type=DAILY,
        period=day_period(scheduled - timedelta(days=1)),
        due_at=scheduled,
    )


def monthly_due(now: datetime) -> DueReport:
    """The most recent monthly run that has come round, covering the month that ended before it."""
    moment = now.astimezone(timezone.utc)
    scheduled = moment.replace(
        day=max(1, min(28, settings.REPORT_MONTHLY_DAY)),
        hour=_hour(settings.REPORT_MONTHLY_HOUR_UTC),
        minute=_minute(settings.REPORT_MONTHLY_MINUTE_UTC),
        second=0,
        microsecond=0,
    )
    if scheduled > moment:
        #  back into the previous month and land on the configured day of it.
        previous = scheduled.replace(day=1) - timedelta(days=1)
        scheduled = scheduled.replace(year=previous.year, month=previous.month)
    return DueReport(
        report_type=MONTHLY,
        period=previous_month_period(scheduled - timedelta(days=1)),
        due_at=scheduled,
    )


def _hour(value: int) -> int:
    return max(0, min(23, value))


def _minute(value: int) -> int:
    return max(0, min(59, value))


async def already_generated(session: AsyncSession, due: DueReport) -> bool:
    """Whether a report of this type already covers this exact period.

    The period is the identity of a scheduled report, so this is what makes the check idempotent
    without a marker table, a lock or a stored last-run timestamp - none of which could survive a
    restart at the wrong moment as reliably as the row that was actually written.
    """
    existing = await session.scalar(
        select(Report.id).where(
            Report.report_type == due.report_type,
            Report.period_start == due.period.start,
            Report.period_end == due.period.end,
        )
    )
    return existing is not None


async def run_due(session: AsyncSession, *, now: datetime | None = None) -> ScheduleResult:
    """Produce whichever scheduled reports are due and not already produced.

    Called from the periodic sweep on every tick. On the overwhelming majority of ticks it runs
    two indexed lookups and returns having done nothing, which is what a scheduled task riding an
    existing loop is supposed to cost.
    """
    result = ScheduleResult()
    if not settings.REPORT_SCHEDULE_ENABLED:
        return result

    moment = now or utcnow()
    for due in (daily_due(moment), monthly_due(moment)):
        result.considered += 1
        if await already_generated(session, due):
            continue
        request = report_service.validate_request(
            report_type=due.report_type,
            output_format=SCHEDULED_FORMAT,
            period=due.period,
            stream=report_service.STREAM_BOTH,
            status_filter=None,
        )
        try:
            # `requested_by` is None on purpose: nobody asked for this one, and attributing it to
            # a person - or to an invented service account - would put a name on work nobody did.
            report = await report_service.generate(
                session, request, requested_by=None, scope=report_service.system_scope()
            )
            # Only a scheduled report notifies. An ad-hoc one has a requester already watching
            # its job-progress indicator, and telling them what their own screen is telling them
            # would be noise.
            #
            # Two separate acts, in this order and deliberately not merged. The first is the
            # standing notice to Admin and the approving desk that a scheduled report exists,
            # which is a property of the platform and has been here since . The second is
            # configured distribution, which is a property of what an administrator asked for and
            # reaches nobody until somebody configures it. Collapsing them would make turning
            # distribution on silently change who is told a report exists at all.
            await notify_report_ready(
                session,
                report_id=report.id,
                report_type=due.report_type,
                title=report.title,
            )
            outcome = await distribution.distribute(
                session,
                report_id=report.id,
                report_type=due.report_type,
                title=report.title,
            )
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception(
                "scheduled_report_failed",
                extra={"report_type": due.report_type, "due_at": due.due_at.isoformat()},
            )
            continue
        result.generated.append(report.generation_reference)
        logger.info(
            "scheduled_report_generated",
            extra={
                "report_type": due.report_type,
                "generation_reference": report.generation_reference,
                "period_start": due.period.start.isoformat(),
                # Said plainly on the log line as well as on the document. False here now means
                # "nobody was configured to receive it", not "this platform cannot send".
                "distributed": outcome.distributed,
                "recipient_count": len(outcome.notified_user_ids),
            },
        )
    return result


def should_run() -> bool:
    """Only outside the test harness, which drives `run_due` directly and deterministically."""
    return settings.REPORT_SCHEDULE_ENABLED and not settings.is_testing

"""What becomes of a document once it is old, and the reason nothing happens yet.

The BRD asks for a retention policy and then says, in its own words, that the period is to be
confirmed by AGFZE. That leaves exactly one honest thing to build: the mechanism, switched off,
with no period baked into it. A default retention period invented here would be a number nobody
agreed to, quietly deleting a trade document somebody needed - and unlike a wrong threshold, that
is not a decision anybody can reverse afterwards.

So this module ships three deliberate properties.

**Off by default.** `DOCUMENT_RETENTION_ENABLED` is False. Nothing runs.

**No default period.** `DOCUMENT_RETENTION_DAYS` is 0, which means unset rather than "delete
immediately", and the sweep refuses to run on it however the flag is set. Turning retention on
without naming a period does nothing and says so on the log line.

**Dry run until somebody says otherwise.** Even fully configured, the default mode reports what it
*would* act on and touches nothing. `DOCUMENT_RETENTION_DRY_RUN=false` is the one setting that lets
it act, and even then it only ever marks a document for review - see `RetentionAction`.

There is deliberately no code path in this module that deletes an object from storage or a row from
the database. Archival to a colder storage class is a bucket lifecycle rule, which belongs in
Terraform where it is reviewable, not in a job that could be misconfigured into a delete.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.base import utcnow
from app.models.intake import Document
from app.models.reporting import Report
from app.services.audit_service import ActorType, record_audit_event

logger = get_logger(__name__)

RETENTION_REVIEW_EVENT = "retention.review_due"

# How many rows one sweep will look at. A retention sweep is not urgent and a deployment that has
# just switched it on may have years of documents behind it; a bounded pass that runs again next
# tick is preferable to one long transaction holding locks across the whole table.
SWEEP_LIMIT = 500


@dataclass
class RetentionAction:
    """One thing the sweep found, and what it did about it - which is never a deletion."""

    entity_type: str
    entity_id: str
    reference: str | None
    age_days: int


@dataclass
class RetentionResult:
    considered: int = 0
    flagged: list[RetentionAction] = field(default_factory=list)
    dry_run: bool = True
    # Why a sweep did nothing, where it did nothing. Read on the log line, and by the tests.
    skipped_reason: str | None = None

    @property
    def acted(self) -> bool:
        return bool(self.flagged) and not self.dry_run


def retention_cutoff(now: datetime | None = None) -> datetime | None:
    """The moment before which a document is older than the configured period.

    None when no period is configured, which is the shipped state and is not an error.
    """
    days = settings.DOCUMENT_RETENTION_DAYS
    if days <= 0:
        return None
    return (now or utcnow()) - timedelta(days=days)


def should_run() -> bool:
    """Both switches, and never only the flag.

    A deployment that enabled retention but never named a period has not configured retention; it
    has expressed an intention. Running on that would mean choosing the period on their behalf.
    """
    return (
        settings.DOCUMENT_RETENTION_ENABLED
        and settings.DOCUMENT_RETENTION_DAYS > 0
        and not settings.is_testing
    )


async def run_due(session: AsyncSession, *, now: datetime | None = None) -> RetentionResult:
    """Find what has aged past the configured period and record it for a person to review."""
    result = RetentionResult(dry_run=settings.DOCUMENT_RETENTION_DRY_RUN)

    if not settings.DOCUMENT_RETENTION_ENABLED:
        result.skipped_reason = "retention_disabled"
        return result

    cutoff = retention_cutoff(now)
    if cutoff is None:
        # Said out loud rather than passed over: somebody turned this on expecting it to do
        # something, and silence would let them believe it had.
        logger.warning(
            "retention.no_period_configured",
            extra={"detail": "DOCUMENT_RETENTION_ENABLED is on but DOCUMENT_RETENTION_DAYS is 0"},
        )
        result.skipped_reason = "no_period_configured"
        return result

    documents = list(
        (
            await session.scalars(
                select(Document)
                .where(Document.created_at < cutoff)
                .order_by(Document.created_at)
                .limit(SWEEP_LIMIT)
            )
        ).all()
    )
    reports = list(
        (
            await session.scalars(
                select(Report)
                .where(Report.generated_at < cutoff)
                .order_by(Report.generated_at)
                .limit(SWEEP_LIMIT)
            )
        ).all()
    )
    result.considered = len(documents) + len(reports)

    moment = now or utcnow()
    for document in documents:
        result.flagged.append(
            RetentionAction(
                entity_type="document",
                entity_id=str(document.id),
                reference=document.filename,
                age_days=_age_days(document.created_at, moment),
            )
        )
    for report in reports:
        result.flagged.append(
            RetentionAction(
                entity_type="report",
                entity_id=str(report.id),
                reference=report.generation_reference,
                age_days=_age_days(report.generated_at, moment),
            )
        )

    if result.dry_run:
        logger.info(
            "retention.dry_run",
            extra={
                "considered": result.considered,
                "would_flag": len(result.flagged),
                "retention_days": settings.DOCUMENT_RETENTION_DAYS,
            },
        )
        return result

    # The one thing this job does when it is fully switched on: writes an audit row per item, so
    # the retention position is visible on /admin/audit and a person decides. No object is removed
    # from storage and no row is deleted, here or anywhere downstream of here.
    for action in result.flagged:
        await record_audit_event(
            session,
            event_type=RETENTION_REVIEW_EVENT,
            entity_type=action.entity_type,
            entity_id=action.entity_id,
            actor_type=ActorType.SYSTEM,
            metadata={
                "reference": action.reference,
                "age_days": action.age_days,
                "retention_days": settings.DOCUMENT_RETENTION_DAYS,
                # Stated on every row so nobody reading the trail later infers that the platform
                # removed something.
                "action": "flagged_for_review",
                "deleted": False,
            },
        )
    logger.info(
        "retention.flagged_for_review",
        extra={"considered": result.considered, "flagged": len(result.flagged)},
    )
    return result


def _age_days(moment: datetime, now: datetime) -> int:
    from app.services.governance.approval_service import aware

    return max(0, (now - aware(moment)).days)

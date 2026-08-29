"""Orchestrating the three postings an approved transaction owes the outside world.

The rules this module exists to enforce, in the order they matter:

1. **A job's status is what genuinely happened.** `succeeded` is written in exactly two places -
   an adapter that really succeeded, and an administrator who confirmed in writing that they
   finished the posting themselves. There is no third writer and no default.
2. **The three jobs are independent.** Each is attempted, retried, failed and resolved on its
   own. A DMS upload nobody can perform never delays the tracker sync, and a failing SAP posting
   never touches either of the others.
3. **A job waiting on a person is never retried.** There is nothing automated left to attempt on
   an `awaiting_manual_action` job, and re-running it would overwrite a person's work in progress
   with the same fallback that produced it.
4. **`Committed` means all three are resolved.** Whether a resolution was automated or manually
   confirmed makes no difference to reaching it; the distinction stays visible on every job
   forever.

The exception on final failure is opened by calling Step 4's standalone case-creation function
directly - the same function the shipment sweep calls - rather than by synthesising a rule
evaluation. An integration failure is not a check on extracted data, and dressing it up as one to
reuse the hard-fail hook would put a fabricated evaluation in a table auditors read as a record
of real checks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.errors import ConflictError, NotFoundError
from app.core.logging import get_logger
from app.core.roles import PlatformRole
from app.db.base import utcnow
from app.models.enums import (
    RETRYABLE_JOB_STATUSES,
    ExceptionCategory,
    ExceptionPriority,
    IntegrationJobStatus,
    IntegrationTargetSystem,
    TransactionStatus,
)
from app.models.governance import ExceptionCase
from app.models.identity import User
from app.models.integration import IntegrationJob
from app.models.transactions import TradeTransaction
from app.services.audit_service import ActorType, record_audit_event
from app.services.governance import hooks as governance_hooks
from app.services.integration.adapters import IntegrationAdapter, IntegrationOutcome, OutcomeKind
from app.services.integration.dms import DmsAdapter
from app.services.integration.sap import SapAdapter
from app.services.integration.tracker import TrackerAdapter
from app.services.notification_service import notify_integration_attention

logger = get_logger(__name__)

# The order jobs are created and shown in. Not a sequence of dependencies - nothing here waits on
# anything else - just the order a person reads them in.
TARGET_SYSTEMS: tuple[str, ...] = (
    IntegrationTargetSystem.TRACKER.value,
    IntegrationTargetSystem.SAP.value,
    IntegrationTargetSystem.DMS.value,
)

TARGET_LABELS: dict[str, str] = {
    IntegrationTargetSystem.TRACKER.value: "Excel tracker",
    IntegrationTargetSystem.SAP.value: "SAP",
    IntegrationTargetSystem.DMS.value: "Document management",
}

MIN_MANUAL_NOTE = 10


class AuditEvent:
    JOBS_CREATED = "integration.jobs.created"
    JOB_ATTEMPTED = "integration.job.attempted"
    JOB_SUCCEEDED = "integration.job.succeeded"
    JOB_FAILED = "integration.job.failed"
    JOB_AWAITING_MANUAL = "integration.job.awaiting_manual_action"
    JOB_RETRY_SCHEDULED = "integration.job.retry_scheduled"
    JOB_RETRIED = "integration.job.retried"
    JOB_COMPLETED_MANUALLY = "integration.job.completed_manually"
    TRANSACTION_COMMITTED = "integration.transaction.committed"


_ADAPTERS: dict[str, IntegrationAdapter] = {
    IntegrationTargetSystem.TRACKER.value: TrackerAdapter(),
    IntegrationTargetSystem.SAP.value: SapAdapter(),
    IntegrationTargetSystem.DMS.value: DmsAdapter(),
}


def adapter_for(target_system: str) -> IntegrationAdapter:
    adapter = _ADAPTERS.get(target_system)
    if adapter is None:  # pragma: no cover - the vocabulary is closed by a check constraint
        raise NotFoundError(f"No adapter is registered for '{target_system}'.")
    return adapter


def set_adapter(target_system: str, adapter: IntegrationAdapter) -> IntegrationAdapter:
    """Replace one adapter. Used by the test suite, and by a deployment that has a real one."""
    previous = _ADAPTERS[target_system]
    _ADAPTERS[target_system] = adapter
    return previous


def configured_targets() -> dict[str, bool]:
    """Which targets this deployment can genuinely post to, for the monitor to state plainly."""
    return {target: adapter_for(target).configured for target in TARGET_SYSTEMS}


def aware(moment: datetime) -> datetime:
    """SQLite hands timestamps back naive; PostgreSQL's carry their zone."""
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


# --- backoff -------------------------------------------------------------------------------------


def backoff_seconds(attempt_count: int) -> int:
    """A short first wait, roughly doubling, capped. One attempt in, one wait out.

    `attempt_count` is the number of attempts already made, so the wait after the first failure
    is the base interval and each subsequent one is twice the last, up to the configured ceiling.
    """
    base = max(1, settings.INTEGRATION_RETRY_BASE_SECONDS)
    ceiling = max(base, settings.INTEGRATION_RETRY_MAX_SECONDS)
    exponent = max(0, attempt_count - 1)
    # Bounded before the shift so a job that somehow accumulated a large count cannot produce a
    # number too big to be a delay.
    if exponent > 32:
        return ceiling
    return min(base * (2**exponent), ceiling)


def next_attempt_at(job: IntegrationJob) -> datetime | None:
    """When this job is next due, or None if it is not waiting on the clock at all."""
    if job.status != IntegrationJobStatus.QUEUED.value:
        return None
    if job.last_attempted_at is None:
        return aware(job.created_at)
    return aware(job.last_attempted_at) + timedelta(seconds=backoff_seconds(job.attempt_count))


def is_due(job: IntegrationJob, *, now: datetime | None = None) -> bool:
    due = next_attempt_at(job)
    return due is not None and due <= (now or utcnow())


# --- creating the jobs ---------------------------------------------------------------------------


async def create_jobs(
    session: AsyncSession, transaction: TradeTransaction, *, actor_id: UUID | None = None
) -> list[IntegrationJob]:
    """Three jobs, one per target, and the transaction moved to `Integration Pending`.

    Idempotent: a transaction that already has its jobs is not given a second set. The unique
    constraint on (transaction, target) is the guarantee behind that, not this check.
    """
    existing = {job.target_system: job for job in await jobs_for(session, transaction.id)}
    created: list[IntegrationJob] = []
    for target in TARGET_SYSTEMS:
        if target in existing:
            continue
        job = IntegrationJob(
            transaction_id=transaction.id,
            target_system=target,
            status=IntegrationJobStatus.QUEUED.value,
            attempt_count=0,
        )
        session.add(job)
        created.append(job)
    await session.flush()

    if transaction.status != TransactionStatus.INTEGRATION_PENDING.value:
        transaction.status = TransactionStatus.INTEGRATION_PENDING.value
        transaction.updated_at = utcnow()
        await session.flush()

    if created:
        await record_audit_event(
            session,
            event_type=AuditEvent.JOBS_CREATED,
            entity_type="trade_transaction",
            entity_id=transaction.id,
            actor_id=actor_id,
            actor_type=ActorType.USER if actor_id else ActorType.SYSTEM,
            metadata={
                "batch_number": transaction.batch_number,
                "transaction_status": transaction.status,
                "jobs": [
                    {"id": str(job.id), "target_system": job.target_system} for job in created
                ],
                # Recorded at creation so the trail says, at the moment of approval, which
                # targets this deployment could actually post to.
                "configured_targets": configured_targets(),
            },
        )
    return [*existing.values(), *created]


async def jobs_for(session: AsyncSession, transaction_id: UUID) -> list[IntegrationJob]:
    rows = list(
        (
            await session.scalars(
                select(IntegrationJob)
                .where(IntegrationJob.transaction_id == transaction_id)
                .options(selectinload(IntegrationJob.completed_manually_by))
            )
        ).all()
    )
    order = {target: index for index, target in enumerate(TARGET_SYSTEMS)}
    return sorted(rows, key=lambda row: order.get(row.target_system, len(order)))


async def load_transaction(session: AsyncSession, transaction_id: UUID) -> TradeTransaction | None:
    return await session.scalar(
        select(TradeTransaction)
        .where(TradeTransaction.id == transaction_id)
        .options(
            selectinload(TradeTransaction.purchase_leg),
            selectinload(TradeTransaction.sales_leg),
            selectinload(TradeTransaction.fa_leg),
            selectinload(TradeTransaction.commodity),
        )
    )


# --- running one job -----------------------------------------------------------------------------


async def _record_attempt(
    session: AsyncSession,
    job: IntegrationJob,
    transaction: TradeTransaction,
    outcome: IntegrationOutcome,
) -> None:
    await record_audit_event(
        session,
        event_type=AuditEvent.JOB_ATTEMPTED,
        entity_type="integration_job",
        entity_id=job.id,
        actor_type=ActorType.SYSTEM,
        metadata={
            "transaction_id": str(transaction.id),
            "batch_number": transaction.batch_number,
            "target_system": job.target_system,
            "attempt": job.attempt_count,
            "outcome": outcome.kind.value,
            "configured": adapter_for(job.target_system).configured,
            # The adapter's own notes. Never a credential and never a provider message: adapters
            # return a reason code, not the body they were handed.
            "detail": outcome.detail,
        },
    )


async def _apply_success(
    session: AsyncSession,
    job: IntegrationJob,
    transaction: TradeTransaction,
    outcome: IntegrationOutcome,
) -> None:
    job.status = IntegrationJobStatus.SUCCEEDED.value
    job.external_reference = outcome.external_reference
    job.failure_reason = None
    job.manual_instruction = None
    job.updated_at = utcnow()
    await session.flush()
    await record_audit_event(
        session,
        event_type=AuditEvent.JOB_SUCCEEDED,
        entity_type="integration_job",
        entity_id=job.id,
        actor_type=ActorType.SYSTEM,
        metadata={
            "transaction_id": str(transaction.id),
            "target_system": job.target_system,
            "external_reference": job.external_reference,
            "attempt": job.attempt_count,
            # Always present, always false on this path. An automated success and a manual
            # confirmation must never be indistinguishable on the trail.
            "completed_manually": False,
        },
    )


async def _apply_awaiting_manual(
    session: AsyncSession,
    job: IntegrationJob,
    transaction: TradeTransaction,
    outcome: IntegrationOutcome,
) -> None:
    job.status = IntegrationJobStatus.AWAITING_MANUAL_ACTION.value
    job.failure_reason = None
    job.manual_instruction = outcome.manual_instruction
    job.prepared_payload = outcome.prepared_payload
    job.updated_at = utcnow()
    await session.flush()
    await record_audit_event(
        session,
        event_type=AuditEvent.JOB_AWAITING_MANUAL,
        entity_type="integration_job",
        entity_id=job.id,
        actor_type=ActorType.SYSTEM,
        metadata={
            "transaction_id": str(transaction.id),
            "batch_number": transaction.batch_number,
            "target_system": job.target_system,
            "reason": outcome.detail.get("reason"),
            "attempt": job.attempt_count,
        },
    )
    # Waiting on a person is not a failure, and the notification says so in its own words. It is
    # still work an administrator owes, so it is still told to them.
    await notify_integration_attention(
        session,
        transaction_id=transaction.id,
        target_label=TARGET_LABELS.get(job.target_system, job.target_system),
        batch_number=transaction.batch_number,
        state=IntegrationJobStatus.AWAITING_MANUAL_ACTION.value,
    )


async def _apply_failure(
    session: AsyncSession,
    job: IntegrationJob,
    transaction: TradeTransaction,
    outcome: IntegrationOutcome,
) -> None:
    """A failed attempt either earns another go or ends the job for good.

    The maximum attempt count is a ceiling on *attempts*, not on failures of a particular kind: a
    failure the adapter says is not worth retrying ends the job immediately, because four more
    identical rejections would only make the exception slower to arrive.
    """
    exhausted = job.attempt_count >= max(1, settings.INTEGRATION_MAX_ATTEMPTS)
    if outcome.retryable and not exhausted:
        job.status = IntegrationJobStatus.QUEUED.value
        job.failure_reason = outcome.failure_reason
        job.updated_at = utcnow()
        await session.flush()
        await record_audit_event(
            session,
            event_type=AuditEvent.JOB_RETRY_SCHEDULED,
            entity_type="integration_job",
            entity_id=job.id,
            actor_type=ActorType.SYSTEM,
            metadata={
                "transaction_id": str(transaction.id),
                "target_system": job.target_system,
                "attempt": job.attempt_count,
                "max_attempts": settings.INTEGRATION_MAX_ATTEMPTS,
                "failure_reason": outcome.failure_reason,
                "next_attempt_at": (
                    due.isoformat() if (due := next_attempt_at(job)) is not None else None
                ),
            },
        )
        return

    job.status = IntegrationJobStatus.FAILED.value
    job.failure_reason = outcome.failure_reason
    job.updated_at = utcnow()
    await session.flush()

    case = await open_failure_case(session, job, transaction)
    await record_audit_event(
        session,
        event_type=AuditEvent.JOB_FAILED,
        entity_type="integration_job",
        entity_id=job.id,
        actor_type=ActorType.SYSTEM,
        metadata={
            "transaction_id": str(transaction.id),
            "batch_number": transaction.batch_number,
            "target_system": job.target_system,
            "attempt": job.attempt_count,
            "max_attempts": settings.INTEGRATION_MAX_ATTEMPTS,
            "failure_reason": outcome.failure_reason,
            "retryable": outcome.retryable,
            "exception_case_id": str(case.id) if case is not None else None,
        },
    )
    await notify_integration_attention(
        session,
        transaction_id=transaction.id,
        target_label=TARGET_LABELS.get(job.target_system, job.target_system),
        batch_number=transaction.batch_number,
        state=IntegrationJobStatus.FAILED.value,
    )


async def open_failure_case(
    session: AsyncSession, job: IntegrationJob, transaction: TradeTransaction
) -> ExceptionCase | None:
    """The integration-failure case, owned by the desk that can actually do something about it.

    Admin, because on this platform Admin is the IT and integration-support function: a rejected
    SAP posting is not the buying desk's to fix. The category has been registered and dormant
    since Step 4 for exactly this moment, and this is the first code in the platform that can
    produce one.
    """
    label = TARGET_LABELS.get(job.target_system, job.target_system)
    return await governance_hooks.open_case(
        session,
        category=ExceptionCategory.INTEGRATION_FAILURE.value,
        owner_role=PlatformRole.ADMIN.value,
        priority=ExceptionPriority.HIGH.value,
        summary=(
            f"{label} rejected or could not accept the posting for batch "
            f"{transaction.batch_number} after {job.attempt_count} attempt"
            f"{'' if job.attempt_count == 1 else 's'}. "
            + (job.failure_reason or "No reason was reported.")
            + " The transaction stays in Integration Pending until this is resolved; nothing has "
            "been marked as posted."
        ),
        transaction_id=transaction.id,
        request_id=transaction.request_id,
        field_name=f"integration.{job.target_system}",
        expected_value="a completed posting",
        actual_value=job.failure_reason or "failed",
    )


async def run_job(session: AsyncSession, job: IntegrationJob) -> IntegrationJob:
    """One attempt at one posting. Never raises out; every outcome ends up on the row.

    An adapter that raises an unexpected exception is a failing integration, not a failing
    request: the failure is recorded against the job, and the transaction is left exactly where
    it was rather than being dragged forward.
    """
    if job.status not in RETRYABLE_JOB_STATUSES:
        return job

    transaction = await load_transaction(session, job.transaction_id)
    if transaction is None:  # pragma: no cover - a job cannot outlive its transaction
        return job

    job.status = IntegrationJobStatus.PROCESSING.value
    job.attempt_count += 1
    job.last_attempted_at = utcnow()
    job.updated_at = utcnow()
    await session.flush()

    adapter = adapter_for(job.target_system)
    try:
        outcome = await adapter.run(session, job, transaction)
    except Exception as exc:
        logger.exception(
            "integration_adapter_raised",
            extra={"target_system": job.target_system, "job_id": str(job.id)},
        )
        outcome = IntegrationOutcome.failed(
            f"{TARGET_LABELS.get(job.target_system, job.target_system)} could not be reached "
            f"({type(exc).__name__}).",
            retryable=True,
            reason=type(exc).__name__,
        )

    await _record_attempt(session, job, transaction, outcome)
    if outcome.kind is OutcomeKind.SUCCEEDED:
        await _apply_success(session, job, transaction, outcome)
    elif outcome.kind is OutcomeKind.AWAITING_MANUAL_ACTION:
        await _apply_awaiting_manual(session, job, transaction, outcome)
    else:
        await _apply_failure(session, job, transaction, outcome)

    await maybe_commit(session, transaction)
    return job


@dataclass
class DispatchResult:
    attempted: int = 0
    succeeded: int = 0
    failed: int = 0
    awaiting_manual: int = 0
    requeued: int = 0


def _tally(result: DispatchResult, job: IntegrationJob) -> None:
    result.attempted += 1
    if job.status == IntegrationJobStatus.SUCCEEDED.value:
        result.succeeded += 1
    elif job.status == IntegrationJobStatus.FAILED.value:
        result.failed += 1
    elif job.status == IntegrationJobStatus.AWAITING_MANUAL_ACTION.value:
        result.awaiting_manual += 1
    else:
        result.requeued += 1


async def dispatch(session: AsyncSession, transaction: TradeTransaction) -> DispatchResult:
    """Attempt every queued job on one transaction, each one independently of the others.

    Run inline on the approval rather than handed to a background task, because an unconfigured
    target - which today is all three on most deployments - resolves without any network call at
    all, and the approver should see the true state immediately rather than a row that says
    `queued` and means nothing yet. A configured adapter carries its own bounded timeout, and the
    sweep, not this function, owns everything that has to wait.

    Each job is run in its own try/except: one target's failure never prevents another target's
    attempt, which is the whole reason these are three independent jobs.
    """
    result = DispatchResult()
    for job in await jobs_for(session, transaction.id):
        if job.status != IntegrationJobStatus.QUEUED.value:
            continue
        try:
            await run_job(session, job)
        except Exception:  # pragma: no cover - run_job already contains adapter failures
            logger.exception(
                "integration_job_dispatch_failed",
                extra={"job_id": str(job.id), "target_system": job.target_system},
            )
            continue
        _tally(result, job)
    return result


# --- the scheduled sweep -------------------------------------------------------------------------


async def due_jobs(session: AsyncSession, *, limit: int) -> list[IntegrationJob]:
    """Every queued job whose backoff has elapsed, oldest attempt first.

    The query deliberately cannot return an `awaiting_manual_action` job: the filter is on
    `queued`, and nothing anywhere moves a job out of `awaiting_manual_action` except an
    administrator's explicit confirmation.
    """
    rows = list(
        (
            await session.scalars(
                select(IntegrationJob)
                .where(IntegrationJob.status == IntegrationJobStatus.QUEUED.value)
                .order_by(
                    IntegrationJob.last_attempted_at.is_(None).desc(),
                    IntegrationJob.last_attempted_at,
                )
                .limit(limit)
            )
        ).all()
    )
    return [row for row in rows if is_due(row)]


async def run_sweep(session: AsyncSession, *, limit: int = 50) -> DispatchResult:
    """One scheduled pass over everything whose next attempt has come due."""
    result = DispatchResult()
    for job in await due_jobs(session, limit=limit):
        try:
            await run_job(session, job)
        except Exception:  # pragma: no cover
            logger.exception("integration_sweep_job_failed", extra={"job_id": str(job.id)})
            continue
        _tally(result, job)
    await session.flush()
    return result


# --- the two administrator actions ---------------------------------------------------------------


async def get_job(session: AsyncSession, job_id: UUID) -> IntegrationJob:
    job = await session.get(IntegrationJob, job_id)
    if job is None:
        raise NotFoundError("Integration job not found.")
    return job


async def retry(session: AsyncSession, job: IntegrationJob, *, user: User) -> IntegrationJob:
    """Re-queue a failed job now, outside its backoff schedule, and attempt it immediately.

    Only a `failed` job. A job awaiting manual action has nothing automated to re-attempt, and
    offering "retry" on it would invite an administrator to press a button that cannot help them;
    the manual-completion action is the one that resolves those, and it is deliberately a
    different action with a different name.
    """
    if job.status != IntegrationJobStatus.FAILED.value:
        raise ConflictError(
            "Only a failed job can be retried. A job waiting on manual action has nothing "
            "automated left to attempt - confirm its completion instead.",
            code="not_retryable",
        )

    previous_attempts = job.attempt_count
    # The counter is reset so the administrator genuinely gets a fresh series of attempts rather
    # than one doomed run against an exhausted ceiling. What it was is on the audit trail.
    job.attempt_count = 0
    job.status = IntegrationJobStatus.QUEUED.value
    job.last_attempted_at = None
    job.updated_at = utcnow()
    await session.flush()

    await record_audit_event(
        session,
        event_type=AuditEvent.JOB_RETRIED,
        entity_type="integration_job",
        entity_id=job.id,
        actor_id=user.id,
        actor_type=ActorType.USER,
        metadata={
            "transaction_id": str(job.transaction_id),
            "target_system": job.target_system,
            "previous_attempts": previous_attempts,
            "previous_failure_reason": job.failure_reason,
        },
    )
    return await run_job(session, job)


async def complete_manually(
    session: AsyncSession,
    job: IntegrationJob,
    *,
    user: User,
    external_reference: str,
    note: str,
) -> IntegrationJob:
    """Record that a person finished this posting outside the platform.

    The reference and the reason are both required, and the fact that this success came from a
    person rather than a call is written into the row itself - not only onto the audit trail -
    so no screen, export or report can present it as an automated posting later.
    """
    if job.status != IntegrationJobStatus.AWAITING_MANUAL_ACTION.value:
        raise ConflictError(
            "Only a job that is waiting on manual action can be confirmed as completed by hand.",
            code="not_awaiting_manual_action",
        )
    reference = (external_reference or "").strip()
    reason = (note or "").strip()
    if not reference:
        raise ConflictError(
            "Give the reference the receiving system produced. A completion with nothing to "
            "point at is not evidence that anything was posted.",
            code="reference_required",
        )
    if len(reason) < MIN_MANUAL_NOTE:
        raise ConflictError(
            f"Give a note of at least {MIN_MANUAL_NOTE} characters saying what was done. This "
            "is the only record of a posting the platform did not make itself.",
            code="reason_required",
        )

    transaction = await load_transaction(session, job.transaction_id)
    if transaction is None:  # pragma: no cover
        raise NotFoundError("The transaction behind this job no longer exists.")

    job.status = IntegrationJobStatus.SUCCEEDED.value
    job.completed_manually = True
    # Both the key and the loaded relationship, so the response this call returns names the
    # person who acted rather than reporting a stale, already-loaded empty one.
    job.completed_manually_by_id = user.id
    job.completed_manually_by = user
    job.completed_manually_at = utcnow()
    job.manual_note = reason
    job.external_reference = reference
    job.failure_reason = None
    job.updated_at = utcnow()
    await session.flush()

    if job.target_system == IntegrationTargetSystem.DMS.value:
        # The packs really are in the DMS now, under the identifier the administrator gave.
        from app.services.integration import document_packs

        await document_packs.mark_filed(
            session,
            await document_packs.packs_for(session, transaction.id),
            dms_document_id=reference,
            filed_at=job.completed_manually_at,
        )

    await record_audit_event(
        session,
        event_type=AuditEvent.JOB_COMPLETED_MANUALLY,
        entity_type="integration_job",
        entity_id=job.id,
        actor_id=user.id,
        actor_type=ActorType.USER,
        metadata={
            "transaction_id": str(transaction.id),
            "batch_number": transaction.batch_number,
            "target_system": job.target_system,
            "external_reference": reference,
            "note": reason,
            # The whole point of this entry: this success was a person's act, not a call's.
            "completed_manually": True,
        },
    )

    await maybe_commit(session, transaction)
    return job


# --- reaching Committed --------------------------------------------------------------------------


async def maybe_commit(session: AsyncSession, transaction: TradeTransaction) -> bool:
    """Move to `Committed`, but only once all three jobs are genuinely `succeeded`.

    A job still queued, still failed, or still waiting on a person leaves the transaction exactly
    where it is. How a job reached `succeeded` - automatically or by an administrator's
    confirmation - makes no difference here and every difference on the job itself.

    Nothing in this function, or anywhere else in this step, sets `Closed`.
    """
    jobs = await jobs_for(session, transaction.id)
    if len(jobs) < len(TARGET_SYSTEMS):
        return False
    if any(job.status != IntegrationJobStatus.SUCCEEDED.value for job in jobs):
        return False
    if transaction.status == TransactionStatus.COMMITTED.value:
        return False

    transaction.status = TransactionStatus.COMMITTED.value
    transaction.updated_at = utcnow()
    await session.flush()

    await record_audit_event(
        session,
        event_type=AuditEvent.TRANSACTION_COMMITTED,
        entity_type="trade_transaction",
        entity_id=transaction.id,
        actor_type=ActorType.SYSTEM,
        metadata={
            "batch_number": transaction.batch_number,
            "jobs": [
                {
                    "target_system": job.target_system,
                    "external_reference": job.external_reference,
                    # Carried into the commit record too, so the trail never loses which of
                    # these postings a person made by hand.
                    "completed_manually": job.completed_manually,
                }
                for job in jobs
            ],
        },
    )
    logger.info(
        "transaction_committed",
        extra={
            "transaction_id": str(transaction.id),
            "manual_completions": sum(1 for job in jobs if job.completed_manually),
        },
    )
    return True

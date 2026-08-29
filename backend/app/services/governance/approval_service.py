"""Approval tasks: creating them, ranking them, and recording what an approver decided.

The identity behind a decision is never negotiable. `decide` takes the acting user as a `User`
row resolved from the verified bearer token, and stamps `decided_at` from the server clock. There
is no parameter, anywhere on this path, that a request body could fill in.

That identity is also what the maker-checker control is enforced against. An approval by the same
account that submitted the transaction is refused outright - see `decide` - because the whole
point of the control is that the person who prepared the figures is not the person who accepts
them. Sending a transaction back is not refused: it is a return to the preparing desk, not a
commitment of anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.core.logging import get_logger
from app.core.roles import PlatformRole
from app.db.base import utcnow
from app.models.enums import ApprovalDecision, TransactionStatus
from app.models.governance import ApprovalTask
from app.models.identity import User
from app.models.transactions import TradeTransaction
from app.services.audit_service import ActorType, record_audit_event
from app.services.governance import exception_service
from app.services.governance.hooks import GovernanceAuditEvent
from app.services.notification_service import (
    notify_approval_decided,
    notify_approval_requested,
)

logger = get_logger(__name__)

DECISIONS_REQUIRING_REASON = frozenset(
    {ApprovalDecision.REJECTED.value, ApprovalDecision.CHANGES_REQUESTED.value}
)

# Where a rejected or a changed-back transaction lands. Neither is terminal: both are a return to
# the desk that raised it, with the figures editable again and the stated reason attached.
RETURN_STATUS = TransactionStatus.VALIDATION_PENDING.value


def aware(moment: datetime) -> datetime:
    """Timestamps read back from SQLite come without a timezone; PostgreSQL's carry one."""
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


async def create_task(
    session: AsyncSession,
    transaction: TradeTransaction,
    *,
    requested_by_id: UUID | None,
    assignee_id: UUID | None = None,
) -> ApprovalTask:
    """Raise the approval task for a transaction that has just reached `Approval Pending`.

    Idempotent on the pending task: a transaction that is already waiting on a decision is not
    given a second one. A transaction that was sent back and re-submitted does get a fresh task,
    because that is genuinely a second request for a decision.
    """
    existing = await session.scalar(
        select(ApprovalTask).where(
            ApprovalTask.transaction_id == transaction.id,
            ApprovalTask.decision == ApprovalDecision.PENDING.value,
        )
    )
    if existing is not None:
        return existing

    task = ApprovalTask(
        transaction_id=transaction.id,
        approver_role=PlatformRole.APPROVER_HOD.value,
        assignee_id=assignee_id,
        requested_by_id=requested_by_id,
        requested_at=utcnow(),
        decision=ApprovalDecision.PENDING.value,
    )
    session.add(task)
    await session.flush()

    await record_audit_event(
        session,
        event_type=GovernanceAuditEvent.APPROVAL_REQUESTED,
        entity_type="approval_task",
        entity_id=task.id,
        actor_id=requested_by_id,
        actor_type=ActorType.USER if requested_by_id else ActorType.SYSTEM,
        metadata={
            "transaction_id": str(transaction.id),
            "batch_number": transaction.batch_number,
            "approver_role": task.approver_role,
        },
    )

    # The task now tells somebody it exists. A named assignee is messaged directly; a task left
    # to whoever on the desk picks it up is broadcast to the approving role, which is exactly who
    # could take it.
    await notify_approval_requested(
        session,
        task_id=task.id,
        approver_role=task.approver_role,
        assignee_id=task.assignee_id,
        batch_number=transaction.batch_number,
        requested_by_id=requested_by_id,
    )
    return task


async def get_task(session: AsyncSession, task_id: UUID) -> ApprovalTask:
    task = await session.get(ApprovalTask, task_id)
    if task is None:
        raise NotFoundError("Approval task not found.")
    return task


@dataclass(frozen=True)
class RiskProfile:
    """Why a transaction is ranked where it is, in words a person can check.

    A stated assumption, not an invented score. Nothing in this 's governing material defines
    a risk model, so rather than manufacture one, risk here means exactly two observable facts: a
    tolerance somebody had to accept by hand, and a history of having gone wrong before. A
    transaction with neither is the clean case; that is the whole of the claim.
    """

    acknowledged_tolerance: bool
    prior_exception: bool
    value: Decimal | None
    above_bulk_ceiling: bool

    @property
    def score(self) -> int:
        return (
            (2 if self.acknowledged_tolerance else 0)
            + (1 if self.prior_exception else 0)
            + (1 if self.above_bulk_ceiling else 0)
        )

    @property
    def label(self) -> str:
        if self.acknowledged_tolerance:
            return "elevated"
        if self.prior_exception or self.above_bulk_ceiling:
            return "watch"
        return "clean"

    @property
    def reasons(self) -> list[str]:
        notes: list[str] = []
        if self.acknowledged_tolerance:
            notes.append(
                "A tolerance breach on this transaction was accepted by the preparing user "
                "rather than corrected."
            )
        if self.prior_exception:
            notes.append("This transaction has been through the exception queue at least once.")
        if self.above_bulk_ceiling:
            notes.append(
                "Its value is above the ceiling for a batch decision, so it is decided on its own."
            )
        if not notes:
            notes.append(
                "Every applicable check passed on the data as it stands, with nothing "
                "acknowledged and no exception in its history."
            )
        return notes

    @property
    def bulk_eligible(self) -> bool:
        """The lowest risk tier, and nothing else.

        Deliberately narrow. A batch decision is the one place an approver is not looking at each
        transaction individually, so anything that has already needed a human judgement call -
        an accepted tolerance, a past exception - or that is large enough to warrant a second
        confirmation on its own is excluded from it.
        """
        return not (self.acknowledged_tolerance or self.prior_exception or self.above_bulk_ceiling)


async def risk_profile(
    session: AsyncSession,
    transaction: TradeTransaction,
    *,
    bulk_ceiling: Decimal,
) -> RiskProfile:
    leg = transaction.purchase_leg
    value = leg.amount if leg and leg.amount is not None else None
    return RiskProfile(
        acknowledged_tolerance=await exception_service.has_acknowledged_tolerance(
            session, transaction.id
        ),
        prior_exception=await exception_service.has_prior_exception(session, transaction.id),
        value=value,
        above_bulk_ceiling=value is None or Decimal(value) > bulk_ceiling,
    )


def rank(
    rows: list[tuple[ApprovalTask, TradeTransaction, RiskProfile]], rank_by: str
) -> list[tuple[ApprovalTask, TradeTransaction, RiskProfile]]:
    """Oldest, largest or riskiest first. Age and value are stored facts; risk is the heuristic."""
    if rank_by == "value":
        return sorted(
            rows,
            key=lambda row: row[2].value if row[2].value is not None else Decimal(0),
            reverse=True,
        )
    if rank_by == "risk":
        return sorted(
            rows,
            key=lambda row: (-row[2].score, aware(row[0].requested_at)),
        )
    return sorted(rows, key=lambda row: aware(row[0].requested_at))


async def decide(
    session: AsyncSession,
    task: ApprovalTask,
    transaction: TradeTransaction,
    *,
    decision: str,
    reason: str | None,
    user: User,
    confirmed_above_threshold: bool,
    confirmation_threshold: Decimal,
    bulk: bool = False,
) -> ApprovalTask:
    """Record one decision, and move the transaction exactly as far as that decision goes.

    An approval reaches `Approved`, and from  that state finally has a consumer: the
    caller raises the three integration jobs against it and the transaction moves on to
    `Integration Pending`. This function still stops at `Approved` itself, deliberately - the
    decision and the postings it authorises are two different acts, and a rejected approval must
    never be able to reach the posting path by sharing a code path with an accepted one.
    """
    # Maker-checker, and the first thing this function decides. BRD 9.1 requires the desk that
    # prepared a transaction to be separate from the desk that accepts it, and an account holding
    # both a preparing role and `approver_hod`/`admin` is otherwise free to do both - the
    # decision would be recorded faithfully, and still be a control failure.
    #
    # Only an approval is barred. A rejection or a request for changes by the submitter returns
    # the transaction to their own desk with a reason attached; nothing is committed, no
    # integration job is raised, and refusing it would only strand work nobody else has picked up.
    #
    # A transaction with no recorded submitter - system-created, or created before this column
    # carried a value - has no self-approval to guard against, so it is not caught here.
    if (
        decision == ApprovalDecision.APPROVED.value
        and transaction.submitted_by_id is not None
        and transaction.submitted_by_id == user.id
    ):
        raise ConflictError(
            "You submitted this transaction for approval, so you cannot also approve it. "
            "A different approver has to decide it. You can still reject it or send it back "
            "for changes.",
            code="segregation_of_duties",
        )

    if task.decision != ApprovalDecision.PENDING.value:
        raise ConflictError(
            f"This transaction was already {task.decision.replace('_', ' ')} "
            f"on {aware(task.decided_at).date() if task.decided_at else 'an earlier date'}."
        )
    if transaction.status != TransactionStatus.APPROVAL_PENDING.value:
        raise ConflictError(
            "This transaction is no longer waiting for approval; its state has moved on."
        )

    cleaned = (reason or "").strip()
    if decision in DECISIONS_REQUIRING_REASON and len(cleaned) < 10:
        raise ConflictError(
            "Sending a transaction back needs a reason of at least 10 characters. The desk that "
            "raised it has to know what to change.",
            code="reason_required",
        )

    leg = transaction.purchase_leg
    value = Decimal(leg.amount) if leg and leg.amount is not None else None
    needs_confirmation = (
        decision == ApprovalDecision.APPROVED.value
        and value is not None
        and value > confirmation_threshold
    )
    if needs_confirmation and not confirmed_above_threshold:
        raise ConflictError(
            f"This transaction is worth {value} {transaction.currency}, above the configured "
            f"{confirmation_threshold} {transaction.currency} threshold. Confirm the approval "
            "explicitly to finalise it.",
            code="confirmation_required",
        )

    # Server-verified identity and server clock, both of them. Nothing from the request body.
    task.decision = decision
    task.decided_by_id = user.id
    task.decided_at = utcnow()
    task.reason = cleaned or None
    task.updated_at = utcnow()

    if decision == ApprovalDecision.APPROVED.value:
        transaction.status = TransactionStatus.APPROVED.value
    else:
        transaction.status = RETURN_STATUS
    transaction.updated_at = utcnow()
    await session.flush()

    await exception_service.close_approval_ageing_case(session, transaction, user=user)

    # One audit entry per decision, including each individual transaction inside a batch: a bulk
    # action is N approvals that happened to be requested together, and the trail has to read
    # that way rather than as one blanket act.
    await record_audit_event(
        session,
        event_type=GovernanceAuditEvent.APPROVAL_DECIDED,
        entity_type="approval_task",
        entity_id=task.id,
        actor_id=user.id,
        actor_type=ActorType.USER,
        metadata={
            "transaction_id": str(transaction.id),
            "batch_number": transaction.batch_number,
            "decision": decision,
            "reason": task.reason,
            "transaction_status": transaction.status,
            "value": str(value) if value is not None else None,
            "currency": transaction.currency,
            "above_confirmation_threshold": bool(needs_confirmation),
            "bulk": bulk,
        },
    )

    # One notification per decided transaction, and the bulk path reaches this function once per
    # transaction, so a batch decision produces N notifications to N submitters rather than one
    # standing in for several. The recipient is resolved from the audit trail, which is the only
    # record of who put this transaction up.
    await notify_approval_decided(
        session,
        transaction_id=transaction.id,
        task_id=task.id,
        batch_number=transaction.batch_number,
        decision=decision,
        reason=task.reason,
        decided_by_id=user.id,
    )
    return task

"""Reading, ageing and resolving exception cases.

Two things are never stored and always computed: how old a case is, and whether it has passed its
ageing threshold. Both are derived from `opened_at` and the configured number of hours at the
moment of the read, exactly as  derives a rule result from the values in front of it. There
is no sweep, no cached flag and nothing that can go stale because a job did not run.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AuthorizationError, ConflictError, NotFoundError
from app.core.roles import PlatformRole
from app.db.base import utcnow
from app.models.enums import (
    ApprovalDecision,
    ExceptionCategory,
    ExceptionPriority,
    TransactionStatus,
)
from app.models.governance import ApprovalTask, ExceptionCase
from app.models.identity import User
from app.models.transactions import RuleEvaluation, TradeTransaction
from app.services.audit_service import ActorType, record_audit_event
from app.services.governance import hooks, thresholds
from app.services.governance.categories import desks_for
from app.services.governance.hooks import GovernanceAuditEvent

# Who may act on an exception at all. Which categories each of them may act on is a second,
# narrower question answered by `desks_for` - Finance works invoice-value cases, not every case.
RESOLVE_ROLES = frozenset(
    {
        PlatformRole.PURCHASE_USER.value,
        PlatformRole.SALES_USER.value,
        PlatformRole.FA_USER.value,
        PlatformRole.LOGISTICS_USER.value,
        PlatformRole.FINANCE_USER.value,
        PlatformRole.ADMIN.value,
    }
)


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def age_hours(case: ExceptionCase, *, now: datetime | None = None) -> float:
    """Whole hours the case has been open, stopping at the moment it was resolved."""
    end = _aware(case.resolved_at) if case.resolved_at else (now or utcnow())
    return max(0.0, (end - _aware(case.opened_at)).total_seconds() / 3600.0)


def is_overdue(case: ExceptionCase, ageing_hours: Decimal, *, now: datetime | None = None) -> bool:
    """Past its ageing threshold. Only ever true of a case that is still open."""
    if case.resolved_at is not None:
        return False
    return age_hours(case, now=now) >= float(ageing_hours)


def may_work(user: User, category: str) -> bool:
    held = set(user.roles or ())
    if not held & RESOLVE_ROLES:
        return False
    return bool(held & desks_for(category))


def require_can_work(user: User, case: ExceptionCase) -> None:
    if not may_work(user, case.exception_type):
        raise AuthorizationError(
            "Your role does not own this category of exception. "
            f"It sits with {case.owner_role.replace('_', ' ')}."
        )


def list_query(
    *,
    exception_type: str | None = None,
    owner_role: str | None = None,
    status: str = "open",
    transaction_id: UUID | None = None,
    search: str | None = None,
) -> Select[tuple[ExceptionCase]]:
    statement = select(ExceptionCase)
    if exception_type:
        statement = statement.where(ExceptionCase.exception_type == exception_type)
    if owner_role:
        statement = statement.where(ExceptionCase.owner_role == owner_role)
    if status == "open":
        statement = statement.where(ExceptionCase.resolved_at.is_(None))
    elif status == "resolved":
        statement = statement.where(ExceptionCase.resolved_at.is_not(None))
    if transaction_id is not None:
        statement = statement.where(ExceptionCase.transaction_id == transaction_id)
    if search:
        term = f"%{search.strip().lower()}%"
        statement = statement.where(
            or_(ExceptionCase.summary.ilike(term), ExceptionCase.rule_id.ilike(term))
        )
    return statement


def apply_minimum_age(statement: Select, minimum_age_hours: float | None) -> Select:
    """Filter on age in the query, from the stored timestamp - never from a stored age."""
    if not minimum_age_hours:
        return statement
    cutoff = utcnow() - timedelta(hours=float(minimum_age_hours))
    return statement.where(ExceptionCase.opened_at <= cutoff)


PRIORITY_ORDER = {
    ExceptionPriority.HIGH.value: 0,
    ExceptionPriority.MEDIUM.value: 1,
    ExceptionPriority.LOW.value: 2,
}


def sort_key(case: ExceptionCase) -> tuple[int, int, datetime]:
    """Escalated first, then priority, then oldest. An escalated case has been asked for."""
    return (
        0 if case.escalated else 1,
        PRIORITY_ORDER.get(case.priority, 1),
        _aware(case.opened_at),
    )


async def ensure_overdue_approval_cases(session: AsyncSession) -> list[ExceptionCase]:
    """Open an 'approval not received' case for every decision that has waited too long.

    Reconciled here, on the read, rather than by a scheduled sweep. There is no notification to
    send yet, so a periodic job would exist only to write a row nobody is waiting on; computing
    the same answer when the queue is opened gives the identical result with nothing to schedule,
    monitor or leave stuck. It is idempotent, so a second read changes nothing.
    """
    overdue_hours = await thresholds.resolve(
        session, thresholds.GovernanceKey.APPROVAL_OVERDUE_HOURS
    )
    cutoff = utcnow() - timedelta(hours=float(overdue_hours))

    stale = list(
        (
            await session.scalars(
                select(ApprovalTask).where(
                    ApprovalTask.decision == ApprovalDecision.PENDING.value,
                    ApprovalTask.requested_at <= cutoff,
                )
            )
        ).all()
    )

    opened: list[ExceptionCase] = []
    for task in stale:
        transaction = await session.get(TradeTransaction, task.transaction_id)
        if transaction is None:
            continue
        waited = int((utcnow() - _aware(task.requested_at)).total_seconds() // 3600)
        case = await hooks.open_case(
            session,
            category=ExceptionCategory.APPROVAL_NOT_RECEIVED.value,
            owner_role=task.approver_role,
            priority=ExceptionPriority.HIGH.value,
            summary=(
                f"Batch {transaction.batch_number} has been waiting for a decision for "
                f"{waited} hours, past the configured {int(overdue_hours)}-hour threshold. "
                "No reminder has been sent: outbound notification does not exist on this "
                "platform yet, so the queue is the only place this is visible."
            ),
            transaction_id=transaction.id,
            request_id=transaction.request_id,
            field_name="approval_task",
            expected_value=f"decided within {int(overdue_hours)} hours",
            actual_value=f"{waited} hours and still pending",
            assigned_to_id=task.assignee_id,
        )
        if case is not None:
            opened.append(case)
    return opened


async def get_case(session: AsyncSession, case_id: UUID) -> ExceptionCase:
    case = await session.get(ExceptionCase, case_id)
    if case is None:
        raise NotFoundError("Exception case not found.")
    return case


async def current_evaluation(session: AsyncSession, case: ExceptionCase) -> RuleEvaluation | None:
    """Where the rule that opened this case stands right now.

    The case carries what the rule said when it opened; this is what it says at this instant. The
    two together are what tells a reader whether their correction actually worked.
    """
    if case.transaction_id is None or case.rule_id is None:
        return None
    statement = select(RuleEvaluation).where(
        RuleEvaluation.transaction_id == case.transaction_id,
        RuleEvaluation.rule_id == case.rule_id,
    )
    statement = (
        statement.where(RuleEvaluation.check_key == case.check_key)
        if case.check_key is not None
        else statement.where(RuleEvaluation.check_key.is_(None))
    )
    return await session.scalar(
        statement.order_by(RuleEvaluation.evaluated_at.desc(), RuleEvaluation.id.desc()).limit(1)
    )


async def underlying_rule_passes(session: AsyncSession, case: ExceptionCase) -> bool | None:
    """True, false, or None when this case has no rule behind it to re-check.

    A low-confidence or an approval-ageing case has no rule; those are closed on the resolver's
    stated note, because there is no machine check that could confirm them. Every case that does
    have a rule is held to it.
    """
    if case.rule_id is None:
        return None
    evaluation = await current_evaluation(session, case)
    # A case that names a rule with no current evaluation behind it counts as still failing.
    # Nothing has demonstrated a pass, and "we could not find the check" is not evidence of one.
    return bool(evaluation.passed) if evaluation is not None else False


async def resolve_case(
    session: AsyncSession,
    case: ExceptionCase,
    *,
    user: User,
    note: str,
) -> ExceptionCase:
    """Close a case, but only once the thing that opened it has actually stopped being true.

    The note alone never closes anything. Where a rule sits behind the case, that rule has to be
    passing at this moment - re-evaluated after whatever correction the caller supplied - or the
    request is refused outright and the case stays exactly where it was.
    """
    if case.resolved_at is not None:
        raise ConflictError("This exception has already been resolved.")

    passes = await underlying_rule_passes(session, case)
    if passes is False:
        evaluation = await current_evaluation(session, case)
        raise ConflictError(
            f"{case.rule_id} is still failing, so this exception cannot be marked resolved. "
            + (evaluation.message if evaluation else "Correct the underlying values first."),
            code="rule_still_failing",
        )

    if case.exception_type == ExceptionCategory.APPROVAL_NOT_RECEIVED.value:
        task = await session.scalar(
            select(ApprovalTask)
            .where(ApprovalTask.transaction_id == case.transaction_id)
            .order_by(ApprovalTask.requested_at.desc())
            .limit(1)
        )
        if task is not None and task.decision == ApprovalDecision.PENDING.value:
            raise ConflictError(
                "This transaction is still waiting on a decision. Record the approval decision "
                "itself; the case closes with it.",
                code="approval_still_pending",
            )

    case.resolved_at = utcnow()
    case.resolved_by_id = user.id
    case.resolution_note = note.strip()
    case.updated_at = utcnow()
    await session.flush()

    await record_audit_event(
        session,
        event_type=GovernanceAuditEvent.EXCEPTION_RESOLVED,
        entity_type="exception_case",
        entity_id=case.id,
        actor_id=user.id,
        actor_type=ActorType.USER,
        metadata={
            "exception_type": case.exception_type,
            "rule_id": case.rule_id,
            "check_key": case.check_key,
            "transaction_id": str(case.transaction_id) if case.transaction_id else None,
            "rule_re_passed": passes is True,
            "note": case.resolution_note,
        },
    )
    return case


async def escalate_case(
    session: AsyncSession, case: ExceptionCase, *, user: User, note: str | None
) -> ExceptionCase:
    """Raise a case's visibility without claiming its cause has been dealt with.

    This is not a resolution and is never treated as one: the case stays open, keeps ageing, and
    still needs the underlying problem fixed. It is for the person who cannot fix it themselves
    and needs a more senior pair of eyes. No message is sent to anyone - outbound notification
    does not exist on this platform yet - so the escalation is visible in the queue and nowhere
    else, which is exactly what the queue says.
    """
    if case.resolved_at is not None:
        raise ConflictError("This exception is already resolved; there is nothing to escalate.")

    case.escalated = True
    case.escalated_at = utcnow()
    case.escalated_by_id = user.id
    case.escalation_note = (note or "").strip() or None
    case.priority = ExceptionPriority.HIGH.value
    case.updated_at = utcnow()
    await session.flush()

    await record_audit_event(
        session,
        event_type=GovernanceAuditEvent.EXCEPTION_ESCALATED,
        entity_type="exception_case",
        entity_id=case.id,
        actor_id=user.id,
        actor_type=ActorType.USER,
        metadata={
            "exception_type": case.exception_type,
            "rule_id": case.rule_id,
            "transaction_id": str(case.transaction_id) if case.transaction_id else None,
            "note": case.escalation_note,
            "notification_sent": False,
        },
    )
    return case


async def close_approval_ageing_case(
    session: AsyncSession, transaction: TradeTransaction, *, user: User
) -> None:
    """Close any 'approval not received' case the moment the decision it was waiting on lands."""
    cases = list(
        (
            await session.scalars(
                select(ExceptionCase).where(
                    ExceptionCase.transaction_id == transaction.id,
                    ExceptionCase.exception_type == ExceptionCategory.APPROVAL_NOT_RECEIVED.value,
                    ExceptionCase.resolved_at.is_(None),
                )
            )
        ).all()
    )
    for case in cases:
        case.resolved_at = utcnow()
        case.resolved_by_id = user.id
        case.resolution_note = "Closed automatically: the decision this case was waiting on "
        case.resolution_note += "has now been recorded."
        case.updated_at = utcnow()
        await record_audit_event(
            session,
            event_type=GovernanceAuditEvent.EXCEPTION_RESOLVED,
            entity_type="exception_case",
            entity_id=case.id,
            actor_id=user.id,
            actor_type=ActorType.USER,
            metadata={
                "exception_type": case.exception_type,
                "transaction_id": str(transaction.id),
                "closed_by": "approval_decision",
            },
        )


async def has_prior_exception(session: AsyncSession, transaction_id: UUID) -> bool:
    """Any exception at all in this transaction's history, open or long since closed."""
    found = await session.scalar(
        select(ExceptionCase.id).where(ExceptionCase.transaction_id == transaction_id).limit(1)
    )
    return found is not None


async def has_acknowledged_tolerance(session: AsyncSession, transaction_id: UUID) -> bool:
    found = await session.scalar(
        select(RuleEvaluation.id)
        .where(
            RuleEvaluation.transaction_id == transaction_id,
            RuleEvaluation.acknowledged.is_(True),
        )
        .limit(1)
    )
    return found is not None


def editable_statuses() -> frozenset[str]:
    """The states in which a transaction's figures may still move."""
    return frozenset(
        {
            TransactionStatus.MATCHED.value,
            TransactionStatus.VALIDATION_PENDING.value,
            TransactionStatus.EXTRACTED.value,
        }
    )

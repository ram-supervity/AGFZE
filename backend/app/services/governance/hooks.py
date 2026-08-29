"""The generic hook that turns a failure into an owned case.

Deliberately kept free of any import of the rule engine or the exception API. The engine calls
into here after it has persisted its evaluations, and the resolve path calls back into the engine
to re-validate; putting both directions in one module would be a cycle. This half knows only how
to read the mapping table and write a case.

Nothing in this file names a rule. It is handed evaluations, asks the mapping what each failing
one means, and writes whatever it is told. That is the whole reason  5 and 6 added rows
rather than branches.

The one judgement it makes for itself is who a case belongs to, and even that is made by looking
at the transaction rather than at the rule - see `owner_role_for`.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.roles import DESK_ROLE_BY_LEG, PlatformRole
from app.models.enums import ExceptionCategory, ExceptionPriority, RuleSeverity
from app.models.governance import ExceptionCase, RuleExceptionMapping
from app.models.intake import Document, Request
from app.models.transactions import RuleEvaluation, TradeTransaction
from app.services.audit_service import ActorType, record_audit_event
from app.services.notification_service import notify_exception_opened

logger = get_logger(__name__)


class GovernanceAuditEvent:
    EXCEPTION_OPENED = "exception.opened"
    EXCEPTION_RESOLVED = "exception.resolved"
    EXCEPTION_ESCALATED = "exception.escalated"
    EXCEPTION_MAPPING_MISSING = "exception.mapping_missing"
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_DECIDED = "approval.decided"


# Which desk carries a request, read off the category the classifier already assigned. Used for a
# low-confidence case, whose owner the matrix defines as "the business user already assigned to
# the request" rather than a fixed desk.
REQUEST_CATEGORY_OWNERS: dict[str, str] = {
    "purchase": PlatformRole.PURCHASE_USER.value,
    "sales": PlatformRole.SALES_USER.value,
    "fa": PlatformRole.FA_USER.value,
    "logistics": PlatformRole.LOGISTICS_USER.value,
}

# The roles that mean "the desk preparing this transaction", read off the shared leg-to-desk map
# rather than restated here. Finance, Admin and the approver are absent because they are not
# leg-derived: an invoice-value case is Finance's whichever desk raised it, and substituting a
# preparing desk for them would be wrong.
DESK_OWNER_ROLES: frozenset[str] = frozenset(DESK_ROLE_BY_LEG.values())


def owner_role_for(transaction: TradeTransaction, mapped_owner: str) -> str:
    """Which desk this case actually belongs to, from the leg the transaction actually carries.

    The mapping table names a default owner, and for the scrap stream that default is usually the
    right answer. It stops being the right answer the moment a rule written about a purchase leg
    is reused - unchanged, which is the point - against a transaction that carries a sales or an
    FA leg instead. BR-05's row says `purchase_user`, and an FA quantity breach routed there
    would sit in a queue the FA desk cannot even open.

    So the mapping's owner is honoured wherever it is a desk this transaction genuinely has, and
    substituted for the desk it does have wherever it is not. Nothing here names a stream: it
    inspects the legs, which is why it worked for the sales leg before FA existed and will work
    for whatever a later  hangs off the same parent.
    """
    if mapped_owner not in DESK_OWNER_ROLES:
        return mapped_owner
    present = [
        role
        for attribute, role in DESK_ROLE_BY_LEG.items()
        if getattr(transaction, attribute, None) is not None
    ]
    if not present or mapped_owner in present:
        return mapped_owner
    return present[0]


async def mapping_for(
    session: AsyncSession, rule_id: str, check_key: str | None
) -> RuleExceptionMapping | None:
    """The category a failing rule opens. The row naming the check wins over the rule-wide row."""
    rows = list(
        (
            await session.scalars(
                select(RuleExceptionMapping).where(
                    RuleExceptionMapping.rule_id == rule_id,
                    RuleExceptionMapping.is_active.is_(True),
                    RuleExceptionMapping.check_key.in_([check_key, None])
                    if check_key is not None
                    else RuleExceptionMapping.check_key.is_(None),
                )
            )
        ).all()
    )
    if not rows:
        return None
    return max(rows, key=lambda row: row.specificity)


async def existing_open_case(
    session: AsyncSession,
    *,
    category: str,
    transaction_id: UUID | None,
    document_id: UUID | None,
) -> ExceptionCase | None:
    """The unresolved case already covering this subject and category, if there is one.

    The subject is the transaction where there is one and the document otherwise, which is what
    makes the check meaningful for a low-confidence case raised before matching has run.
    """
    statement = select(ExceptionCase).where(
        ExceptionCase.exception_type == category,
        ExceptionCase.resolved_at.is_(None),
    )
    if transaction_id is not None:
        statement = statement.where(ExceptionCase.transaction_id == transaction_id)
    elif document_id is not None:
        statement = statement.where(
            ExceptionCase.transaction_id.is_(None),
            ExceptionCase.document_id == document_id,
        )
    else:
        return None
    return await session.scalar(statement.order_by(ExceptionCase.opened_at).limit(1))


async def open_case(
    session: AsyncSession,
    *,
    category: str,
    owner_role: str,
    summary: str,
    priority: str = ExceptionPriority.MEDIUM.value,
    transaction_id: UUID | None = None,
    document_id: UUID | None = None,
    request_id: UUID | None = None,
    rule_id: str | None = None,
    check_key: str | None = None,
    field_name: str | None = None,
    expected_value: str | None = None,
    actual_value: str | None = None,
    assigned_to_id: UUID | None = None,
) -> ExceptionCase | None:
    """Open one case, or return None because an unresolved one already covers this.

    Idempotent by construction: re-running validation against a transaction that is still failing
    the same way adds nothing. The queue shows one problem once, ageing from when it first
    appeared, rather than a new row per re-validation.
    """
    duplicate = await existing_open_case(
        session, category=category, transaction_id=transaction_id, document_id=document_id
    )
    if duplicate is not None:
        return None

    case = ExceptionCase(
        transaction_id=transaction_id,
        document_id=document_id,
        request_id=request_id,
        exception_type=category,
        rule_id=rule_id,
        check_key=check_key,
        owner_role=owner_role,
        assigned_to_id=assigned_to_id,
        priority=priority,
        summary=summary,
        field_name=field_name,
        expected_value=expected_value,
        actual_value=actual_value,
    )
    session.add(case)
    await session.flush()

    await record_audit_event(
        session,
        event_type=GovernanceAuditEvent.EXCEPTION_OPENED,
        entity_type="exception_case",
        entity_id=case.id,
        actor_type=ActorType.SYSTEM,
        metadata={
            "exception_type": category,
            "owner_role": owner_role,
            "priority": priority,
            "rule_id": rule_id,
            "check_key": check_key,
            "transaction_id": str(transaction_id) if transaction_id else None,
            "document_id": str(document_id) if document_id else None,
            "field_name": field_name,
        },
    )

    # 's one addition to this function. The desk that owns the case is told it exists,
    # through the single shared notification service - a case is a role's work, so this is a
    # broadcast to every active holder of that role rather than a message to one person.
    batch_number: str | None = None
    if transaction_id is not None:
        transaction = await session.get(TradeTransaction, transaction_id)
        batch_number = transaction.batch_number if transaction is not None else None
    await notify_exception_opened(
        session,
        case_id=case.id,
        owner_role=owner_role,
        summary=summary,
        batch_number=batch_number,
    )
    return case


def is_hard_failure(evaluation: RuleEvaluation) -> bool:
    """A failure with no self-approval path.

    The invoice amount's middle tier is `acknowledgeable` and fails only until the preparing user
    accepts it in the workspace; it is not this queue's business and never opens a case. Anything
    the rule itself marked `hard` is.
    """
    return not evaluation.passed and evaluation.severity == RuleSeverity.HARD.value


async def record_hard_failures(
    session: AsyncSession,
    transaction: TradeTransaction,
    evaluations: list[RuleEvaluation],
) -> list[ExceptionCase]:
    """Open a case for every genuine hard failure in a validation run.

    Called by the orchestrator immediately after it persists its rows, for any rule at all. There
    is no list of rule identifiers here, and adding one would be the bug this whole arrangement
    exists to prevent.
    """
    opened: list[ExceptionCase] = []
    for evaluation in evaluations:
        if not is_hard_failure(evaluation):
            continue

        mapping = await mapping_for(session, evaluation.rule_id, evaluation.check_key)
        if mapping is None:
            # Never invented: a rule nobody has categorised does not get a guessed category. The
            # failure is still blocking the transaction and visible on its validation panel, and
            # the gap in the mapping table is recorded so an administrator can close it.
            logger.warning(
                "exception_mapping_missing",
                extra={"rule_id": evaluation.rule_id, "check_key": evaluation.check_key},
            )
            await record_audit_event(
                session,
                event_type=GovernanceAuditEvent.EXCEPTION_MAPPING_MISSING,
                entity_type="trade_transaction",
                entity_id=transaction.id,
                actor_type=ActorType.SYSTEM,
                metadata={"rule_id": evaluation.rule_id, "check_key": evaluation.check_key},
            )
            continue

        case = await open_case(
            session,
            category=mapping.exception_type,
            owner_role=owner_role_for(transaction, mapping.owner_role),
            priority=mapping.priority,
            summary=evaluation.message,
            transaction_id=transaction.id,
            request_id=transaction.request_id,
            rule_id=evaluation.rule_id,
            check_key=evaluation.check_key,
            field_name=evaluation.field_name,
            expected_value=evaluation.expected_value,
            actual_value=evaluation.actual_value,
        )
        if case is not None:
            opened.append(case)
    return opened


async def record_low_confidence(
    session: AsyncSession,
    document: Document,
    *,
    threshold: float,
    lowest_confidence: float | None,
    field_names: list[str],
) -> ExceptionCase | None:
    """Formalise 's inline confidence flag into an owned, ageing case.

    The inline flag stays exactly where it was - it is what makes a doubtful value obvious while
    somebody is looking at the document. The case is what gives that doubt an owner and a clock
    when nobody is.
    """
    request = await session.get(Request, document.request_id)
    owner_role = REQUEST_CATEGORY_OWNERS.get(
        (request.category or "") if request else "", PlatformRole.PURCHASE_USER.value
    )
    assignee = None
    if request is not None:
        assignee = request.created_by_id
    assignee = assignee or document.uploaded_by_id

    scored = f"{lowest_confidence:.0%}" if lowest_confidence is not None else "no score at all"
    detail = ", ".join(sorted(field_names)[:6]) if field_names else "its classification"
    return await open_case(
        session,
        category=ExceptionCategory.LOW_CONFIDENCE.value,
        owner_role=owner_role,
        priority=ExceptionPriority.MEDIUM.value,
        summary=(
            f"'{document.filename}' was read at {scored}, below the {threshold:.0%} confidence "
            f"threshold. Check {detail} against the source page before this document is relied "
            "on."
        ),
        transaction_id=document.transaction_id,
        document_id=document.id,
        request_id=document.request_id,
        field_name=field_names[0] if field_names else None,
        expected_value=f"at or above {threshold:.0%} confidence",
        actual_value=scored,
        assigned_to_id=assignee,
    )

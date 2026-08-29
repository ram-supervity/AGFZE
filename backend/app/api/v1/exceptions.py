"""The exception queue: what is wrong, whose it is, how long it has been wrong, and closing it.

Reads are open to every signed-in account, which is the platform's transparency principle. Acting
on a case is narrower twice over: the caller must hold a desk role at all, and must hold one of
the desks the matrix gives that particular category. Finance sees every tab and may only settle
invoice-value cases; that second check is made here, server-side, not by hiding a button.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core.dependencies import CurrentUser, DbSession, require_roles
from app.core.errors import ConflictError
from app.core.roles import ALL_ROLES
from app.models.enums import EXCEPTION_CATEGORIES
from app.models.governance import ExceptionCase
from app.models.identity import User
from app.models.intake import Document
from app.models.transactions import TradeTransaction
from app.schemas.common import ResponseEnvelope
from app.schemas.governance import (
    ExceptionCaseDetail,
    ExceptionCaseListItem,
    ExceptionCategoryRead,
    ExceptionQueue,
    ExceptionResolution,
)
from app.schemas.intake import DocumentSummary, Page
from app.schemas.transaction import RuleEvaluationRead
from app.services import transaction_fields, transaction_service
from app.services.governance import exception_service, thresholds
from app.services.governance.categories import CATEGORY_BY_NAME, CATEGORY_CATALOG
from app.services.rules.catalog import RULE_BY_ID
from app.services.storage import get_storage_service

router = APIRouter(prefix="/exceptions", tags=["exceptions"])

# Every desk that may resolve anything. Which categories each of them may resolve is a second,
# narrower check made per case inside the handler, from the matrix's own ownership.
ExceptionWorker = Annotated[User, Depends(require_roles(*sorted(exception_service.RESOLVE_ROLES)))]


def _label(category: str) -> str:
    definition = CATEGORY_BY_NAME.get(category)
    return definition.label if definition else category.replace("_", " ").capitalize()


async def _list_item(
    session: DbSession,
    case: ExceptionCase,
    ageing_hours: float,
    *,
    transaction: TradeTransaction | None = None,
) -> ExceptionCaseListItem:
    item = ExceptionCaseListItem.model_validate(case)
    item.exception_label = _label(case.exception_type)
    hours = exception_service.age_hours(case)
    item.age_hours = round(hours, 2)
    item.age_days = int(hours // 24)
    item.overdue = exception_service.is_overdue(case, ageing_hours)
    item.ageing_threshold_hours = int(ageing_hours)
    item.assigned_to_name = case.assigned_to.display_name if case.assigned_to else None

    if transaction is None and case.transaction_id is not None:
        transaction = await session.get(TradeTransaction, case.transaction_id)
    if transaction is not None:
        item.batch_number = transaction.batch_number
        item.currency = transaction.currency
        leg = transaction.purchase_leg
        # Named from whichever leg the transaction carries. A sales-only or FA case reporting no
        # counterparty at all would be a queue row nobody can identify at a glance.
        item.counterparty = (
            (leg.supplier_name if leg else None)
            or (transaction.sales_leg.customer_name if transaction.sales_leg else None)
            or (transaction.fa_leg.counterparty_name if transaction.fa_leg else None)
        )
        item.value = leg.amount if leg else None
    return item


@router.get(
    "",
    response_model=ResponseEnvelope[ExceptionQueue],
    summary="Paginated, filterable exception queue with every category tab",
)
async def list_exceptions(
    user: CurrentUser,
    session: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    exception_type: str | None = Query(None),
    owner_role: str | None = Query(None),
    status: str = Query("open", pattern="^(open|resolved|all)$"),
    min_age_hours: float | None = Query(None, ge=0),
    search: str | None = Query(None, max_length=200),
) -> ResponseEnvelope[ExceptionQueue]:
    if exception_type and exception_type not in EXCEPTION_CATEGORIES:
        exception_type = None
    if owner_role and owner_role not in ALL_ROLES:
        owner_role = None

    # An approval that has waited too long is a real exception, reconciled here from the stored
    # timestamps rather than by a job. Doing it on the read is what keeps ageing live.
    await exception_service.ensure_overdue_approval_cases(session)
    await session.commit()

    ageing_hours = float(
        await thresholds.resolve(session, thresholds.GovernanceKey.EXCEPTION_AGEING_HOURS)
    )

    statement = exception_service.apply_minimum_age(
        exception_service.list_query(
            exception_type=exception_type,
            owner_role=owner_role,
            status=status,
            search=search,
        ),
        min_age_hours,
    )
    total = int(await session.scalar(select(func.count()).select_from(statement.subquery())) or 0)

    rows = list(
        (
            await session.scalars(
                statement.options(selectinload(ExceptionCase.assigned_to))
                .order_by(ExceptionCase.escalated.desc(), ExceptionCase.opened_at)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )

    # Per-tab open counts, so the queue can show where the work actually is - including a
    # truthful zero on the three categories nothing can raise yet.
    counted = dict(
        (
            await session.execute(
                select(ExceptionCase.exception_type, func.count(ExceptionCase.id))
                .where(ExceptionCase.resolved_at.is_(None))
                .group_by(ExceptionCase.exception_type)
            )
        ).all()
    )

    return ResponseEnvelope[ExceptionQueue](
        data=ExceptionQueue(
            items=[await _list_item(session, row, ageing_hours) for row in rows],
            page=Page(
                page=page,
                page_size=page_size,
                total=total,
                total_pages=max(1, -(-total // page_size)),
            ),
            categories=[
                ExceptionCategoryRead(
                    category=definition.category,
                    label=definition.label,
                    owner_role=definition.owner_role,
                    shared_with=list(definition.shared_with),
                    triggerable=definition.triggerable,
                    description=definition.description,
                    dormant_reason=definition.dormant_reason,
                    open_count=int(counted.get(definition.category, 0)),
                )
                for definition in CATEGORY_CATALOG
            ],
            ageing_threshold_hours=int(ageing_hours),
        )
    )


async def _detail(session: DbSession, case: ExceptionCase, user: User) -> ExceptionCaseDetail:
    ageing_hours = float(
        await thresholds.resolve(session, thresholds.GovernanceKey.EXCEPTION_AGEING_HOURS)
    )
    transaction = (
        await session.get(TradeTransaction, case.transaction_id)
        if case.transaction_id is not None
        else None
    )
    base = await _list_item(session, case, ageing_hours, transaction=transaction)
    detail = ExceptionCaseDetail(**base.model_dump())

    detail.request_id = case.request_id
    detail.resolution_note = case.resolution_note
    detail.resolved_by_name = case.resolved_by.display_name if case.resolved_by else None
    detail.escalated_at = case.escalated_at
    detail.escalated_by_name = case.escalated_by.display_name if case.escalated_by else None
    detail.escalation_note = case.escalation_note
    detail.transaction_status = transaction.status if transaction else None

    evaluation = await exception_service.current_evaluation(session, case)
    if evaluation is not None:
        read = RuleEvaluationRead.model_validate(evaluation)
        definition = RULE_BY_ID.get(evaluation.rule_id)
        read.title = definition.title if definition else None
        read.statement = definition.statement if definition else None
        detail.current_evaluation = read
    detail.rule_now_passes = await exception_service.underlying_rule_passes(session, case)

    documents: list[Document] = []
    if case.transaction_id is not None:
        documents = list(
            (
                await session.scalars(
                    select(Document)
                    .where(Document.transaction_id == case.transaction_id)
                    .order_by(Document.created_at)
                )
            ).all()
        )
    elif case.document_id is not None:
        one = await session.get(Document, case.document_id)
        documents = [one] if one is not None else []

    storage = get_storage_service()
    summaries: list[DocumentSummary] = []
    for document in documents:
        summary = DocumentSummary.model_validate(document)
        refs = document.page_image_refs or []
        summary.thumbnail_url = await storage.get_signed_url(refs[0]) if refs else None
        summaries.append(summary)
    detail.documents = summaries

    may_work = exception_service.may_work(user, case.exception_type)
    open_case = case.resolved_at is None
    detail.can_resolve = may_work and open_case
    detail.can_escalate = may_work and open_case and not case.escalated
    if not may_work:
        detail.resolve_blocked_reason = (
            "This category is worked by "
            f"{case.owner_role.replace('_', ' ')}, which your account does not hold."
        )
    elif not open_case:
        detail.resolve_blocked_reason = "This case has already been resolved."
    elif detail.rule_now_passes is False:
        detail.resolve_blocked_reason = (
            f"{case.rule_id} is still failing. Correct the underlying values - the case can only "
            "be closed once the check actually passes."
        )
    return detail


@router.get(
    "/{case_id}",
    response_model=ResponseEnvelope[ExceptionCaseDetail],
    summary="Full case detail: the rule, the field, the values and where they stand now",
)
async def read_exception(
    case_id: UUID, user: CurrentUser, session: DbSession
) -> ResponseEnvelope[ExceptionCaseDetail]:
    case = await exception_service.get_case(session, case_id)
    return ResponseEnvelope[ExceptionCaseDetail](data=await _detail(session, case, user))


@router.post(
    "/{case_id}/resolve",
    response_model=ResponseEnvelope[ExceptionCaseDetail],
    summary="Resolve a case with a genuine fix, and/or escalate it to the HOD",
)
async def resolve_exception(
    case_id: UUID,
    payload: ExceptionResolution,
    user: ExceptionWorker,
    session: DbSession,
) -> ResponseEnvelope[ExceptionCaseDetail]:
    """Close a case only once the thing behind it has actually stopped being true.

    A correction, where one is supplied, goes through the very same service call the transaction
    workspace's own field editor uses, so it carries the same reason gate, the same provenance
    record and the same synchronous re-validation. The re-validated result is then what decides
    whether this case may close - never the note.

    Escalating is a separate outcome and says so: it raises the case, leaves it open, and claims
    nothing about the underlying problem. No message is sent to anybody, because this platform
    cannot send one yet.
    """
    case = await exception_service.get_case(session, case_id)
    exception_service.require_can_work(user, case)

    messages: list[str] = []

    if payload.correction is not None:
        if case.transaction_id is None:
            raise ConflictError(
                "This case is not attached to a transaction, so there is no field on it to "
                "correct here."
            )
        transaction = await transaction_service.get_transaction(session, case.transaction_id)
        changed = await transaction_fields.apply_corrections(
            session,
            transaction,
            [(payload.correction.name, payload.correction.value, payload.correction.reason)],
            user=user,
            audit_event_type=transaction_service.AuditEvent.TRANSACTION_FIELD_CORRECTED,
            audit_context={"origin": "exception_queue", "exception_case_id": str(case.id)},
        )
        messages.append(
            f"{len(changed)} field corrected and every check re-run."
            if changed
            else "No field value changed; the checks were re-run against the current values."
        )

    if payload.escalate_to_hod:
        await exception_service.escalate_case(
            session, case, user=user, note=payload.resolution_note
        )
        await session.commit()
        refreshed = await exception_service.get_case(session, case_id)
        messages.append(
            "Escalated to the HOD and given elevated priority in the queue. The underlying "
            "problem is not resolved, and no notification has been sent - outbound notification "
            "does not exist on this platform yet."
        )
        return ResponseEnvelope[ExceptionCaseDetail](
            data=await _detail(session, refreshed, user), message=" ".join(messages)
        )

    await exception_service.resolve_case(session, case, user=user, note=payload.resolution_note)
    await session.commit()

    refreshed = await exception_service.get_case(session, case_id)
    messages.append(
        f"{_label(case.exception_type)} resolved and closed against your account."
        if refreshed.rule_id is None
        else f"{refreshed.rule_id} now passes, so the case is closed."
    )
    return ResponseEnvelope[ExceptionCaseDetail](
        data=await _detail(session, refreshed, user), message=" ".join(messages)
    )

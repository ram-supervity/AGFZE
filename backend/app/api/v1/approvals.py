"""The approval queue and the decision that closes it.

Everyone signed in may read this queue and any single approval in it - an approval that only its
approver can see is not a governed decision, it is a private one. Only the approver may decide,
and that is enforced by the dependency on the write endpoints rather than by what the screen
chooses to render.

An approved decision is where this module's work ends and the integration hub's begins. The
decision itself is recorded by `approval_service.decide`, which reaches `Approved` and stops;
this endpoint then raises the three integration jobs against it and moves the transaction to
`Integration Pending`. A rejection or a request for changes touches none of that: it returns the
transaction to the desk that raised it, exactly as it always has.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core.dependencies import CurrentUser, DbSession, require_roles
from app.core.errors import ConflictError, NotFoundError
from app.core.logging import get_logger
from app.core.roles import PlatformRole
from app.db.base import utcnow
from app.models.enums import ApprovalDecision
from app.models.governance import ApprovalTask, ExceptionCase
from app.models.identity import User
from app.models.intake import Document, Request
from app.models.transactions import TradeTransaction
from app.schemas.common import ResponseEnvelope
from app.schemas.governance import (
    ApprovalDecisionRequest,
    ApprovalDetail,
    ApprovalListItem,
    ApprovalQueue,
    ApprovalRiskRead,
    ApprovalSummaryRead,
    BulkApprovalOutcome,
    BulkApprovalRequest,
    BulkApprovalResult,
)
from app.schemas.intake import DocumentSummary, Page
from app.schemas.transaction import RuleEvaluationRead
from app.services import gemini_service
from app.services.governance import approval_service, thresholds
from app.services.governance.approval_service import RiskProfile
from app.services.integration import integration_service
from app.services.rules import engine as rule_engine
from app.services.rules.catalog import RULE_BY_ID
from app.services.storage import get_storage_service

logger = get_logger(__name__)

router = APIRouter(prefix="/approvals", tags=["approvals"])

Approver = Annotated[
    User,
    Depends(require_roles(PlatformRole.APPROVER_HOD.value, PlatformRole.ADMIN.value)),
]


def _may_decide(user: User) -> bool:
    return bool(
        {PlatformRole.APPROVER_HOD.value, PlatformRole.ADMIN.value}.intersection(user.roles or ())
    )


def _risk_read(profile: RiskProfile) -> ApprovalRiskRead:
    return ApprovalRiskRead(
        label=profile.label,
        score=profile.score,
        reasons=profile.reasons,
        acknowledged_tolerance=profile.acknowledged_tolerance,
        prior_exception=profile.prior_exception,
        bulk_eligible=profile.bulk_eligible,
    )


def _list_item(
    task: ApprovalTask,
    transaction: TradeTransaction,
    profile: RiskProfile,
    *,
    overdue_hours: float,
    confirmation_threshold: Decimal,
) -> ApprovalListItem:
    leg = transaction.purchase_leg
    hours = max(
        0.0,
        (utcnow() - approval_service.aware(task.requested_at)).total_seconds() / 3600.0,
    )
    value = leg.amount if leg else None
    # Whichever desk's leg names the other side of the deal. An FA transaction reaching the
    # approval queue is named by its counterparty, exactly as a purchase one is by its supplier.
    counterparty = (
        (leg.supplier_name if leg else None)
        or (transaction.sales_leg.customer_name if transaction.sales_leg else None)
        or (transaction.fa_leg.counterparty_name if getattr(transaction, "fa_leg", None) else None)
    )
    return ApprovalListItem(
        id=task.id,
        transaction_id=transaction.id,
        batch_number=transaction.batch_number,
        counterparty=counterparty,
        contract_number=leg.contract_number if leg else None,
        commodity_name=transaction.commodity.display_name if transaction.commodity else None,
        quantity_mt=transaction.quantity_mt,
        value=value,
        currency=transaction.currency,
        decision=task.decision,
        requested_at=task.requested_at,
        requested_by_name=task.requested_by.display_name if task.requested_by else None,
        decided_at=task.decided_at,
        decided_by_name=task.decided_by.display_name if task.decided_by else None,
        reason=task.reason,
        age_hours=round(hours, 2),
        age_days=int(hours // 24),
        overdue=task.decision == ApprovalDecision.PENDING.value and hours >= overdue_hours,
        risk=_risk_read(profile),
        requires_confirmation=value is not None and Decimal(value) > confirmation_threshold,
    )


async def _load_transaction(session: DbSession, task: ApprovalTask) -> TradeTransaction:
    transaction = await session.scalar(
        select(TradeTransaction)
        .where(TradeTransaction.id == task.transaction_id)
        .options(
            selectinload(TradeTransaction.purchase_leg),
            selectinload(TradeTransaction.commodity),
        )
    )
    if transaction is None:
        raise NotFoundError("The transaction behind this approval no longer exists.")
    return transaction


@router.get(
    "",
    response_model=ResponseEnvelope[ApprovalQueue],
    summary="The ranked approval queue (rank_by: age, value or risk)",
)
async def list_approvals(
    user: CurrentUser,
    session: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    rank_by: str = Query("age", pattern="^(age|value|risk)$"),
    decision: str = Query("pending"),
) -> ResponseEnvelope[ApprovalQueue]:
    configured = await thresholds.resolve_many(
        session,
        thresholds.GovernanceKey.APPROVAL_CONFIRMATION_VALUE,
        thresholds.GovernanceKey.BULK_APPROVAL_VALUE_CEILING,
        thresholds.GovernanceKey.APPROVAL_OVERDUE_HOURS,
    )
    confirmation = configured[thresholds.GovernanceKey.APPROVAL_CONFIRMATION_VALUE]
    ceiling = configured[thresholds.GovernanceKey.BULK_APPROVAL_VALUE_CEILING]
    overdue_hours = float(configured[thresholds.GovernanceKey.APPROVAL_OVERDUE_HOURS])

    statement = select(ApprovalTask)
    if decision != "all":
        statement = statement.where(ApprovalTask.decision == decision)
    total = int(await session.scalar(select(func.count()).select_from(statement.subquery())) or 0)

    tasks = list(
        (
            await session.scalars(
                statement.options(
                    selectinload(ApprovalTask.requested_by),
                    selectinload(ApprovalTask.decided_by),
                ).order_by(ApprovalTask.requested_at)
            )
        ).all()
    )

    # Ranked over the whole queue and then paged, not paged and then ranked: "oldest first" has
    # to mean oldest of everything waiting, not oldest of whichever 25 rows came back.
    rows: list[tuple[ApprovalTask, TradeTransaction, RiskProfile]] = []
    for task in tasks:
        transaction = await session.scalar(
            select(TradeTransaction)
            .where(TradeTransaction.id == task.transaction_id)
            .options(
                selectinload(TradeTransaction.purchase_leg),
                selectinload(TradeTransaction.commodity),
            )
        )
        if transaction is None:
            continue
        rows.append(
            (
                task,
                transaction,
                await approval_service.risk_profile(session, transaction, bulk_ceiling=ceiling),
            )
        )

    ranked = approval_service.rank(rows, rank_by)
    window = ranked[(page - 1) * page_size : (page - 1) * page_size + page_size]

    return ResponseEnvelope[ApprovalQueue](
        data=ApprovalQueue(
            items=[
                _list_item(
                    task,
                    transaction,
                    profile,
                    overdue_hours=overdue_hours,
                    confirmation_threshold=confirmation,
                )
                for task, transaction, profile in window
            ],
            page=Page(
                page=page,
                page_size=page_size,
                total=total,
                total_pages=max(1, -(-total // page_size)),
            ),
            rank_by=rank_by,
            confirmation_threshold=confirmation,
            bulk_value_ceiling=ceiling,
            overdue_threshold_hours=int(overdue_hours),
            can_decide=_may_decide(user),
        )
    )


def _summary_facts(transaction: TradeTransaction, evaluations: list) -> dict[str, object]:
    """The facts handed to the model, assembled from whatever legs the transaction carries.

    Read generically: a sales or an FA leg becomes part of the summary by existing, because this
    walks what is on the record rather than naming the purchase leg and stopping.
    """
    facts: dict[str, object] = {
        "batch number": transaction.batch_number,
        "business stream": transaction.stream,
        "commodity": (
            transaction.commodity.display_name
            if transaction.commodity
            else transaction.commodity_code
        ),
        "quantity (MT)": str(transaction.quantity_mt) if transaction.quantity_mt else None,
        "currency": transaction.currency,
        "price basis": transaction.price_basis,
        "LME percentage": (str(transaction.lme_percentage) if transaction.lme_percentage else None),
        "status": transaction.status,
    }
    for name in ("purchase_leg", "sales_leg", "fa_leg"):
        leg = getattr(transaction, name, None)
        if leg is None:
            continue
        prefix = name.replace("_leg", "")
        for column in leg.__table__.columns:
            if column.name in {"id", "transaction_id", "created_at", "updated_at"}:
                continue
            value = getattr(leg, column.name, None)
            if value is not None:
                facts[f"{prefix} {column.name.replace('_', ' ')}"] = str(value)

    facts["checks that passed"] = [
        f"{row.rule_id}: {row.message}" for row in evaluations if row.passed
    ]
    facts["checks accepted by a person rather than earned"] = [
        f"{row.rule_id}: {row.acknowledgement_reason}" for row in evaluations if row.acknowledged
    ]
    return facts


async def _ai_summary(
    session: DbSession, task: ApprovalTask, transaction: TradeTransaction, evaluations: list
) -> ApprovalSummaryRead:
    """Generate the note on first view and keep it; never regenerate it for a repeat view.

    A failure here is never allowed to matter. The caller renders the whole decision screen from
    the transaction either way, and the approver can do their job without ever seeing this.
    """
    if task.ai_summary:
        return ApprovalSummaryRead(
            available=True,
            summary=task.ai_summary,
            generated_at=task.ai_summary_generated_at,
        )

    try:
        generated = await gemini_service.summarize_for_approval(
            _summary_facts(transaction, evaluations)
        )
    except gemini_service.AIServiceError as exc:
        logger.warning(
            "approval_summary_unavailable",
            extra={"approval_task_id": str(task.id), "reason": exc.reason},
        )
        task.ai_summary_error = exc.reason
        await session.flush()
        return ApprovalSummaryRead(
            available=False,
            unavailable_reason=(
                "The summary could not be generated. Everything below is the transaction's own "
                "recorded data and is complete without it."
            ),
        )

    body = generated.summary.strip()
    if generated.what_to_check:
        body += "\n\nWorth checking yourself:\n" + "\n".join(
            f"- {item}" for item in generated.what_to_check[:4]
        )
    task.ai_summary = body
    task.ai_summary_generated_at = utcnow()
    task.ai_summary_error = None
    await session.flush()
    return ApprovalSummaryRead(
        available=True,
        summary=body,
        what_to_check=list(generated.what_to_check[:4]),
        generated_at=task.ai_summary_generated_at,
    )


@router.get(
    "/{approval_id}",
    response_model=ResponseEnvelope[ApprovalDetail],
    summary="Full approval detail, with the AI summary generated once and cached",
)
async def read_approval(
    approval_id: UUID, user: CurrentUser, session: DbSession
) -> ResponseEnvelope[ApprovalDetail]:
    task = await approval_service.get_task(session, approval_id)
    transaction = await _load_transaction(session, task)

    configured = await thresholds.resolve_many(
        session,
        thresholds.GovernanceKey.APPROVAL_CONFIRMATION_VALUE,
        thresholds.GovernanceKey.BULK_APPROVAL_VALUE_CEILING,
        thresholds.GovernanceKey.APPROVAL_OVERDUE_HOURS,
    )
    confirmation = configured[thresholds.GovernanceKey.APPROVAL_CONFIRMATION_VALUE]
    ceiling = configured[thresholds.GovernanceKey.BULK_APPROVAL_VALUE_CEILING]
    overdue_hours = float(configured[thresholds.GovernanceKey.APPROVAL_OVERDUE_HOURS])

    profile = await approval_service.risk_profile(session, transaction, bulk_ceiling=ceiling)
    evaluations = await rule_engine.current_results(session, transaction.id)

    base = _list_item(
        task,
        transaction,
        profile,
        overdue_hours=overdue_hours,
        confirmation_threshold=confirmation,
    )
    summary = await _ai_summary(session, task, transaction, evaluations)
    await session.commit()

    leg = transaction.purchase_leg
    request = await session.get(Request, transaction.request_id)
    submitted_by = (
        await session.get(User, transaction.submitted_by_id)
        if transaction.submitted_by_id
        else None
    )

    documents = list(
        (
            await session.scalars(
                select(Document)
                .where(Document.transaction_id == transaction.id)
                .order_by(Document.created_at)
            )
        ).all()
    )
    storage = get_storage_service()
    summaries: list[DocumentSummary] = []
    for document in documents:
        item = DocumentSummary.model_validate(document)
        refs = document.page_image_refs or []
        item.thumbnail_url = await storage.get_signed_url(refs[0]) if refs else None
        summaries.append(item)

    open_exceptions = int(
        await session.scalar(
            select(func.count(ExceptionCase.id)).where(
                ExceptionCase.transaction_id == transaction.id,
                ExceptionCase.resolved_at.is_(None),
            )
        )
        or 0
    )

    rules: list[RuleEvaluationRead] = []
    for row in evaluations:
        read = RuleEvaluationRead.model_validate(row)
        definition = RULE_BY_ID.get(row.rule_id)
        read.title = definition.title if definition else None
        read.statement = definition.statement if definition else None
        read.acknowledged_by_name = (
            row.acknowledged_by.display_name if row.acknowledged_by else None
        )
        rules.append(read)

    return ResponseEnvelope[ApprovalDetail](
        data=ApprovalDetail(
            **base.model_dump(),
            transaction_status=transaction.status,
            request_code=request.request_code if request else None,
            submitted_by_name=submitted_by.display_name if submitted_by else None,
            submitted_at=transaction.submitted_at,
            price_basis=transaction.price_basis,
            lme_percentage=transaction.lme_percentage,
            rate=leg.rate if leg else None,
            invoice_status=leg.invoice_status if leg else None,
            supplier_invoice_number=leg.supplier_invoice_number if leg else None,
            port_of_loading=leg.port_of_loading if leg else None,
            hedge_date=leg.hedge_date if leg else None,
            ai_summary=summary,
            rule_evaluations=rules,
            documents=summaries,
            open_exception_count=open_exceptions,
            confirmation_threshold=confirmation,
            can_decide=_may_decide(user) and task.decision == ApprovalDecision.PENDING.value,
        )
    )


def _integration_message(
    batch_number: str, dispatch: integration_service.DispatchResult | None
) -> str:
    """What actually happened downstream, said plainly and never optimistically.

    A posting that is waiting on a person is reported as waiting on a person. There is no wording
    here, and no branch that produces wording, describing an approval as posted when it is not.
    """
    if dispatch is None or dispatch.attempted == 0:
        return f"Batch {batch_number} is approved and its integration jobs are queued."
    parts: list[str] = []
    if dispatch.succeeded:
        parts.append(f"{dispatch.succeeded} posted automatically")
    if dispatch.awaiting_manual:
        parts.append(f"{dispatch.awaiting_manual} prepared for somebody to complete by hand")
    if dispatch.failed:
        parts.append(f"{dispatch.failed} failed")
    if dispatch.requeued:
        parts.append(f"{dispatch.requeued} queued for another attempt")
    return (
        f"Batch {batch_number} is approved and its three integration jobs have run: "
        + ", ".join(parts)
        + ". It reaches Committed only once all three are genuinely resolved."
    )


@router.post(
    "/{approval_id}/decide",
    response_model=ResponseEnvelope[ApprovalListItem],
    summary="Record the approver's decision",
)
async def decide_approval(
    approval_id: UUID,
    payload: ApprovalDecisionRequest,
    user: Approver,
    session: DbSession,
) -> ResponseEnvelope[ApprovalListItem]:
    """Approve, reject, or send back for changes.

    `decided_by` is the verified token subject and `decided_at` the server clock, always. The
    request body has no field for either, so there is nothing to ignore and nothing to spoof.

    Approving records the decision, raises exactly three integration jobs - one per target system,
    each worked independently - and moves the transaction to `Integration Pending`. It never
    reaches `Committed` here: that state is earned by the three postings genuinely resolving, and
    an approval on its own has posted nothing.

    Rejecting or requesting changes returns the transaction to `Validation Pending` with the
    reason attached, creates no job at all, and is a correctable state the desk that raised it can
    work again - never a dead end.
    """
    task = await approval_service.get_task(session, approval_id)
    transaction = await _load_transaction(session, task)

    configured = await thresholds.resolve_many(
        session,
        thresholds.GovernanceKey.APPROVAL_CONFIRMATION_VALUE,
        thresholds.GovernanceKey.BULK_APPROVAL_VALUE_CEILING,
        thresholds.GovernanceKey.APPROVAL_OVERDUE_HOURS,
    )

    await approval_service.decide(
        session,
        task,
        transaction,
        decision=payload.decision,
        reason=payload.reason,
        user=user,
        confirmed_above_threshold=payload.confirm_above_threshold,
        confirmation_threshold=configured[thresholds.GovernanceKey.APPROVAL_CONFIRMATION_VALUE],
    )

    # The one additive change this endpoint needed for the integration hub. Three jobs, created
    # and attempted in the same transaction as the decision, so an approval can never leave a
    # transaction sitting in `Approved` with nothing behind it.
    dispatch: integration_service.DispatchResult | None = None
    if payload.decision == ApprovalDecision.APPROVED.value:
        await integration_service.create_jobs(session, transaction, actor_id=user.id)
        dispatch = await integration_service.dispatch(session, transaction)
    await session.commit()

    refreshed = await approval_service.get_task(session, approval_id)
    transaction = await _load_transaction(session, refreshed)
    profile = await approval_service.risk_profile(
        session,
        transaction,
        bulk_ceiling=configured[thresholds.GovernanceKey.BULK_APPROVAL_VALUE_CEILING],
    )

    message = (
        _integration_message(transaction.batch_number, dispatch)
        if payload.decision == ApprovalDecision.APPROVED.value
        else f"Batch {transaction.batch_number} has gone back to the desk that raised it, "
        "editable, with your reason on it."
    )
    return ResponseEnvelope[ApprovalListItem](
        data=_list_item(
            refreshed,
            transaction,
            profile,
            overdue_hours=float(configured[thresholds.GovernanceKey.APPROVAL_OVERDUE_HOURS]),
            confirmation_threshold=configured[thresholds.GovernanceKey.APPROVAL_CONFIRMATION_VALUE],
        ),
        message=message,
    )


@router.post(
    "/bulk-decide",
    response_model=ResponseEnvelope[BulkApprovalResult],
    summary="Approve several lowest-risk transactions, each one individually",
)
async def bulk_decide(
    payload: BulkApprovalRequest,
    user: Approver,
    session: DbSession,
) -> ResponseEnvelope[BulkApprovalResult]:
    """N independent approvals that happened to be asked for together.

    Never one blanket act. Each transaction is re-fetched, re-checked for eligibility against the
    server's own risk profile, decided on its own and audited on its own. A row the frontend
    should have filtered out is refused here, individually, and the rest still go through - the
    client's filter is a convenience, never the authority.
    """
    ceiling = await thresholds.resolve(
        session, thresholds.GovernanceKey.BULK_APPROVAL_VALUE_CEILING
    )
    confirmation = await thresholds.resolve(
        session, thresholds.GovernanceKey.APPROVAL_CONFIRMATION_VALUE
    )

    approved: list[BulkApprovalOutcome] = []
    refused: list[BulkApprovalOutcome] = []

    for approval_id in dict.fromkeys(payload.approval_ids):
        task = await session.get(ApprovalTask, approval_id)
        if task is None:
            refused.append(
                BulkApprovalOutcome(
                    approval_id=approval_id,
                    approved=False,
                    message="This approval no longer exists.",
                )
            )
            continue

        transaction = await session.scalar(
            select(TradeTransaction)
            .where(TradeTransaction.id == task.transaction_id)
            .options(selectinload(TradeTransaction.purchase_leg))
        )
        if transaction is None:
            refused.append(
                BulkApprovalOutcome(
                    approval_id=approval_id,
                    approved=False,
                    message="The transaction behind this approval no longer exists.",
                )
            )
            continue

        profile = await approval_service.risk_profile(session, transaction, bulk_ceiling=ceiling)
        if not profile.bulk_eligible:
            refused.append(
                BulkApprovalOutcome(
                    approval_id=approval_id,
                    transaction_id=transaction.id,
                    batch_number=transaction.batch_number,
                    approved=False,
                    message=(
                        "Outside the lowest risk tier, so it has to be decided on its own: "
                        + " ".join(profile.reasons)
                    ),
                )
            )
            continue

        try:
            await approval_service.decide(
                session,
                task,
                transaction,
                decision=ApprovalDecision.APPROVED.value,
                reason=None,
                user=user,
                # A bulk-eligible transaction is by definition under the bulk ceiling, which sits
                # at or below the confirmation threshold, so nothing here can reach the
                # high-value path. Passing False keeps that a guarantee rather than a habit.
                confirmed_above_threshold=False,
                confirmation_threshold=confirmation,
                bulk=True,
            )
        except ConflictError as exc:
            refused.append(
                BulkApprovalOutcome(
                    approval_id=approval_id,
                    transaction_id=transaction.id,
                    batch_number=transaction.batch_number,
                    approved=False,
                    message=exc.message,
                )
            )
            continue

        # Each transaction gets its own three jobs, raised and attempted individually, exactly
        # as a single decision does. A bulk action is N approvals that happened to be asked for
        # together, and that has to remain true of everything downstream of them too.
        await integration_service.create_jobs(session, transaction, actor_id=user.id)
        await integration_service.dispatch(session, transaction)

        approved.append(
            BulkApprovalOutcome(
                approval_id=approval_id,
                transaction_id=transaction.id,
                batch_number=transaction.batch_number,
                approved=True,
                message=f"Approved. {transaction.batch_number} is now "
                f"{transaction.status.replace('_', ' ')}.",
            )
        )

    await session.commit()

    return ResponseEnvelope[BulkApprovalResult](
        data=BulkApprovalResult(
            approved=approved,
            rejected=refused,
            approved_count=len(approved),
            skipped_count=len(refused),
        ),
        message=(
            f"{len(approved)} transaction{'' if len(approved) == 1 else 's'} approved "
            f"individually; {len(refused)} left for a decision of its own."
        ),
    )

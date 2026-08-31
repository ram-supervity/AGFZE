"""The transaction list, the purchase workspace, and the four actions that move a transaction.

Read access is open to every signed-in account and still passes through the visibility filter, so
the constraint lives in the query rather than in whether a button was rendered. Every write is
role-gated server-side, and `submit` still stops at `Approval Pending` - it raises the approval
task and goes no further. Moving a transaction past that state is the approver's act, recorded
through `/approvals`, and there is no path here that can do it on their behalf.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.dependencies import CurrentUser, DbSession, require_roles
from app.core.errors import AuthorizationError, ConflictError, NotFoundError
from app.core.logging import get_logger
from app.core.roles import PlatformRole
from app.db.base import utcnow
from app.models.audit import AuditEvent
from app.models.enums import (
    BUSINESS_STREAMS,
    PURCHASE_GENERATED_DOCUMENT_TYPES,
    SALES_GENERATED_DOCUMENT_TYPES,
    TRANSACTION_STATUSES,
    BusinessStream,
    DocumentType,
    MatchMethod,
    RuleSeverity,
    TransactionStatus,
)
from app.models.identity import User
from app.models.intake import Document, Request
from app.models.transactions import CommodityCode, RuleEvaluation, TradeTransaction
from app.schemas.common import ResponseEnvelope
from app.schemas.intake import DocumentSummary, Page
from app.schemas.integration import job_read as integration_job_read
from app.schemas.logistics import ContainerRead, LinkedShipmentRead
from app.schemas.transaction import (
    CommodityCodeRead,
    ContractCoverageRead,
    DraftGenerationAccepted,
    DraftGenerationRequest,
    FaFieldSchemaRead,
    FaLegRead,
    FaTransactionCreate,
    GeneratedDraftRead,
    LinkedPurchaseContext,
    PurchaseLegRead,
    PurchaseTransactionCreate,
    RuleEvaluationRead,
    SalesAttachmentResult,
    SalesLegCreate,
    SalesLegRead,
    StatusEvent,
    SubmissionResult,
    ToleranceAcknowledgement,
    TransactionDetail,
    TransactionFieldRead,
    TransactionFieldUpdate,
    TransactionGraph,
    TransactionList,
    TransactionListItem,
)
from app.services import (
    counterparty_codes,
    draft_service,
    extraction_service,
    neo4j_service,
    request_service,
    sales_service,
    transaction_fields,
    transaction_service,
)
from app.services.audit_service import ActorType, record_audit_event
from app.services.governance import approval_service, thresholds
from app.services.integration import integration_service
from app.services.logistics import shipment_service
from app.services.rules import engine as rule_engine
from app.services.rules.catalog import RULE_BY_ID
from app.services.rules.sales_evaluators import draft_generation_permitted
from app.services.storage import get_storage_service

logger = get_logger(__name__)

router = APIRouter(prefix="/transactions", tags=["transactions"])

# The purchase desk owns its own deals; the approver signs them off in Step 4 rather than
# preparing them, and the auditor observes. Reads below are open to every signed-in account.
PurchaseUser = Annotated[
    User,
    Depends(require_roles(PlatformRole.PURCHASE_USER.value, PlatformRole.ADMIN.value)),
]

# The selling desk owns its own deals, exactly as the buying desk owns theirs.
SalesUser = Annotated[
    User,
    Depends(require_roles(PlatformRole.SALES_USER.value, PlatformRole.ADMIN.value)),
]

# And so does the FA desk, on AGFZE's second business line. The same sentence three times, which
# is what a stream-agnostic platform is supposed to look like.
FaUser = Annotated[
    User,
    Depends(require_roles(PlatformRole.FA_USER.value, PlatformRole.ADMIN.value)),
]

# The actions that belong to whichever desk is preparing the transaction. Which *fields* each of
# them may then write is narrowed per leg inside `apply_corrections`, so holding the role is not
# the same as being allowed to restate the other desk's terms.
PreparingUser = Annotated[
    User,
    Depends(
        require_roles(
            PlatformRole.PURCHASE_USER.value,
            PlatformRole.SALES_USER.value,
            PlatformRole.FA_USER.value,
            PlatformRole.ADMIN.value,
        )
    ),
]

# Audit events that belong on a transaction's own timeline.
TIMELINE_EVENTS = (
    transaction_service.AuditEvent.TRANSACTION_CREATED,
    transaction_service.AuditEvent.TRANSACTION_MATCHED,
    transaction_service.AuditEvent.TRANSACTION_DOCUMENT_LINKED,
    transaction_service.AuditEvent.TRANSACTION_SUPERSEDED,
    transaction_service.AuditEvent.TRANSACTION_FIELD_CORRECTED,
    transaction_service.AuditEvent.TRANSACTION_TOLERANCE_ACKNOWLEDGED,
    transaction_service.AuditEvent.TRANSACTION_SUBMITTED,
    transaction_service.AuditEvent.TRANSACTION_SUBMISSION_BLOCKED,
    transaction_service.AuditEvent.TRANSACTION_COMMODITY_UNRESOLVED,
    transaction_service.AuditEvent.CONTAINER_RECORDED,
    transaction_service.AuditEvent.FA_LEG_ATTACHED,
    sales_service.AuditEvent.SALES_LEG_ATTACHED,
    sales_service.AuditEvent.SALES_COMMODITY_MISMATCH,
    sales_service.AuditEvent.PRICE_FIXATION_RECORDED,
    sales_service.AuditEvent.CONTRACT_COVERAGE_REEVALUATED,
    sales_service.AuditEvent.DRAFT_GENERATION_REQUESTED,
    sales_service.AuditEvent.DRAFT_GENERATED,
    sales_service.AuditEvent.DRAFT_GENERATION_FAILED,
)

EVENT_SUMMARIES = {
    transaction_service.AuditEvent.TRANSACTION_CREATED: "Transaction opened",
    transaction_service.AuditEvent.TRANSACTION_MATCHED: "Ambiguous match resolved",
    transaction_service.AuditEvent.TRANSACTION_DOCUMENT_LINKED: "Document linked",
    transaction_service.AuditEvent.TRANSACTION_SUPERSEDED: (
        "Final invoice superseded the provisional figures"
    ),
    transaction_service.AuditEvent.TRANSACTION_FIELD_CORRECTED: "Fields corrected",
    transaction_service.AuditEvent.TRANSACTION_TOLERANCE_ACKNOWLEDGED: (
        "Tolerance breach acknowledged"
    ),
    transaction_service.AuditEvent.TRANSACTION_SUBMITTED: "Submitted for approval",
    transaction_service.AuditEvent.TRANSACTION_SUBMISSION_BLOCKED: (
        "Submission blocked by a failing rule"
    ),
    transaction_service.AuditEvent.TRANSACTION_COMMODITY_UNRESOLVED: "Commodity grade needs review",
    transaction_service.AuditEvent.CONTAINER_RECORDED: "Container recorded against this batch",
    transaction_service.AuditEvent.FA_LEG_ATTACHED: "FA leg attached",
    sales_service.AuditEvent.SALES_LEG_ATTACHED: "Sales leg attached",
    sales_service.AuditEvent.SALES_COMMODITY_MISMATCH: (
        "Sales document's grade disagrees with the batch"
    ),
    sales_service.AuditEvent.PRICE_FIXATION_RECORDED: "Customer price fixation recorded",
    sales_service.AuditEvent.CONTRACT_COVERAGE_REEVALUATED: (
        "Sales contract coverage re-evaluated after a change on another shipment"
    ),
    sales_service.AuditEvent.DRAFT_GENERATION_REQUESTED: "Draft generation requested",
    sales_service.AuditEvent.DRAFT_GENERATED: "Draft document generated",
    sales_service.AuditEvent.DRAFT_GENERATION_FAILED: (
        "Draft generation failed; no document was produced"
    ),
}


def _age_days(created_at: datetime) -> int:
    reference = created_at if created_at.tzinfo else created_at.replace(tzinfo=timezone.utc)
    return max(0, (datetime.now(timezone.utc) - reference).days)


def _counterparty(transaction: TradeTransaction) -> str | None:
    """Whoever the other side of this deal is, from whichever leg the transaction carries.

    Ordered rather than branched on stream: the buying side names the counterparty where there is
    one, a sales-only transaction names the customer, and an FA transaction names its own. A row
    with a counterparty is never rendered as though it had none.
    """
    leg = transaction.purchase_leg
    sales = transaction.sales_leg
    fa = transaction.fa_leg
    return (
        (leg.supplier_name if leg else None)
        or (sales.customer_name if sales else None)
        or (fa.counterparty_name if fa else None)
    )


def _counterparty_code(transaction: TradeTransaction) -> str | None:
    """The desk's own short form of the counterparty's name, derived on read.

    Which convention applies depends on which side of the deal the name came from, and the order
    here is the same one `_counterparty` uses, so the code always abbreviates the name that is
    actually being shown beside it rather than some other leg's.
    """
    leg = transaction.purchase_leg
    if leg is not None and leg.supplier_name:
        return counterparty_codes.supplier_code(leg.supplier_name)
    sales = transaction.sales_leg
    if sales is not None and sales.customer_name:
        return counterparty_codes.customer_code(sales.customer_name)
    fa = transaction.fa_leg
    if fa is not None and fa.counterparty_name:
        # An FA counterparty is neither a supplier nor a customer. The customer convention is the
        # shorter and more neutral of the two, and an FA transaction names one party rather than
        # two, so there is no second name for it to be confused with.
        return counterparty_codes.customer_code(fa.counterparty_name)
    return None


def _contract_reference(transaction: TradeTransaction) -> str | None:
    leg = transaction.purchase_leg
    sales = transaction.sales_leg
    fa = transaction.fa_leg
    return (
        (leg.contract_number if leg else None)
        or (sales.sales_contract_no if sales else None)
        or (fa.fa_contract_reference if fa else None)
    )


def _list_item(
    transaction: TradeTransaction,
    *,
    document_count: int = 0,
    failing: int = 0,
    shipments: list | None = None,
    stale_hours: float = 48.0,
) -> TransactionListItem:
    item = TransactionListItem.model_validate(transaction)
    leg = transaction.purchase_leg
    item.counterparty = _counterparty(transaction)
    item.counterparty_code = _counterparty_code(transaction)
    item.contract_number = _contract_reference(transaction)
    item.invoice_status = leg.invoice_status if leg else None
    item.value = leg.amount if leg else None
    item.commodity_name = transaction.commodity.display_name if transaction.commodity else None
    item.age_days = _age_days(transaction.created_at)
    item.document_count = document_count
    item.failing_rule_count = failing
    item.has_purchase_leg = leg is not None
    item.has_sales_leg = transaction.sales_leg is not None
    item.has_fa_leg = transaction.fa_leg is not None
    item.is_b2b = bool(leg.is_b2b) if leg else False
    item.b2b_partner_name = leg.b2b_partner_name if leg else None
    # Real data from Step 6. Null still means "no shipment record exists", which is a different
    # and more honest thing than reporting a transaction nobody has shipped as on schedule.
    rows = shipments or []
    item.shipment_count = len(rows)
    item.shipment_status = shipment_service.summarise_status(rows)
    item.shipment_stale = any(
        shipment_service.hours_since_check(row) >= stale_hours for row in rows
    )
    return item


async def _load(session: DbSession, transaction_id: UUID, user: User) -> TradeTransaction:
    statement = transaction_service.apply_visibility(
        select(TradeTransaction).where(TradeTransaction.id == transaction_id), user
    ).options(
        selectinload(TradeTransaction.purchase_leg),
        selectinload(TradeTransaction.sales_leg),
        selectinload(TradeTransaction.fa_leg),
        selectinload(TradeTransaction.commodity),
        selectinload(TradeTransaction.containers),
        selectinload(TradeTransaction.shipments),
    )
    transaction = await session.scalar(statement)
    if transaction is None:
        # A transaction outside the caller's scope answers exactly like one that does not exist,
        # so the endpoint cannot be used to probe which batch numbers are real.
        raise NotFoundError("Transaction not found.")
    return transaction


@router.get(
    "/commodity-codes",
    response_model=ResponseEnvelope[list[CommodityCodeRead]],
    summary="The trade grades a transaction may carry",
)
async def list_commodity_codes(
    user: CurrentUser, session: DbSession
) -> ResponseEnvelope[list[CommodityCodeRead]]:
    rows = (
        await session.scalars(
            select(CommodityCode)
            .where(CommodityCode.is_active.is_(True))
            .order_by(CommodityCode.code)
        )
    ).all()
    return ResponseEnvelope[list[CommodityCodeRead]](
        data=[CommodityCodeRead.model_validate(row) for row in rows]
    )


@router.get(
    "/fa/schema",
    response_model=ResponseEnvelope[list[FaFieldSchemaRead]],
    summary="The configured FA fields that have no named column of their own",
)
async def read_fa_schema(
    user: CurrentUser, session: DbSession
) -> ResponseEnvelope[list[FaFieldSchemaRead]]:
    """The same list the workspace's Additional FA Fields panel renders from.

    Exposed on its own because the registration form needs it before any transaction exists to
    hang it off. Both screens read this one source, so neither can drift from the configuration
    or from the other.
    """
    return ResponseEnvelope[list[FaFieldSchemaRead]](data=await _fa_schema(session))


@router.get(
    "",
    response_model=ResponseEnvelope[TransactionList],
    summary="Paginated, filterable transaction list",
)
async def list_transactions(
    user: CurrentUser,
    session: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    stream: str | None = Query(None),
    status: str | None = Query(None),
    commodity_code: str | None = Query(None),
    search: str | None = Query(None, max_length=200),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    deal_type: str | None = Query(None, pattern="^(b2b|standard)$"),
    sort_by: str = Query("created_at"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
) -> ResponseEnvelope[TransactionList]:
    if stream and stream not in BUSINESS_STREAMS:
        stream = None
    if status and status not in TRANSACTION_STATUSES:
        status = None

    statement = transaction_service.apply_visibility(
        transaction_service.list_query(
            stream=stream,
            status=status,
            commodity_code=commodity_code,
            date_from=date_from,
            date_to=date_to,
            search=search,
            deal_type=deal_type,
        ),
        user,
    )
    total = await request_service.count_query(session, statement)

    rows = (
        await session.scalars(
            transaction_service.apply_sort(statement, sort_by, sort_dir)
            .options(
                selectinload(TradeTransaction.purchase_leg),
                selectinload(TradeTransaction.sales_leg),
                selectinload(TradeTransaction.fa_leg),
                selectinload(TradeTransaction.commodity),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()

    ids = [row.id for row in rows] or [None]
    document_counts = dict(
        (
            await session.execute(
                select(Document.transaction_id, func.count(Document.id))
                .where(Document.transaction_id.in_(ids))
                .group_by(Document.transaction_id)
            )
        ).all()
    )

    failing: dict[UUID, int] = {}
    for row in rows:
        current = await rule_engine.current_results(session, row.id)
        failing[row.id] = sum(1 for evaluation in current if not evaluation.passed)

    # One query for every row's shipments rather than one per row, so filling the column that was
    # an honest placeholder until now costs the list nothing.
    shipments = await shipment_service.shipments_for_transactions(session, [row.id for row in rows])
    stale_hours = float(
        await thresholds.resolve(session, thresholds.GovernanceKey.SHIPMENT_STALE_HOURS)
    )

    return ResponseEnvelope[TransactionList](
        data=TransactionList(
            items=[
                _list_item(
                    row,
                    document_count=int(document_counts.get(row.id, 0)),
                    failing=failing.get(row.id, 0),
                    shipments=shipments.get(row.id, []),
                    stale_hours=stale_hours,
                )
                for row in rows
            ],
            page=Page(
                page=page,
                page_size=page_size,
                total=total,
                total_pages=max(1, -(-total // page_size)),
            ),
        )
    )


async def _documents(session: DbSession, transaction_id: UUID) -> list[Document]:
    return list(
        (
            await session.scalars(
                select(Document)
                .where(Document.transaction_id == transaction_id)
                .options(selectinload(Document.fields))
                .order_by(Document.created_at)
            )
        ).all()
    )


async def _history(session: DbSession, transaction: TradeTransaction) -> list[StatusEvent]:
    rows = (
        await session.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.entity_type == "trade_transaction",
                AuditEvent.entity_id == str(transaction.id),
                AuditEvent.event_type.in_(TIMELINE_EVENTS),
            )
            .options(selectinload(AuditEvent.actor))
            .order_by(AuditEvent.occurred_at)
        )
    ).all()
    return [
        StatusEvent(
            occurred_at=row.occurred_at,
            event_type=row.event_type,
            summary=EVENT_SUMMARIES.get(row.event_type, row.event_type.replace(".", " ")),
            actor_name=row.actor.display_name if row.actor else None,
            metadata=row.event_metadata or {},
        )
        for row in rows
    ]


async def _fields(
    session: DbSession,
    transaction: TradeTransaction,
    documents: list[Document],
    editable: bool,
    user_roles: list[str],
) -> list[TransactionFieldRead]:
    # Includes the FA extras resolved from the configured schema, so a field the business adds
    # tomorrow is editable, audited and confidence-coloured with no change here.
    available = await transaction_fields.editable_fields(session, transaction)
    confidences = await transaction_fields.provenance(
        session, transaction, documents, fields=available
    )
    writable = transaction_fields.owners_for(user_roles)
    rendered: list[TransactionFieldRead] = []
    for field in available:
        entry = transaction_fields.override_entry(transaction, field)
        confidence = confidences.get(field.name)
        rendered.append(
            TransactionFieldRead(
                name=field.name,
                label=field.label,
                owner=field.owner,
                type=field.type,
                value=transaction_fields.read_value(transaction, field),
                section=field.section,
                source_confidence=confidence,
                reason_required=transaction_fields.reason_required(
                    confidence, was_extracted=field.source_field is not None
                ),
                is_overridden=bool(entry),
                original_ai_value=entry.get("original_ai_value"),
                original_confidence=entry.get("original_confidence"),
                override_reason=entry.get("reason"),
                overridden_by_name=entry.get("overridden_by_name"),
                overridden_at=entry.get("overridden_at"),
                options=list(field.options),
                # Rendered read-only where the caller's roles do not carry this leg. The same
                # rule is applied again server-side on the correction itself.
                editable=editable and field.owner in writable,
            )
        )
    return rendered


def _rule_read(row: RuleEvaluation) -> RuleEvaluationRead:
    read = RuleEvaluationRead.model_validate(row)
    definition = RULE_BY_ID.get(row.rule_id)
    read.title = definition.title if definition else None
    read.statement = definition.statement if definition else None
    read.acknowledged_by_name = row.acknowledged_by.display_name if row.acknowledged_by else None
    return read


def blocking(evaluations: list[RuleEvaluation]) -> list[str]:
    return [
        f"{row.rule_id}"
        + (f" ({row.check_key.replace('_', ' ')})" if row.check_key else "")
        + f": {row.message}"
        for row in evaluations
        if not row.passed
    ]


async def _detail(
    session: DbSession, transaction: TradeTransaction, user: User
) -> TransactionDetail:
    documents = await _documents(session, transaction.id)
    evaluations = await rule_engine.current_results(session, transaction.id)
    editable = (
        _may_write(user, transaction)
        and transaction.status not in transaction_fields.LOCKED_STATUSES
    )

    detail = TransactionDetail.model_validate(transaction)
    leg = transaction.purchase_leg
    sales = transaction.sales_leg
    detail.counterparty = _counterparty(transaction)
    detail.contract_number = _contract_reference(transaction)
    detail.invoice_status = leg.invoice_status if leg else None
    detail.value = leg.amount if leg else None
    detail.commodity_name = transaction.commodity.display_name if transaction.commodity else None
    detail.age_days = _age_days(transaction.created_at)
    detail.document_count = len(documents)
    detail.failing_rule_count = sum(1 for row in evaluations if not row.passed)
    detail.has_purchase_leg = leg is not None
    detail.has_sales_leg = sales is not None
    detail.has_fa_leg = transaction.fa_leg is not None
    detail.purchase_leg = PurchaseLegRead.model_validate(leg) if leg else None
    # Populates with no change to the response shape: the field was declared in Step 3 and has
    # simply been empty until now.
    detail.sales_leg = SalesLegRead.model_validate(sales) if sales else None
    detail.fa_leg = FaLegRead.model_validate(transaction.fa_leg) if transaction.fa_leg else None
    detail.confidence_threshold = settings.CONFIDENCE_THRESHOLD_DEFAULT
    detail.can_edit = editable
    detail.blocking_rules = blocking(evaluations)
    detail.can_submit = editable and not detail.blocking_rules and bool(evaluations)

    request = (
        await session.get(Request, transaction.request_id)
        if transaction.request_id is not None
        else None
    )
    detail.request_code = request.request_code if request else None

    storage = get_storage_service()
    summaries: list[DocumentSummary] = []
    for document in documents:
        summary = DocumentSummary.model_validate(document)
        refs = document.page_image_refs or []
        summary.thumbnail_url = await storage.get_signed_url(refs[0]) if refs else None
        summaries.append(summary)
    detail.documents = summaries

    # Where this transaction stands with the three downstream systems. New to all three
    # workspaces in Step 7, and the second retrofit to them after Step 6's shipment status - so
    # it is built as a genuine extension: it says nothing at all before an approval has raised
    # any job, which is where most transactions on this screen are.
    detail.integration_jobs = [
        integration_job_read(row)
        for row in await integration_service.jobs_for(session, transaction.id)
    ]
    detail.can_manage_integrations = PlatformRole.ADMIN.value in (user.roles or ())

    detail.rule_evaluations = [_rule_read(row) for row in evaluations]
    detail.fields = await _fields(session, transaction, documents, editable, list(user.roles or ()))
    detail.history = await _history(session, transaction)

    # The shipment status the workspaces show, and the same figure the list shows. Both
    # workspaces read this: it is a genuinely new addition to two already-shipped screens, not a
    # placeholder finally being filled.
    shipments = list(transaction.shipments or [])
    stale_hours = float(
        await thresholds.resolve(session, thresholds.GovernanceKey.SHIPMENT_STALE_HOURS)
    )
    detail.shipment_count = len(shipments)
    detail.shipment_status = shipment_service.summarise_status(shipments)
    detail.shipment_stale = any(
        shipment_service.hours_since_check(row) >= stale_hours for row in shipments
    )
    detail.linked_shipments = [_linked_shipment(row, stale_hours=stale_hours) for row in shipments]
    detail.containers = [
        ContainerRead.model_validate(row) for row in (transaction.containers or [])
    ]

    if transaction.fa_leg is not None:
        detail.fa_extra_fields = [
            row for row in detail.fields if row.owner == transaction_fields.FA_EXTRA
        ]
        detail.fa_field_schema = await _fa_schema(session)

    all_drafts = await _drafts(session, transaction)
    roles = set(user.roles or ())
    is_admin = PlatformRole.ADMIN.value in roles
    is_sales = PlatformRole.SALES_USER.value in roles
    is_purchase = PlatformRole.PURCHASE_USER.value in roles

    if is_admin or (is_sales and is_purchase):
        detail.generated_drafts = all_drafts
    elif is_sales:
        detail.generated_drafts = [
            d for d in all_drafts if d.document_type in SALES_GENERATED_DOCUMENT_TYPES
        ]
    elif is_purchase:
        detail.generated_drafts = [
            d for d in all_drafts if d.document_type in PURCHASE_GENERATED_DOCUMENT_TYPES
        ]
    else:
        detail.generated_drafts = []

    if (is_admin or is_purchase) and transaction.purchase_leg is not None and not is_sales:
        permitted, blocker = draft_service.purchase_draft_generation_permitted(transaction)
        detail.can_generate_draft = editable and permitted
        detail.draft_blocker = blocker
    elif (is_admin or is_sales) and sales is not None:
        detail.linked_purchase = await _linked_purchase(session, transaction)
        detail.contract_coverage = await _coverage(session, transaction)
        permitted, blocker = draft_generation_permitted(evaluations)
        detail.can_generate_draft = editable and permitted
        detail.draft_blocker = blocker
    elif (is_admin or is_purchase) and transaction.purchase_leg is not None:
        permitted, blocker = draft_service.purchase_draft_generation_permitted(transaction)
        detail.can_generate_draft = editable and permitted
        detail.draft_blocker = blocker
    else:
        detail.can_generate_draft = False
        detail.draft_blocker = "You do not have permission to generate draft documents for this transaction."

    names = dict(
        (
            await session.execute(
                select(User.id, User.display_name).where(
                    User.id.in_(
                        [
                            identifier
                            for identifier in (
                                transaction.created_by_id,
                                transaction.submitted_by_id,
                            )
                            if identifier is not None
                        ]
                        or [None]
                    )
                )
            )
        ).all()
    )
    detail.created_by_name = names.get(transaction.created_by_id)
    detail.submitted_by_name = names.get(transaction.submitted_by_id)
    return detail


def _linked_shipment(shipment, *, stale_hours: float) -> LinkedShipmentRead:
    """One shipment as a transaction workspace shows it.

    The same fields whether a carrier or a person put them there, because the workspace has no
    business knowing which - and `original_bl_received` beside them, because it is the field
    BR-07 blocks submission on and the preparing desk needs to see why they are blocked.
    """
    hours = shipment_service.hours_since_check(shipment)
    bill = shipment_service.final_bill(shipment)
    return LinkedShipmentRead(
        id=shipment.id,
        container_number=(
            shipment.container.container_number if shipment.container is not None else None
        ),
        bl_number=shipment.bl_number,
        carrier=shipment.carrier,
        vessel=shipment.vessel,
        port_of_loading=shipment.port_of_loading,
        port_of_discharge=shipment.port_of_discharge,
        etd=shipment.etd,
        eta=shipment.eta,
        current_milestone=shipment.current_milestone,
        status=shipment.status,
        last_checked_at=shipment.last_checked_at,
        last_checked_source=shipment.last_checked_source,
        hours_since_check=round(hours, 2),
        is_stale=hours >= stale_hours,
        review_flagged=bool(shipment.review_flagged),
        original_bl_received=bill is not None,
    )


async def _fa_schema(session: DbSession) -> list[FaFieldSchemaRead]:
    """The configured FA field schema, sent to the workspace so its panel can render itself.

    The panel hardcodes no field name and cannot: it is handed this list and draws a control per
    entry from the entry's own type. Adding a field to `document_type_schemas` therefore adds it
    to the screen with no frontend change, which is the concrete proof the platform's flexible-
    field promise actually holds.
    """
    try:
        schema = await extraction_service.select_schema(
            session, document_type=DocumentType.FA_DOCUMENT.value, territory=None
        )
    except extraction_service.SchemaNotConfiguredError:
        return []
    mapped = set(transaction_service.FA_LEG_COLUMNS) | set(
        transaction_service.FA_TRANSACTION_COLUMNS
    )
    return [
        FaFieldSchemaRead(
            name=definition.name,
            label=definition.label,
            type=definition.type,
            required=definition.required,
            section=definition.section,
            description=definition.description,
        )
        for definition in schema.fields
        if definition.name not in mapped
    ]


def _may_write(user: User, transaction: TradeTransaction | None = None) -> bool:
    """Whether this account may prepare this transaction at all.

    Admin carries every leg. A desk user carries the leg their desk owns, and a transaction with
    no leg of theirs on it is somebody else's work to prepare - which they still read, because
    read access was never keyed to the leg.
    """
    roles = set(user.roles or ())
    if PlatformRole.ADMIN.value in roles:
        return True
    # Which desk carries which leg, as data. The third stream needed one entry here and no branch.
    desks = (
        (PlatformRole.PURCHASE_USER.value, "purchase_leg"),
        (PlatformRole.SALES_USER.value, "sales_leg"),
        (PlatformRole.FA_USER.value, "fa_leg"),
    )
    if transaction is None:
        return bool(roles & {role for role, _ in desks})
    return any(
        role in roles and getattr(transaction, attribute, None) is not None
        for role, attribute in desks
    )


async def _linked_purchase(
    session: DbSession, transaction: TradeTransaction
) -> LinkedPurchaseContext:
    """The buying side's context, and the one comparison the sales workspace actually makes.

    The comparison is delegated to `check_commodity_consistency` rather than repeated here, and
    that matters more than it looks. What the sales leg stores is the grade the document actually
    stated, verbatim - "Copper Millberry 99.9%", or whatever wording the destination's customs
    regime needs. Comparing that string against the batch's `CU` would report a mismatch on
    nearly every export the desk makes, which is exactly the false positive this step forbids.
    The shared function resolves the stated grade to a code first, and compares codes.
    """
    leg = transaction.purchase_leg
    sales = transaction.sales_leg
    consistency = await sales_service.check_commodity_consistency(
        session, transaction, getattr(sales, "extracted_commodity_value", None)
    )

    return LinkedPurchaseContext(
        present=leg is not None,
        supplier_name=leg.supplier_name if leg else None,
        contract_number=leg.contract_number if leg else None,
        supplier_invoice_number=leg.supplier_invoice_number if leg else None,
        invoice_status=leg.invoice_status if leg else None,
        port_of_loading=leg.port_of_loading if leg else None,
        amount=leg.amount if leg else None,
        rate=leg.rate if leg else None,
        commodity_code=transaction.commodity_code,
        sales_document_commodity_value=consistency.document_value,
        commodity_code_mismatch=consistency.mismatch,
        message=(
            consistency.message
            if consistency.mismatch or leg is not None
            else "No purchase leg is attached to this transaction."
        ),
    )


async def _coverage(
    session: DbSession, transaction: TradeTransaction
) -> ContractCoverageRead | None:
    """The quantity meter: everything invoiced against this sales contract, summed."""
    coverage = await sales_service.current_coverage(session, transaction)
    if coverage is None:
        return None
    messages = {
        "partial": (
            "Part-shipped, with further shipments expected against this contract. Nothing is "
            "outstanding."
        ),
        "complete": "Fully shipped: the invoiced total is exactly the contracted quantity.",
        "exceeded": (
            "More has been invoiced against this contract, across every shipment on it, than the "
            "contract covers."
        ),
        "unknown": (
            "No contracted total is recorded for this sales contract, so nothing can be measured "
            "against it."
        ),
    }
    return ContractCoverageRead(
        sales_contract_no=coverage.contract_no,
        contracted_quantity_mt=coverage.contracted_quantity,
        invoiced_quantity_mt=coverage.invoiced_quantity,
        remaining_quantity_mt=coverage.remaining,
        shipment_count=coverage.shipment_count,
        state=coverage.state,
        ratio=coverage.ratio,
        message=messages[coverage.state],
    )


async def _drafts(session: DbSession, transaction: TradeTransaction) -> list[GeneratedDraftRead]:
    """Every draft generated for this transaction, oldest first and versioned per type.

    Nothing is overwritten by a regeneration, so this is the complete record of what the platform
    produced and when. The download is the ordinary document signed URL, subject to exactly the
    same access control as any other document - a generated draft is not exempt from it because
    the system wrote it.
    """
    rows = await draft_service.drafts_for(session, transaction.id)
    if not rows:
        return []

    storage = get_storage_service()
    requesters = [row.uploaded_by_id for row in rows if row.uploaded_by_id is not None]
    names = (
        dict(
            (
                await session.execute(
                    select(User.id, User.display_name).where(User.id.in_(requesters))
                )
            ).all()
        )
        if requesters
        else {}
    )
    counters: dict[str, int] = {}
    drafts: list[GeneratedDraftRead] = []
    for row in rows:
        kind = row.document_type or "draft"
        counters[kind] = counters.get(kind, 0) + 1
        read = GeneratedDraftRead.model_validate(row)
        read.version = counters[kind]
        read.generated_by_name = names.get(row.uploaded_by_id)
        read.download_url = await storage.get_signed_url(row.storage_ref)
        drafts.append(read)
    return drafts


@router.get(
    "/{transaction_id}",
    response_model=ResponseEnvelope[TransactionDetail],
    summary="Full transaction detail with its legs, rules, documents and history",
)
async def read_transaction(
    transaction_id: UUID, user: CurrentUser, session: DbSession
) -> ResponseEnvelope[TransactionDetail]:
    transaction = await _load(session, transaction_id, user)
    return ResponseEnvelope[TransactionDetail](data=await _detail(session, transaction, user))


@router.post(
    "",
    response_model=ResponseEnvelope[TransactionDetail],
    status_code=201,
    summary="Register a purchase transaction by hand",
)
async def create_transaction(
    payload: PurchaseTransactionCreate,
    user: PurchaseUser,
    session: DbSession,
) -> ResponseEnvelope[TransactionDetail]:
    values = {
        "supplier_name": payload.supplier_name,
        "contract_number": payload.contract_number,
        "invoice_number": payload.supplier_invoice_number,
        "invoice_status": payload.invoice_status,
        "commodity_code": payload.commodity_code,
        "quantity": str(payload.quantity_mt) if payload.quantity_mt is not None else None,
        "currency": payload.currency,
        "rate": str(payload.rate) if payload.rate is not None else None,
        "amount": str(payload.amount) if payload.amount is not None else None,
        "advance_payment_percent": (
            str(payload.advance_payment_percent)
            if payload.advance_payment_percent is not None
            else None
        ),
        "hedge_date": payload.hedge_date.isoformat() if payload.hedge_date else None,
        "hedge_low_price": (
            str(payload.hedge_low_price) if payload.hedge_low_price is not None else None
        ),
        "hedge_high_price": (
            str(payload.hedge_high_price) if payload.hedge_high_price is not None else None
        ),
        "port_of_loading": payload.port_of_loading,
    }

    transaction = await transaction_service.create_manual_transaction(
        session,
        user=user,
        stream=payload.stream,
        batch_number=payload.batch_number,
        values=values,
    )
    # The form's own price basis wins over what the values imply: the person registering the deal
    # knows whether it is fixed or LME-linked, and nothing was extracted to disagree with them.
    transaction.price_basis = payload.price_basis
    transaction.lme_percentage = payload.lme_percentage
    await session.flush()

    await record_audit_event(
        session,
        event_type=transaction_service.AuditEvent.TRANSACTION_CREATED,
        entity_type="trade_transaction",
        entity_id=transaction.id,
        actor_id=user.id,
        actor_type=ActorType.USER,
        metadata={
            "batch_number": transaction.batch_number,
            "origin": "manual_registration",
            "match_method": MatchMethod.MANUAL.value,
            "supplier_name": payload.supplier_name,
            "batch_number_supplied": bool(payload.batch_number),
        },
    )
    await rule_engine.run_validation(session, transaction)
    await session.commit()

    refreshed = await _load(session, transaction.id, user)
    return ResponseEnvelope[TransactionDetail](
        data=await _detail(session, refreshed, user),
        message=f"Batch {transaction.batch_number} registered.",
    )


@router.post(
    "/fa",
    response_model=ResponseEnvelope[TransactionDetail],
    status_code=201,
    summary="Register an FA transaction by hand",
)
async def create_fa_transaction(
    payload: FaTransactionCreate,
    user: FaUser,
    session: DbSession,
) -> ResponseEnvelope[TransactionDetail]:
    """AGFZE's second business line, created the way the first one is.

    Purchase's standalone pattern rather than sales' attach-to-an-existing-batch one, and
    deliberately so: a sale is the sell side of cargo already bought and belongs on that cargo's
    transaction, whereas FA is a structurally separate business line with nothing to attach to.

    Beyond deciding which leg to create, nothing here is FA-specific. The same batch numbering,
    the same synthetic portal request that keeps BR-01 honest, the same commodity resolution, the
    same validation run, the same exception routing and the same approval queue. That is the
    whole claim this step makes about the engine, and this endpoint is where it is collected on.

    `extra_fields` is validated against the configured FA schema before a single value is
    persisted. A key the schema does not carry is refused outright - `fa_legs.extra_fields` is a
    correctable field like any other, not somewhere arbitrary JSON can be posted.
    """
    configured = {row.name for row in await _fa_schema(session)}
    unknown = sorted(set(payload.extra_fields) - configured)
    if unknown:
        raise ConflictError(
            "These fields are not in the configured FA document schema, so they cannot be "
            f"recorded: {', '.join(unknown)}. Add them to the schema first; nothing is written "
            "to an FA leg that the schema has not defined.",
            code="fa_field_not_configured",
        )

    values: dict[str, str | None] = {
        "counterparty": payload.counterparty_name,
        "transaction_reference": payload.fa_contract_reference,
        "document_type": payload.document_type,
        "commodity_code": payload.commodity_code,
        "quantity": str(payload.quantity_mt) if payload.quantity_mt is not None else None,
        "currency": payload.currency,
        **payload.extra_fields,
    }

    transaction = await transaction_service.create_manual_transaction(
        session,
        user=user,
        stream=BusinessStream.FA.value,
        batch_number=payload.batch_number,
        values=values,
    )
    await session.flush()

    await record_audit_event(
        session,
        event_type=transaction_service.AuditEvent.FA_LEG_ATTACHED,
        entity_type="trade_transaction",
        entity_id=transaction.id,
        actor_id=user.id,
        actor_type=ActorType.USER,
        metadata={
            "batch_number": transaction.batch_number,
            "origin": "manual_registration",
            "counterparty_name": payload.counterparty_name,
            "fa_contract_reference": payload.fa_contract_reference,
            "fa_document_type": payload.document_type,
            # Names only. The values are on the leg; the trail records which configured fields
            # were supplied, not what they said.
            "extra_field_names": sorted(payload.extra_fields),
        },
    )
    await record_audit_event(
        session,
        event_type=transaction_service.AuditEvent.TRANSACTION_CREATED,
        entity_type="trade_transaction",
        entity_id=transaction.id,
        actor_id=user.id,
        actor_type=ActorType.USER,
        metadata={
            "batch_number": transaction.batch_number,
            "origin": "manual_registration",
            "stream": BusinessStream.FA.value,
            "match_method": MatchMethod.MANUAL.value,
            "batch_number_supplied": bool(payload.batch_number),
        },
    )
    # The same engine, unchanged, against a leg it has never seen before.
    await rule_engine.run_validation(session, transaction)
    await session.commit()

    refreshed = await _load(session, transaction.id, user)
    return ResponseEnvelope[TransactionDetail](
        data=await _detail(session, refreshed, user),
        message=f"FA transaction {transaction.batch_number} registered.",
    )


@router.post(
    "/{transaction_id}/sales-leg",
    response_model=ResponseEnvelope[SalesAttachmentResult],
    status_code=201,
    summary="Attach a sales leg to an existing transaction",
)
async def attach_sales_leg(
    transaction_id: UUID,
    payload: SalesLegCreate,
    user: SalesUser,
    session: DbSession,
) -> ResponseEnvelope[SalesAttachmentResult]:
    """Attach the sell side of a batch to the transaction the purchase side already opened.

    Added beyond the original module list, and worth its own endpoint: attaching a leg to a
    transaction that has already been identified is a different operation from creating one, and
    overloading `POST /transactions` with it would blur the distinction that keeps this platform
    free of a merge. The transaction is named in the path, every time - by an exact batch match,
    by a confident score, by a suggestion this user confirmed, or by a batch this user searched
    for and picked. There is no route through which the server guesses.

    A transaction with no purchase leg is refused unless the caller explicitly acknowledges it. A
    sale is almost always of cargo AGFZE has already bought; quietly creating a purchase-less
    transaction would split one physical cargo across two records with nobody having decided to.
    """
    transaction = await _load(session, transaction_id, user)

    document: Document | None = None
    if payload.document_id is not None:
        document = await session.scalar(
            select(Document)
            .where(Document.id == payload.document_id)
            .options(selectinload(Document.fields), selectinload(Document.request))
        )
        if document is None:
            raise NotFoundError("The sales document quoted does not exist.")
        if document.transaction_id not in (None, transaction.id):
            raise ConflictError(
                "That document is already linked to a different transaction. Resolve the link "
                "before attaching a sales leg against it."
            )

    if transaction.purchase_leg is None:
        if not payload.acknowledge_no_purchase_leg:
            raise ConflictError(
                f"Batch {transaction.batch_number} has no purchase leg. Attaching a sales leg to "
                "a transaction with no purchase counterpart has to be acknowledged explicitly.",
                code="purchase_leg_absent",
            )
        await sales_service.record_no_match_acknowledgement(
            session,
            document=document,
            actor_id=user.id,
            note=(
                payload.acknowledgement_note or "No purchase counterpart exists for this cargo yet."
            ),
        )
        attachment = sales_service.Attachment.NO_PURCHASE_ACKNOWLEDGED
    else:
        attachment = sales_service.Attachment.USER_SELECTED

    leg, consistency = await sales_service.attach_sales_leg(
        session,
        transaction,
        sales_service.SalesLegInput(
            customer_name=payload.customer_name,
            territory=payload.territory,
            sales_contract_no=payload.sales_contract_no,
            payment_condition=payload.payment_condition,
            contracted_quantity_mt=payload.contracted_quantity_mt,
            sales_invoice_number=payload.sales_invoice_number,
            bl_reference=payload.bl_reference,
            port_of_discharge=payload.port_of_discharge,
            inland_container_depot=payload.inland_container_depot,
            customer_fixation_status=payload.customer_fixation_status,
            fixation_rate=payload.fixation_rate,
            fixation_date=payload.fixation_date,
            quantity_mt=payload.quantity_mt,
        ),
        actor_id=user.id,
        attachment=attachment,
        acknowledged_no_purchase=payload.acknowledge_no_purchase_leg,
        document=document,
    )
    await session.commit()

    refreshed = await _load(session, transaction_id, user)
    return ResponseEnvelope[SalesAttachmentResult](
        data=SalesAttachmentResult(
            transaction=await _detail(session, refreshed, user),
            attachment=attachment,
            commodity_code_mismatch=consistency.mismatch,
            commodity_message=consistency.message,
        ),
        message=(
            f"Sales leg for {leg.customer_name} attached to batch {transaction.batch_number}."
            + (
                " The commodity code does not agree - check the match."
                if consistency.mismatch
                else ""
            )
        ),
    )


@router.post(
    "/{transaction_id}/generate-draft",
    response_model=ResponseEnvelope[DraftGenerationAccepted],
    status_code=202,
    summary="Generate a draft contract, invoice, or cost sheet for review",
)
async def generate_draft(
    transaction_id: UUID,
    payload: DraftGenerationRequest,
    user: PreparingUser,
    session: DbSession,
) -> ResponseEnvelope[DraftGenerationAccepted]:
    """Queue a draft generation and hand back the job id to poll.

    The document produced is a draft for a person to read. Nothing here, and nothing anywhere in
    this platform, sends it to a customer or a counterparty: the journey of a document ends
    with a wet signature on paper, outside this system.

    Re-running this against a transaction that already has a draft produces a *new* draft beside
    the old one. Nothing is overwritten, so the transaction's document history is the full record
    of what was generated and when.
    """
    transaction = await _load(session, transaction_id, user)
    roles = set(user.roles or ())
    is_admin = PlatformRole.ADMIN.value in roles
    is_sales = PlatformRole.SALES_USER.value in roles
    is_purchase = PlatformRole.PURCHASE_USER.value in roles

    if payload.document_type in SALES_GENERATED_DOCUMENT_TYPES:
        if not (is_admin or is_sales):
            raise AuthorizationError(
                "Only users with the Sales role may generate sales draft documents."
            )
        if transaction.sales_leg is None:
            raise AuthorizationError(
                "This transaction has no sales leg to generate sales documents for."
            )
    elif payload.document_type in PURCHASE_GENERATED_DOCUMENT_TYPES:
        if not (is_admin or is_purchase):
            raise AuthorizationError(
                "Only users with the Purchase role may generate purchase draft documents."
            )
        if transaction.purchase_leg is None:
            raise AuthorizationError(
                "This transaction has no purchase leg to generate purchase documents for."
            )
    else:
        raise AuthorizationError(
            f"Document type '{payload.document_type}' is not available for generation."
        )
    if transaction.status in transaction_fields.LOCKED_STATUSES:
        raise ConflictError(
            "This transaction is awaiting approval or already approved; a new draft would not "
            "match what the approver was shown."
        )

    job_id = await draft_service.queue_generation(
        session,
        transaction,
        document_type=payload.document_type,
        requested_by=user,
    )
    return ResponseEnvelope[DraftGenerationAccepted](
        data=DraftGenerationAccepted(
            transaction_id=transaction.id,
            document_type=payload.document_type,
            job_id=job_id,
        ),
        message=(
            "Draft generation is running. Poll the job for progress; the finished draft appears "
            "in this transaction's documents for review."
        ),
    )


@router.patch(
    "/{transaction_id}/fields",
    response_model=ResponseEnvelope[TransactionDetail],
    summary="Correct transaction or leg fields and re-run validation",
)
async def correct_fields(
    transaction_id: UUID,
    payload: TransactionFieldUpdate,
    user: PreparingUser,
    session: DbSession,
) -> ResponseEnvelope[TransactionDetail]:
    """Correct transaction, purchase-leg or sales-leg fields through one path.

    The accepted schema widened in Step 5 to carry the sell side, including the fixation rate and
    date that move a customer from `unfixed` to `fixed`. Recording a fixation is deliberately not
    a second endpoint: it is a correction, and it earns the same reason gate, the same provenance
    record and the same synchronous re-validation every other correction gets.
    """
    transaction = await _load(session, transaction_id, user)
    if not _may_write(user, transaction):
        raise AuthorizationError(
            "This transaction carries no leg your desk prepares, so its fields are read-only "
            "for your account."
        )

    previous_fixation = (
        transaction.sales_leg.customer_fixation_status
        if transaction.sales_leg is not None
        else None
    )

    # The lock, the reason gate, the provenance record and the synchronous re-validation all live
    # in `apply_corrections`, because the exception queue's inline correction has to be the same
    # act as this one rather than a second implementation that resembles it.
    changes = await transaction_fields.apply_corrections(
        session,
        transaction,
        [(change.name, change.value, change.reason) for change in payload.changes],
        user=user,
        audit_event_type=transaction_service.AuditEvent.TRANSACTION_FIELD_CORRECTED,
        audit_context={"origin": "transaction_workspace"},
        allowed_owners=transaction_fields.owners_for(user.roles),
    )

    if transaction.sales_leg is not None and changes:
        if transaction_fields.fixation_recorded(changes):
            await sales_service.record_fixation_audit(
                session,
                transaction,
                actor_id=user.id,
                previous_status=previous_fixation or "unfixed",
                rate=transaction.sales_leg.fixation_rate,
                fixed_on=transaction.sales_leg.fixation_date,
            )
        # A corrected quantity or contracted total changes what SL-01 says about every other
        # shipment on the same sales contract, so their recorded results are refreshed here
        # rather than left to go stale until somebody happens to open them.
        await sales_service.propagate_coverage(session, transaction, actor_id=user.id)

    await session.commit()

    refreshed = await _load(session, transaction_id, user)
    return ResponseEnvelope[TransactionDetail](
        data=await _detail(session, refreshed, user),
        message=(
            f"{len(changes)} field{'' if len(changes) == 1 else 's'} corrected and validation "
            "re-run."
            if changes
            else "No field changed; validation was re-run against the current values."
        ),
    )


@router.post(
    "/{transaction_id}/acknowledge-tolerance",
    response_model=ResponseEnvelope[TransactionDetail],
    summary="Acknowledge a self-approvable tolerance breach",
)
async def acknowledge_tolerance(
    transaction_id: UUID,
    payload: ToleranceAcknowledgement,
    user: PreparingUser,
    session: DbSession,
) -> ResponseEnvelope[TransactionDetail]:
    """Convert a flagged, self-approvable breach into a pass that names who accepted it.

    Only a breach the rule itself marked acknowledgeable can be cleared this way. The invoice
    amount's middle tier is the only one that qualifies today; a quantity or price breach is not
    self-approvable at any size, and asking to acknowledge one is refused.
    """
    transaction = await _load(session, transaction_id, user)
    if transaction.status in transaction_fields.LOCKED_STATUSES:
        raise ConflictError("This transaction is awaiting approval and can no longer be changed.")
    # The same leg ownership every other write on this router applies. Holding a preparing role is
    # not the same as preparing *this* transaction, and accepting a discrepancy on somebody else's
    # leg is a write on their record.
    if not _may_write(user, transaction):
        raise AuthorizationError(
            "This transaction carries no leg your desk prepares, so its checks are not yours to "
            "acknowledge."
        )

    current = await rule_engine.latest_evaluations(session, transaction.id)
    matches = [
        row
        for (rule_id, check_key), row in current.items()
        if rule_id == payload.rule_id
        and (payload.check_key is None or check_key == payload.check_key)
    ]
    if not matches:
        raise NotFoundError(f"{payload.rule_id} has not been evaluated for this transaction.")

    outstanding = [row for row in matches if not row.passed]
    if not outstanding:
        raise ConflictError(
            f"{payload.rule_id} is not currently failing, so there is nothing to acknowledge."
        )
    if len(outstanding) > 1:
        raise ConflictError(
            f"{payload.rule_id} has more than one failing check; name the check to acknowledge."
        )

    target = outstanding[0]
    if target.severity != RuleSeverity.ACKNOWLEDGEABLE.value:
        raise ConflictError(
            f"{target.rule_id} is a hard failure and cannot be self-approved. "
            "Correct the underlying figures instead."
        )

    # A new row, never an edit of the failing one: the failure and its acknowledgement both stay
    # on the record, in that order.
    acknowledgement = RuleEvaluation(
        transaction_id=transaction.id,
        rule_id=target.rule_id,
        check_key=target.check_key,
        passed=True,
        severity=target.severity,
        field_name=target.field_name,
        expected_value=target.expected_value,
        actual_value=target.actual_value,
        message=(f"{target.message} Acknowledged by {user.display_name}: {payload.reason}"),
        acknowledged=True,
        acknowledgement_reason=payload.reason,
        acknowledged_by_id=user.id,
        acknowledged_at=utcnow(),
    )
    session.add(acknowledgement)

    # Written and flushed before the commit that makes the acknowledgement real, so the action
    # cannot land without its audit entry.
    await record_audit_event(
        session,
        event_type=transaction_service.AuditEvent.TRANSACTION_TOLERANCE_ACKNOWLEDGED,
        entity_type="trade_transaction",
        entity_id=transaction.id,
        actor_id=user.id,
        actor_type=ActorType.USER,
        metadata={
            "batch_number": transaction.batch_number,
            "rule_id": target.rule_id,
            "check_key": target.check_key,
            "field_name": target.field_name,
            "expected_value": target.expected_value,
            "actual_value": target.actual_value,
            "reason": payload.reason,
        },
    )
    transaction.updated_at = utcnow()
    await session.commit()

    refreshed = await _load(session, transaction_id, user)
    return ResponseEnvelope[TransactionDetail](
        data=await _detail(session, refreshed, user),
        message=f"{target.rule_id} acknowledged and recorded against your account.",
    )


@router.post(
    "/{transaction_id}/submit",
    response_model=ResponseEnvelope[SubmissionResult],
    summary="Submit a fully validated transaction for approval",
)
async def submit_transaction(
    transaction_id: UUID,
    user: PreparingUser,
    session: DbSession,
) -> ResponseEnvelope[SubmissionResult]:
    """Move a transaction to `Approval Pending`, and no further.

    Nothing downstream happens here. Nothing is posted to SAP, written to a tracker or filed in a
    DMS - none of those exist yet, and none of them may be implied. What this does is real on its
    own terms: the transaction has passed every applicable check and is now waiting on a person.
    """
    transaction = await _load(session, transaction_id, user)
    if transaction.status in transaction_fields.LOCKED_STATUSES:
        raise ConflictError(
            "This transaction has already been submitted for approval."
            if transaction.status == TransactionStatus.APPROVAL_PENDING.value
            else "This transaction has already been approved."
        )
    if not _may_write(user, transaction):
        raise AuthorizationError(
            "This transaction carries no leg your desk prepares, so it is not yours to submit."
        )
    if (
        transaction.purchase_leg is None
        and transaction.sales_leg is None
        and transaction.fa_leg is None
    ):
        raise ConflictError("A transaction with no leg has nothing to submit.")

    # Re-validated here rather than trusting whatever the screen last saw: submission is the
    # gate, so it decides on the data as it stands at this instant.
    evaluations = await rule_engine.run_validation(session, transaction)
    failing = rule_engine.outstanding(evaluations)

    if failing:
        blocked = blocking(failing)
        await record_audit_event(
            session,
            event_type=transaction_service.AuditEvent.TRANSACTION_SUBMISSION_BLOCKED,
            entity_type="trade_transaction",
            entity_id=transaction.id,
            actor_id=user.id,
            actor_type=ActorType.USER,
            metadata={
                "batch_number": transaction.batch_number,
                "blocking_rules": [
                    {
                        "rule_id": row.rule_id,
                        "check_key": row.check_key,
                        "field_name": row.field_name,
                        "expected_value": row.expected_value,
                        "actual_value": row.actual_value,
                    }
                    for row in failing
                ],
            },
        )
        await session.commit()
        raise ConflictError(
            "This transaction cannot be submitted while a check is still failing: "
            + "; ".join(blocked),
            code="validation_outstanding",
            errors=[
                {
                    "code": "rule_failed",
                    "message": row.message,
                    "field": row.field_name,
                }
                for row in failing
            ],
        )

    transaction.status = TransactionStatus.APPROVAL_PENDING.value
    transaction.submitted_by_id = user.id
    transaction.submitted_at = utcnow()
    transaction.updated_at = utcnow()

    # The approval queue's row, raised on the success path of the endpoint that already existed
    # rather than by a second endpoint somebody has to remember to call. Reaching
    # `Approval Pending` and having a task waiting are now the same event.
    await approval_service.create_task(session, transaction, requested_by_id=user.id)

    await record_audit_event(
        session,
        event_type=transaction_service.AuditEvent.TRANSACTION_SUBMITTED,
        entity_type="trade_transaction",
        entity_id=transaction.id,
        actor_id=user.id,
        actor_type=ActorType.USER,
        metadata={
            "batch_number": transaction.batch_number,
            "rule_count": len(evaluations),
            "acknowledged_count": sum(1 for row in evaluations if row.acknowledged),
            "status": transaction.status,
        },
    )
    await session.commit()

    return ResponseEnvelope[SubmissionResult](
        data=SubmissionResult(
            transaction_id=transaction.id,
            status=transaction.status,
            submitted_at=transaction.submitted_at,
        ),
        message=(
            f"Batch {transaction.batch_number} passed every applicable check and is waiting for "
            "departmental approval."
        ),
    )


@router.get(
    "/{transaction_id}/graph",
    response_model=ResponseEnvelope[TransactionGraph],
    summary="What this transaction is connected to, to a bounded depth",
)
async def read_transaction_graph(
    transaction_id: UUID,
    user: CurrentUser,
    session: DbSession,
    depth: int = Query(neo4j_service.DEFAULT_TRAVERSAL_DEPTH, ge=1, le=4),
) -> ResponseEnvelope[TransactionGraph]:
    """A traceability view: the email, documents, containers, postings and cases around one deal.

    Three things about this endpoint are deliberate and none of them should be relaxed.

    **It is not a query endpoint.** The traversal is fixed and the only input is a depth, bounded
    by the schema before it reaches the driver. There is no path here that takes Cypher from a
    request, and adding one would turn an internal read model into an arbitrary-query surface.

    **Access is decided against PostgreSQL, not the graph.** The transaction is loaded through the
    same `_load` the detail endpoint uses, which applies the caller's role and stream scoping, and
    a caller who cannot see the transaction gets a 404 before the graph is touched at all. The
    projection carries no permissions of its own and must never be asked to.

    **It is eventually consistent, and says so.** The projection lags the relational store by up to
    one sync interval. The response reports whether the graph answered at all, so the screen can
    say "this trace may be a few minutes behind" rather than implying a complete picture.
    """
    transaction = await _load(session, transaction_id, user)

    if not settings.neo4j_configured:
        return ResponseEnvelope[TransactionGraph](
            data=TransactionGraph(
                transaction_id=transaction.id,
                batch_number=transaction.batch_number,
                available=False,
                nodes=[],
                edges=[],
            ),
            message=(
                "No graph projection is configured for this deployment, so there is no trace to "
                "show. Everything it would draw is readable on this transaction already."
            ),
        )

    try:
        raw = await neo4j_service.get_graph_client().subgraph(str(transaction.id), depth=depth)
    except neo4j_service.GraphUnavailableError:
        # A read model being unreachable is not an error worth failing a page over: the caller
        # gets an honest "not available" and every other panel on the workspace still renders.
        logger.warning(
            "transaction_graph_unavailable", extra={"transaction_id": str(transaction.id)}
        )
        return ResponseEnvelope[TransactionGraph](
            data=TransactionGraph(
                transaction_id=transaction.id,
                batch_number=transaction.batch_number,
                available=False,
                nodes=[],
                edges=[],
            ),
            message="The trace is temporarily unavailable. The transaction itself is unaffected.",
        )

    return ResponseEnvelope[TransactionGraph](
        data=neo4j_service.to_graph_read(transaction, raw),
        message=(
            f"Everything connected to {transaction.batch_number} within {depth} "
            f"step{'s' if depth != 1 else ''}. Read from a projection that may lag by a few "
            "minutes; the transaction record itself is authoritative."
        ),
    )

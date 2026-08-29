"""The shipment board: where the cargo is, and the two ways that gets established.

Reads are open to every signed-in account, which is the same transparency principle the
transaction list and the exception queue follow - the whole point of moving this off one person's
morning spreadsheet is that everybody can see it. Every write is Logistics or Admin, enforced
here and not by whether a control was rendered.

The manual write is held to exactly the same standard as the automated one. It is authenticated,
role-gated, audited, plausibility-checked and it moves `last_checked_at` - because a person
telephoning the carrier and typing in what they were told is not a lesser act than an API call,
and for almost every shipment on this platform it is the only act there is.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core.dependencies import CurrentUser, DbSession, require_roles
from app.core.errors import ConflictError, NotFoundError
from app.core.roles import PlatformRole
from app.models.enums import SHIPMENT_STATUSES, BillOfLadingType
from app.models.identity import User
from app.models.logistics import Container, Shipment
from app.models.transactions import TradeTransaction
from app.schemas.common import ResponseEnvelope
from app.schemas.intake import Page
from app.schemas.logistics import (
    BillOfLadingRead,
    ContainerRead,
    LinkedTransactionRead,
    ShipmentCreate,
    ShipmentDetail,
    ShipmentIssueCreate,
    ShipmentIssueRead,
    ShipmentList,
    ShipmentListItem,
    ShipmentManualUpdate,
    ShipmentRefreshResult,
    timeline_payload,
)
from app.services import request_service
from app.services.governance import thresholds
from app.services.logistics import shipment_service, tracking_service
from app.services.logistics.adapters import registered_adapters
from app.services.rules import engine as rule_engine

router = APIRouter(prefix="/shipments", tags=["shipments"])

# Who may change a shipment. The logistics desk owns the board; Admin carries everything.
LogisticsUser = Annotated[
    User,
    Depends(require_roles(PlatformRole.LOGISTICS_USER.value, PlatformRole.ADMIN.value)),
]


def _can_manage(user: User) -> bool:
    return bool(set(user.roles or ()) & shipment_service.WRITE_ROLES)


async def _list_item(
    shipment: Shipment,
    *,
    stale_hours: float,
    transaction: TradeTransaction | None = None,
) -> ShipmentListItem:
    item = ShipmentListItem.model_validate(shipment)
    hours = shipment_service.hours_since_check(shipment)
    item.hours_since_check = round(hours, 2)
    item.is_stale = hours >= stale_hours
    item.stale_threshold_hours = int(stale_hours)
    item.container_number = (
        shipment.container.container_number if shipment.container is not None else None
    )
    if transaction is not None:
        item.batch_number = transaction.batch_number
        item.counterparty = _counterparty(transaction)
    return item


def _counterparty(transaction: TradeTransaction) -> str | None:
    """Whoever the other side of this deal is, whichever desk's leg names them."""
    for leg, attribute in (
        (transaction.purchase_leg, "supplier_name"),
        (transaction.sales_leg, "customer_name"),
        (getattr(transaction, "fa_leg", None), "counterparty_name"),
    ):
        value = getattr(leg, attribute, None) if leg is not None else None
        if value:
            return value
    return None


def _linked_transaction(transaction: TradeTransaction) -> LinkedTransactionRead:
    purchase = transaction.purchase_leg
    sales = transaction.sales_leg
    fa = getattr(transaction, "fa_leg", None)
    return LinkedTransactionRead(
        id=transaction.id,
        batch_number=transaction.batch_number,
        stream=transaction.stream,
        status=transaction.status,
        counterparty=_counterparty(transaction),
        contract_number=(
            (purchase.contract_number if purchase else None)
            or (sales.sales_contract_no if sales else None)
            or (fa.fa_contract_reference if fa else None)
        ),
        commodity_name=(transaction.commodity.display_name if transaction.commodity else None),
        quantity_mt=transaction.quantity_mt,
        currency=transaction.currency,
        has_purchase_leg=purchase is not None,
        has_sales_leg=sales is not None,
        has_fa_leg=fa is not None,
    )


async def _load_transaction(session: DbSession, transaction_id: UUID) -> TradeTransaction | None:
    return await session.scalar(
        select(TradeTransaction)
        .where(TradeTransaction.id == transaction_id)
        .options(
            selectinload(TradeTransaction.purchase_leg),
            selectinload(TradeTransaction.sales_leg),
            selectinload(TradeTransaction.fa_leg),
            selectinload(TradeTransaction.commodity),
            selectinload(TradeTransaction.containers),
        )
    )


async def _detail(
    session: DbSession, shipment: Shipment, user: User, *, stale_hours: float
) -> ShipmentDetail:
    transaction = await _load_transaction(session, shipment.transaction_id)
    base = await _list_item(shipment, stale_hours=stale_hours, transaction=transaction)

    detail = ShipmentDetail(**base.model_dump(), created_at=shipment.created_at)
    detail.container = (
        ContainerRead.model_validate(shipment.container) if shipment.container is not None else None
    )
    detail.containers = [
        ContainerRead.model_validate(row)
        for row in (transaction.containers if transaction is not None else [])
    ]
    detail.bills_of_lading = [
        BillOfLadingRead.model_validate(row) for row in shipment.bills_of_lading
    ]
    detail.issues = [
        ShipmentIssueRead(
            id=row.id,
            issue_type=row.issue_type,
            description=row.description,
            document_id=row.document_id,
            logged_by_name=row.logged_by.display_name if row.logged_by else None,
            logged_at=row.logged_at,
            resolved_at=row.resolved_at,
        )
        for row in shipment.issues
    ]
    # Derived from the audit trail on every read. There is no history table behind this.
    detail.timeline = timeline_payload(await shipment_service.milestone_timeline(session, shipment))
    detail.transaction = _linked_transaction(transaction) if transaction is not None else None
    detail.can_manage = _can_manage(user)
    detail.carrier_adapters_available = len(registered_adapters())
    return detail


async def _stale_hours(session: DbSession) -> float:
    return float(await thresholds.resolve(session, thresholds.GovernanceKey.SHIPMENT_STALE_HOURS))


@router.get(
    "",
    response_model=ResponseEnvelope[ShipmentList],
    summary="Paginated, filterable shipment board",
)
async def list_shipments(
    user: CurrentUser,
    session: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    status: str | None = Query(None),
    carrier: str | None = Query(None),
    port_of_discharge: str | None = Query(None),
    transaction_id: UUID | None = Query(None),
    search: str | None = Query(None, max_length=200),
    stale_only: bool = Query(False),
) -> ResponseEnvelope[ShipmentList]:
    if status and status not in SHIPMENT_STATUSES:
        status = None

    stale_hours = await _stale_hours(session)
    statement = shipment_service.list_query(
        status=status,
        carrier=carrier,
        port_of_discharge=port_of_discharge,
        transaction_id=transaction_id,
        search=search,
    )
    if stale_only:
        # Filtered in the query, from the stored timestamp - never from a stored staleness flag,
        # which could only ever be as fresh as whatever last wrote it.
        cutoff = shipment_service.stale_cutoff(stale_hours)
        statement = statement.where(
            func.coalesce(Shipment.last_checked_at, Shipment.created_at) <= cutoff
        )

    total = await request_service.count_query(session, statement)
    rows = list(
        (
            await session.scalars(
                statement.options(selectinload(Shipment.container))
                .order_by(
                    Shipment.last_checked_at.is_(None).desc(),
                    Shipment.last_checked_at,
                    Shipment.created_at.desc(),
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )

    batches = dict(
        (
            await session.execute(
                select(TradeTransaction.id, TradeTransaction.batch_number).where(
                    TradeTransaction.id.in_([row.transaction_id for row in rows] or [None])
                )
            )
        ).all()
    )

    items: list[ShipmentListItem] = []
    for row in rows:
        item = await _list_item(row, stale_hours=stale_hours)
        item.batch_number = batches.get(row.transaction_id)
        items.append(item)

    carriers, ports = await shipment_service.filter_values(session)
    return ResponseEnvelope[ShipmentList](
        data=ShipmentList(
            items=items,
            page=Page(
                page=page,
                page_size=page_size,
                total=total,
                total_pages=max(1, -(-total // page_size)),
            ),
            carriers=carriers,
            ports_of_discharge=ports,
            stale_threshold_hours=int(stale_hours),
            carrier_adapters_available=len(registered_adapters()),
            can_manage=_can_manage(user),
        )
    )


@router.post(
    "",
    response_model=ResponseEnvelope[ShipmentDetail],
    status_code=201,
    summary="Open a shipment against a transaction by hand",
)
async def create_shipment(
    payload: ShipmentCreate,
    user: LogisticsUser,
    session: DbSession,
) -> ResponseEnvelope[ShipmentDetail]:
    """Open a shipment for cargo the paperwork has not caught up with.

    Most shipments will arrive this way rather than off a document, because a container number is
    frequently known from the booking long before any bill of lading reaches the platform.
    """
    transaction = await _load_transaction(session, payload.transaction_id)
    if transaction is None:
        raise NotFoundError("Transaction not found.")

    container: Container | None = None
    number = (payload.container_number or "").strip().upper()
    if number:
        container = next(
            (row for row in transaction.containers if row.container_number == number), None
        )
        if container is None:
            container = Container(transaction_id=transaction.id, container_number=number)
            session.add(container)
            await session.flush()

    shipment = await shipment_service.open_shipment(
        session,
        transaction,
        container=container,
        bl_number=payload.bl_number,
        carrier=payload.carrier,
        vessel=payload.vessel,
        port_of_loading=payload.port_of_loading,
        port_of_discharge=payload.port_of_discharge,
        actor_id=user.id,
    )
    if payload.eta is not None or payload.etd is not None:
        await tracking_service.apply_manual_update(
            session,
            shipment,
            tracking_service.ShipmentUpdate(
                eta=payload.eta,
                etd=payload.etd,
                note="Recorded when the shipment was opened.",
            ),
            user=user,
        )
    await session.commit()

    refreshed = await shipment_service.get_shipment(session, shipment.id)
    return ResponseEnvelope[ShipmentDetail](
        data=await _detail(session, refreshed, user, stale_hours=await _stale_hours(session)),
        message=f"Shipment opened against batch {transaction.batch_number}.",
    )


@router.get(
    "/{shipment_id}",
    response_model=ResponseEnvelope[ShipmentDetail],
    summary="Full shipment detail: milestone timeline, issues and the linked transaction",
)
async def read_shipment(
    shipment_id: UUID, user: CurrentUser, session: DbSession
) -> ResponseEnvelope[ShipmentDetail]:
    shipment = await shipment_service.get_shipment(session, shipment_id)
    return ResponseEnvelope[ShipmentDetail](
        data=await _detail(session, shipment, user, stale_hours=await _stale_hours(session))
    )


@router.post(
    "/{shipment_id}/refresh",
    response_model=ResponseEnvelope[ShipmentRefreshResult],
    summary="Pull this shipment's status through whatever carrier adapter handles it",
)
async def refresh_shipment(
    shipment_id: UUID, user: LogisticsUser, session: DbSession
) -> ResponseEnvelope[ShipmentRefreshResult]:
    """The same adapter path the scheduled sweep uses, on demand.

    Where no adapter handles this shipment - which today is every shipment, because no carrier's
    API is specified anywhere in this platform's material and none has been invented - the
    response says so plainly and the record stays open for manual entry. That is a working
    outcome, not a failure, and it is not dressed up as either.
    """
    shipment = await shipment_service.get_shipment(session, shipment_id)
    outcome = await tracking_service.refresh_shipment(session, shipment, actor_id=user.id)
    await session.commit()

    refreshed = await shipment_service.get_shipment(session, shipment_id)
    return ResponseEnvelope[ShipmentRefreshResult](
        data=ShipmentRefreshResult(
            shipment=await _detail(
                session, refreshed, user, stale_hours=await _stale_hours(session)
            ),
            attempted=outcome.attempted,
            updated=outcome.updated,
            adapter=outcome.adapter,
            message=outcome.message,
            plausibility_flagged=outcome.plausibility_flagged,
        ),
        message=outcome.message,
    )


@router.patch(
    "/{shipment_id}",
    response_model=ResponseEnvelope[ShipmentDetail],
    summary="Record or correct a shipment's status by hand",
)
async def update_shipment(
    shipment_id: UUID,
    payload: ShipmentManualUpdate,
    user: LogisticsUser,
    session: DbSession,
) -> ResponseEnvelope[ShipmentDetail]:
    """The manual tracking path, and the one almost every shipment is actually kept current by.

    It writes the identical columns an adapter's result would, through the identical function, so
    the plausibility check and the audit entry apply to it in full. An implausible change is
    flagged for review and still saved - a heuristic that refused a correction would leave the
    wrong date in place, which is worse than asking somebody to glance at the right one.
    """
    shipment = await shipment_service.get_shipment(session, shipment_id)

    outcome = await tracking_service.apply_manual_update(
        session,
        shipment,
        tracking_service.ShipmentUpdate(
            status=payload.status,
            milestone=payload.milestone,
            eta=payload.eta,
            etd=payload.etd,
            carrier=payload.carrier,
            vessel=payload.vessel,
            port_of_loading=payload.port_of_loading,
            port_of_discharge=payload.port_of_discharge,
            bl_number=payload.bl_number,
            note=payload.note,
        ),
        user=user,
    )

    bill_recorded = False
    if payload.bl_type is not None or payload.original_bl_received is not None:
        await shipment_service.record_bill_of_lading(
            session,
            shipment,
            bl_number=payload.bl_number or shipment.bl_number,
            bl_type=payload.bl_type or BillOfLadingType.ORIGINAL.value,
            is_original_received=bool(payload.original_bl_received),
            document_id=payload.bl_document_id,
            user=user,
        )
        bill_recorded = True

    # BR-07 reads the bill-of-lading record, so recording one changes what the transaction's
    # validation says. Re-run it here rather than leaving the workspace showing yesterday's
    # answer until somebody happens to correct a field.
    if bill_recorded:
        transaction = await session.get(TradeTransaction, shipment.transaction_id)
        if transaction is not None:
            await rule_engine.run_validation(session, transaction)

    await session.commit()

    refreshed = await shipment_service.get_shipment(session, shipment_id)
    return ResponseEnvelope[ShipmentDetail](
        data=await _detail(session, refreshed, user, stale_hours=await _stale_hours(session)),
        message=(
            "Shipment updated. "
            + (
                "The change has been flagged for review: "
                + (outcome.plausibility.reason or "it does not look plausible.")
                + " It has been saved either way."
                if outcome.plausibility.flagged
                else "Recorded against your account and added to the milestone timeline."
            )
        ),
    )


@router.post(
    "/{shipment_id}/issues",
    response_model=ResponseEnvelope[ShipmentIssueRead],
    status_code=201,
    summary="Log a post-delivery issue against this shipment",
)
async def log_issue(
    shipment_id: UUID,
    payload: ShipmentIssueCreate,
    user: LogisticsUser,
    session: DbSession,
) -> ResponseEnvelope[ShipmentIssueRead]:
    shipment = await shipment_service.get_shipment(session, shipment_id)
    if shipment.transaction_id is None:
        raise ConflictError("This shipment is not linked to a transaction.")

    issue = await shipment_service.log_issue(
        session,
        shipment,
        issue_type=payload.issue_type,
        description=payload.description,
        document_id=payload.document_id,
        user=user,
    )
    await session.commit()

    return ResponseEnvelope[ShipmentIssueRead](
        data=ShipmentIssueRead(
            id=issue.id,
            issue_type=issue.issue_type,
            description=issue.description,
            document_id=issue.document_id,
            logged_by_name=user.display_name,
            logged_at=issue.logged_at,
            resolved_at=issue.resolved_at,
        ),
        message="Issue logged against this shipment and recorded on its timeline.",
    )

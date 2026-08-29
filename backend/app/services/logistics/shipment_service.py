"""Reading shipments, and the two things that create them.

Containers come from matching, as a side effect of a document being tied to a batch. Shipments
come from here: either raised alongside a container the moment a batch is known to be loaded, or
opened by hand by the logistics desk for cargo the paperwork has not caught up with.

Two things this module deliberately does not build. There is no separate milestone-history table:
every status and milestone change is already audit-logged, and `milestone_timeline` derives the
timeline from those entries, so there is exactly one record of what happened and it is the one an
auditor already reads. And there is no "manual shipment" concept - `open_shipment` produces the
same row whether a carrier or a person is going to keep it up to date.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import set_committed_value

from app.core.errors import BadRequestError, NotFoundError
from app.core.roles import PlatformRole
from app.db.base import utcnow
from app.models.audit import AuditEvent as AuditEventRow
from app.models.enums import (
    SHIPMENT_ISSUE_TYPES,
    BillOfLadingType,
    ShipmentMilestone,
    ShipmentStatus,
)
from app.models.identity import User
from app.models.intake import Document
from app.models.logistics import BillOfLading, Container, Shipment, ShipmentIssue
from app.models.transactions import TradeTransaction
from app.services.audit_service import ActorType, record_audit_event

# The roles that may change a shipment: trigger a refresh, correct a status by hand, or log an
# issue. Enforced server-side on every endpoint; the sidebar's visibility has nothing to do with
# it. Reading a shipment is open to every signed-in account, as reading a transaction is.
WRITE_ROLES: frozenset[str] = frozenset(
    {PlatformRole.LOGISTICS_USER.value, PlatformRole.ADMIN.value}
)


class AuditEvent:
    SHIPMENT_OPENED = "shipment.opened"
    SHIPMENT_STATUS_UPDATED = "shipment.status_updated"
    SHIPMENT_TRACKING_ATTEMPTED = "shipment.tracking_attempted"
    SHIPMENT_TRACKING_UNAVAILABLE = "shipment.tracking_unavailable"
    SHIPMENT_REVIEW_FLAGGED = "shipment.implausible_change_flagged"
    SHIPMENT_ISSUE_LOGGED = "shipment.issue_logged"
    SHIPMENT_BILL_RECORDED = "shipment.bill_of_lading_recorded"
    SHIPMENT_STALE = "shipment.stale_exception_opened"


# The audit events that belong on a shipment's own milestone timeline. Everything else about a
# shipment stays on the audit trail and out of the timeline, which is a narrative rather than a
# log.
TIMELINE_EVENTS: tuple[str, ...] = (
    AuditEvent.SHIPMENT_OPENED,
    AuditEvent.SHIPMENT_STATUS_UPDATED,
    AuditEvent.SHIPMENT_TRACKING_UNAVAILABLE,
    AuditEvent.SHIPMENT_REVIEW_FLAGGED,
    AuditEvent.SHIPMENT_ISSUE_LOGGED,
    AuditEvent.SHIPMENT_BILL_RECORDED,
    AuditEvent.SHIPMENT_STALE,
)

EVENT_SUMMARIES: dict[str, str] = {
    AuditEvent.SHIPMENT_OPENED: "Shipment opened",
    AuditEvent.SHIPMENT_STATUS_UPDATED: "Status updated",
    AuditEvent.SHIPMENT_TRACKING_UNAVAILABLE: "Tracking attempt returned nothing",
    AuditEvent.SHIPMENT_REVIEW_FLAGGED: "Change flagged as implausible",
    AuditEvent.SHIPMENT_ISSUE_LOGGED: "Issue logged",
    AuditEvent.SHIPMENT_BILL_RECORDED: "Bill of lading recorded",
    AuditEvent.SHIPMENT_STALE: "Exception opened: nobody has established where this cargo is",
}

# What `last_checked_source` records for an update a person made. A plain string rather than an
# enum, because the alternative values are adapter names and those are open-ended.
MANUAL_SOURCE = "manual"


def aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def hours_since_check(shipment: Shipment, *, now: datetime | None = None) -> float:
    """How long since anybody established where this cargo is.

    Counted from `last_checked_at` where there is one and from the shipment's creation where
    there is not, because a shipment nobody has ever checked is not fresher than one checked
    once - it is the least-known shipment on the board.
    """
    reference = aware(shipment.last_checked_at or shipment.created_at)
    return max(0.0, ((now or utcnow()) - reference).total_seconds() / 3600.0)


def is_active(shipment: Shipment) -> bool:
    """Whether tracking still has anything to find out.

    A delivered shipment is not silent, it is finished, and a queue that ages finished shipments
    into exceptions is a queue nobody reads.
    """
    if shipment.status == ShipmentStatus.ARRIVED.value:
        return False
    return shipment.milestone != ShipmentMilestone.DELIVERED.value


async def get_shipment(session: AsyncSession, shipment_id: UUID) -> Shipment:
    shipment = await session.scalar(
        select(Shipment)
        .where(Shipment.id == shipment_id)
        .options(
            selectinload(Shipment.container),
            selectinload(Shipment.bills_of_lading),
            selectinload(Shipment.issues),
        )
    )
    if shipment is None:
        raise NotFoundError("Shipment not found.")
    return shipment


def list_query(
    *,
    status: str | None = None,
    carrier: str | None = None,
    port_of_discharge: str | None = None,
    transaction_id: UUID | None = None,
    search: str | None = None,
) -> Select[tuple[Shipment]]:
    statement = select(Shipment)
    if status:
        statement = statement.where(Shipment.status == status)
    if carrier:
        statement = statement.where(Shipment.carrier == carrier)
    if port_of_discharge:
        statement = statement.where(Shipment.port_of_discharge == port_of_discharge)
    if transaction_id is not None:
        statement = statement.where(Shipment.transaction_id == transaction_id)
    if search:
        term = f"%{search.strip().lower()}%"
        statement = (
            statement.outerjoin(Container, Container.id == Shipment.container_id)
            .where(
                or_(
                    Shipment.bl_number.ilike(term),
                    Shipment.vessel.ilike(term),
                    Container.container_number.ilike(term),
                )
            )
            .distinct()
        )
    return statement


async def filter_values(session: AsyncSession) -> tuple[list[str], list[str]]:
    """The carriers and discharge ports actually on the board, for the dashboard's filters.

    Read from the data rather than from a hardcoded list: the carriers AGFZE ships with are
    whoever is on the shipments, and a fixed list would be both wrong and quietly out of date.
    """
    carriers = [
        value
        for value in (
            await session.scalars(
                select(Shipment.carrier).where(Shipment.carrier.is_not(None)).distinct()
            )
        ).all()
        if value
    ]
    ports = [
        value
        for value in (
            await session.scalars(
                select(Shipment.port_of_discharge)
                .where(Shipment.port_of_discharge.is_not(None))
                .distinct()
            )
        ).all()
        if value
    ]
    return sorted(carriers), sorted(ports)


async def open_shipment(
    session: AsyncSession,
    transaction: TradeTransaction,
    *,
    container: Container | None = None,
    bl_number: str | None = None,
    carrier: str | None = None,
    vessel: str | None = None,
    port_of_loading: str | None = None,
    port_of_discharge: str | None = None,
    actor_id: UUID | None = None,
) -> Shipment:
    """Open a shipment for a batch. One row, whoever ends up keeping it current.

    No `tracked_automatically` argument, and there is not going to be one. Whether a carrier
    adapter exists for this shipment is a property of the deployment at the moment somebody asks,
    not a property of the cargo, and freezing it into the row would make a shipment opened today
    behave differently from one opened after an adapter was registered.
    """
    shipment = Shipment(
        transaction_id=transaction.id,
        container_id=container.id if container is not None else None,
        bl_number=(bl_number or "").strip() or None,
        carrier=(carrier or "").strip() or None,
        vessel=(vessel or "").strip() or None,
        port_of_loading=(port_of_loading or "").strip() or None,
        port_of_discharge=(port_of_discharge or "").strip() or None,
        status=ShipmentStatus.ON_SCHEDULE.value,
        current_milestone=ShipmentMilestone.BOOKED.value,
    )
    session.add(shipment)
    await session.flush()
    # Stated rather than left unset, for the same reason a newly created transaction states its
    # absent legs: an unloaded collection read inside an async request raises rather than queries,
    # and a shipment opened a moment ago genuinely carries neither a bill nor an issue.
    set_committed_value(shipment, "bills_of_lading", [])
    set_committed_value(shipment, "issues", [])
    set_committed_value(shipment, "container", container)

    await record_audit_event(
        session,
        event_type=AuditEvent.SHIPMENT_OPENED,
        entity_type="shipment",
        entity_id=shipment.id,
        actor_id=actor_id,
        actor_type=ActorType.USER if actor_id else ActorType.AGENT,
        metadata={
            "batch_number": transaction.batch_number,
            "transaction_id": str(transaction.id),
            "container_number": container.container_number if container else None,
            "bl_number": shipment.bl_number,
            "carrier": shipment.carrier,
            "milestone": shipment.current_milestone,
            "status": shipment.status,
        },
    )
    return shipment


@dataclass(frozen=True)
class TimelineEntry:
    """One line of a shipment's history, derived rather than stored."""

    occurred_at: datetime
    event_type: str
    summary: str
    milestone: str | None
    status: str | None
    source: str | None
    actor_name: str | None
    detail: str | None


async def milestone_timeline(session: AsyncSession, shipment: Shipment) -> list[TimelineEntry]:
    """The shipment's milestone history, read out of `audit_events`.

    There is no shipment-history table and there is not going to be one. Every status and
    milestone change is already required to be audit-logged, and a second table holding the same
    facts would be a second thing to keep in  - with the certainty that one day the timeline
    on the screen and the trail an auditor reads would disagree, and nobody would know which was
    right.
    """
    rows = (
        await session.scalars(
            select(AuditEventRow)
            .where(
                AuditEventRow.entity_type == "shipment",
                AuditEventRow.entity_id == str(shipment.id),
                AuditEventRow.event_type.in_(TIMELINE_EVENTS),
            )
            .options(selectinload(AuditEventRow.actor))
            .order_by(AuditEventRow.occurred_at, AuditEventRow.id)
        )
    ).all()

    entries: list[TimelineEntry] = []
    for row in rows:
        payload = row.event_metadata or {}
        entries.append(
            TimelineEntry(
                occurred_at=row.occurred_at,
                event_type=row.event_type,
                summary=EVENT_SUMMARIES.get(row.event_type, row.event_type.replace(".", " ")),
                milestone=payload.get("milestone"),
                status=payload.get("status"),
                source=payload.get("source"),
                actor_name=row.actor.display_name if row.actor else None,
                detail=(
                    payload.get("note")
                    or payload.get("reason")
                    or payload.get("unavailable_reason")
                    or payload.get("carrier_description")
                ),
            )
        )
    return entries


async def log_issue(
    session: AsyncSession,
    shipment: Shipment,
    *,
    issue_type: str,
    description: str,
    document_id: UUID | None,
    user: User,
) -> ShipmentIssue:
    """Record something that went wrong with the cargo, against the shipment it went wrong on."""
    if issue_type not in SHIPMENT_ISSUE_TYPES:
        raise BadRequestError(
            f"Issue type must be one of: {', '.join(SHIPMENT_ISSUE_TYPES)}.",
            code="invalid_value",
        )
    cleaned = description.strip()
    if len(cleaned) < 10:
        raise BadRequestError(
            "Describe the issue in at least 10 characters; this goes on the record against the "
            "shipment and the customer may be shown it.",
            code="description_required",
        )
    if document_id is not None:
        supporting = await session.get(Document, document_id)
        if supporting is None:
            raise NotFoundError("The supporting document quoted does not exist.")

    issue = ShipmentIssue(
        shipment_id=shipment.id,
        issue_type=issue_type,
        description=cleaned,
        document_id=document_id,
        logged_by_id=user.id,
        logged_at=utcnow(),
    )
    session.add(issue)
    shipment.updated_at = utcnow()
    await session.flush()

    await record_audit_event(
        session,
        event_type=AuditEvent.SHIPMENT_ISSUE_LOGGED,
        entity_type="shipment",
        entity_id=shipment.id,
        actor_id=user.id,
        actor_type=ActorType.USER,
        metadata={
            "issue_type": issue_type,
            "transaction_id": str(shipment.transaction_id),
            "document_id": str(document_id) if document_id else None,
            "note": cleaned[:200],
        },
    )
    return issue


async def record_bill_of_lading(
    session: AsyncSession,
    shipment: Shipment,
    *,
    bl_number: str | None,
    bl_type: str,
    is_original_received: bool,
    document_id: UUID | None,
    user: User,
) -> BillOfLading:
    """Create or update this shipment's bill-of-lading record.

    The field BR-07 now reads is `is_original_received`, and this is where a person sets it. It
    is a statement about a piece of paper being physically in hand, which is why it is a human
    act with an audit entry behind it rather than something inferred from a file's classification.
    """
    bill = next(
        (
            row
            for row in shipment.bills_of_lading
            if bl_number and row.bl_number == bl_number.strip()
        ),
        None,
    ) or next(iter(shipment.bills_of_lading), None)

    previously_received = bool(bill.is_original_received) if bill is not None else False
    if bill is None:
        bill = BillOfLading(shipment_id=shipment.id)
        session.add(bill)
        shipment.bills_of_lading.append(bill)

    bill.bl_number = (bl_number or "").strip() or bill.bl_number or shipment.bl_number
    bill.bl_type = bl_type
    bill.document_id = document_id if document_id is not None else bill.document_id
    bill.is_original_received = is_original_received
    if is_original_received and bill.received_at is None:
        bill.received_at = utcnow()
    if not is_original_received:
        bill.received_at = None
    bill.updated_at = utcnow()

    if bill.bl_number and not shipment.bl_number:
        shipment.bl_number = bill.bl_number
    shipment.updated_at = utcnow()
    await session.flush()

    await record_audit_event(
        session,
        event_type=AuditEvent.SHIPMENT_BILL_RECORDED,
        entity_type="shipment",
        entity_id=shipment.id,
        actor_id=user.id,
        actor_type=ActorType.USER,
        metadata={
            "transaction_id": str(shipment.transaction_id),
            "bl_number": bill.bl_number,
            "bl_type": bill.bl_type,
            "is_original_received": bill.is_original_received,
            "was_received": previously_received,
            "note": (
                "Original bill of lading recorded as received."
                if bill.is_original_received
                else "Bill of lading recorded; the original is not yet in hand."
            ),
        },
    )
    return bill


def final_bill(shipment: Shipment) -> BillOfLading | None:
    """The received, non-draft bill on this shipment, if there is one. What BR-07 looks for."""
    return next(
        (
            row
            for row in shipment.bills_of_lading
            if row.is_original_received and row.bl_type != BillOfLadingType.DRAFT.value
        ),
        None,
    )


async def shipments_for_transactions(
    session: AsyncSession, transaction_ids: list[UUID]
) -> dict[UUID, list[Shipment]]:
    """Every shipment on each of these transactions, in one query.

    Used by the transaction list, which has to show a shipment status per row and must not issue
    a query per row to do it.
    """
    if not transaction_ids:
        return {}
    rows = (
        await session.scalars(
            select(Shipment)
            .where(Shipment.transaction_id.in_(transaction_ids))
            .options(selectinload(Shipment.container))
            .order_by(Shipment.created_at)
        )
    ).all()
    grouped: dict[UUID, list[Shipment]] = {}
    for row in rows:
        grouped.setdefault(row.transaction_id, []).append(row)
    return grouped


# The order a transaction's overall shipment status is reduced in: the worst news wins. A batch
# split across two containers where one has arrived and one is in exception is a batch with a
# problem, and the list has one cell to say so in.
STATUS_SEVERITY: tuple[str, ...] = (
    ShipmentStatus.EXCEPTION.value,
    ShipmentStatus.DELAYED.value,
    ShipmentStatus.ON_SCHEDULE.value,
    ShipmentStatus.ARRIVED.value,
)


def summarise_status(shipments: list[Shipment]) -> str | None:
    """One status for a transaction that may have several shipments, or None where it has none.

    None is a real answer and the list renders it as such. A transaction with no shipment record
    is not "on schedule"; nobody has said anything about its cargo at all.
    """
    if not shipments:
        return None
    present = {row.status for row in shipments}
    for status in STATUS_SEVERITY:
        if status in present:
            return status
    return next(iter(present))


def stale_cutoff(hours: float, *, now: datetime | None = None) -> datetime:
    return (now or utcnow()) - timedelta(hours=hours)

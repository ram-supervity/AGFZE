"""Writing the Loading Sheet row for a confirmed purchase batch.

Two destinations, one set of figures. `tracker_fields(transaction)` is the single source of both,
so a row held in this platform's table and a row written into AGFZE's workbook can never carry
different numbers for the same batch.

Where a SharePoint/Excel workbook is configured the write goes through the Graph Excel client the
tracker adapter already uses - `upsert_tracker_row`, row-level, locate-and-patch or append. This
module never opens, downloads or saves a workbook file, and there is no code path here that
could: somebody with the tracker open in Excel at the same moment is never overwritten.

Where it is not configured, the row is recorded here as `pending` and the existing periodic
worker drains it the moment a connection appears. That is the whole of the fallback: not a
different sheet, not a manual instruction, the same row waiting for the same write.

Everything is keyed on the batch number and enforced unique by the table, so re-confirming a
transaction updates the row it already has. There is no path that produces a second row for one
batch.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.base import utcnow
from app.models.enums import LoadingSheetSyncStatus
from app.models.integration import LoadingSheetRow
from app.models.transactions import TradeTransaction
from app.services.audit_service import ActorType, record_audit_event
from app.services.graph_service import GraphError, TrackerNotConfiguredError, get_graph_client
from app.services.integration.payloads import tracker_fields

logger = get_logger(__name__)


class AuditEvent:
    ROW_WRITTEN = "loading_sheet.row_written"
    ROW_UPDATED = "loading_sheet.row_updated"
    ROW_SYNCED = "loading_sheet.row_synced"
    ROW_SYNC_FAILED = "loading_sheet.row_sync_failed"


def workbook_configured() -> bool:
    return bool(settings.tracker_configured)


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def _columns(transaction: TradeTransaction, fields: dict[str, Any]) -> dict[str, Any]:
    """The named columns, read out of the tracker payload rather than off the legs again.

    Deriving them from `fields` rather than from the transaction a second time is what guarantees
    the sheet's own columns and the payload it posts describe the same figures.
    """
    purchase = transaction.purchase_leg
    return {
        "batch_number": fields.get("batch_number") or transaction.batch_number,
        "batch_source": transaction.batch_number_source,
        "transaction_id": transaction.id,
        "supplier_name": fields.get("counterparty"),
        "commodity_code": fields.get("commodity_code"),
        "commodity_name": fields.get("commodity_name"),
        "quantity_mt": _decimal(fields.get("quantity_mt")),
        "currency": fields.get("currency") or transaction.currency,
        "rate": _decimal(fields.get("rate")),
        "amount": _decimal(fields.get("amount")),
        "port_of_loading": fields.get("port_of_loading")
        or (purchase.port_of_loading if purchase else None),
        "supplier_invoice_number": fields.get("supplier_invoice_number"),
        "contract_number": fields.get("contract_number"),
        "tracker_payload": fields,
    }


async def row_for_batch(session: AsyncSession, batch_number: str) -> LoadingSheetRow | None:
    return await session.scalar(
        select(LoadingSheetRow).where(LoadingSheetRow.batch_number == batch_number)
    )


async def row_for_transaction(
    session: AsyncSession, transaction_id: UUID
) -> LoadingSheetRow | None:
    return await session.scalar(
        select(LoadingSheetRow).where(LoadingSheetRow.transaction_id == transaction_id)
    )


@dataclass(frozen=True)
class UpsertResult:
    row: LoadingSheetRow
    created: bool


async def upsert_row(
    session: AsyncSession,
    transaction: TradeTransaction,
    *,
    actor_id: UUID | None = None,
) -> UpsertResult:
    """Record this batch's Loading Sheet row, creating it once and updating it thereafter.

    Idempotent by the batch number, which is the cargo's identity: a second confirmation of the
    same transaction refreshes the figures in place and writes no second row.
    """
    fields = tracker_fields(transaction)
    values = _columns(transaction, fields)
    existing = await row_for_batch(session, str(values["batch_number"]))

    if existing is None:
        row = LoadingSheetRow(
            **values,
            sync_status=LoadingSheetSyncStatus.PENDING.value,
        )
        session.add(row)
        await session.flush()
        created = True
    else:
        row = existing
        changed = False
        for name, value in values.items():
            if getattr(row, name) != value:
                setattr(row, name, value)
                changed = True
        if changed and row.sync_status == LoadingSheetSyncStatus.SYNCED.value:
            # The figures moved after the workbook was written, so the workbook is now behind.
            # Re-queued rather than left claiming a sync that no longer describes this batch.
            row.sync_status = LoadingSheetSyncStatus.PENDING.value
        row.updated_at = utcnow()
        await session.flush()
        created = False

    await record_audit_event(
        session,
        event_type=AuditEvent.ROW_WRITTEN if created else AuditEvent.ROW_UPDATED,
        entity_type="loading_sheet_row",
        entity_id=row.id,
        actor_id=actor_id,
        actor_type=ActorType.USER if actor_id else ActorType.SYSTEM,
        metadata={
            "batch_number": row.batch_number,
            "transaction_id": str(transaction.id),
            "sync_status": row.sync_status,
            "workbook_configured": workbook_configured(),
            "tracker_fields": fields,
        },
    )
    return UpsertResult(row=row, created=created)


async def sync_row(session: AsyncSession, row: LoadingSheetRow) -> LoadingSheetRow:
    """Push one held row into the configured workbook through the existing Graph Excel path."""
    if not workbook_configured():
        return row

    row.sync_attempts += 1
    try:
        result = await get_graph_client().upsert_tracker_row(dict(row.tracker_payload or {}))
    except TrackerNotConfiguredError:
        row.sync_error = "The tracker workbook configuration is incomplete on this deployment."
        row.updated_at = utcnow()
        await session.flush()
        return row
    except GraphError as exc:
        row.sync_status = LoadingSheetSyncStatus.FAILED.value
        row.sync_error = f"The Loading Sheet workbook could not be written ({exc.reason})."
        row.updated_at = utcnow()
        await record_audit_event(
            session,
            event_type=AuditEvent.ROW_SYNC_FAILED,
            entity_type="loading_sheet_row",
            entity_id=row.id,
            actor_type=ActorType.SYSTEM,
            metadata={
                "batch_number": row.batch_number,
                "reason": exc.reason,
                "attempt": row.sync_attempts,
            },
        )
        await session.flush()
        return row

    reference = (
        f"{settings.TRACKER_TABLE_NAME}!row {result.row_index}"
        if settings.TRACKER_TABLE_NAME
        else f"row {result.row_index}"
    )
    row.sync_status = LoadingSheetSyncStatus.SYNCED.value
    row.external_reference = reference
    row.sync_error = None
    row.synced_at = utcnow()
    row.updated_at = row.synced_at
    await record_audit_event(
        session,
        event_type=AuditEvent.ROW_SYNCED,
        entity_type="loading_sheet_row",
        entity_id=row.id,
        actor_type=ActorType.SYSTEM,
        metadata={
            "batch_number": row.batch_number,
            "external_reference": reference,
            "action": result.action,
            "row_index": result.row_index,
        },
    )
    await session.flush()
    logger.info(
        "loading_sheet_row_synced",
        extra={"batch_number": row.batch_number, "row_index": result.row_index},
    )
    return row


async def drain(session: AsyncSession, *, limit: int = 50) -> int:
    """Write every row still held here into the workbook. Returns how many genuinely landed.

    Called by the existing periodic worker. It does nothing at all where no workbook is
    configured, which is the state every deployment is in until AGFZE names one - the rows simply
    keep waiting, and nothing is lost by them waiting.
    """
    if not workbook_configured():
        return 0

    rows = list(
        (
            await session.scalars(
                select(LoadingSheetRow)
                .where(
                    LoadingSheetRow.sync_status.in_(
                        (
                            LoadingSheetSyncStatus.PENDING.value,
                            LoadingSheetSyncStatus.FAILED.value,
                        )
                    )
                )
                .order_by(LoadingSheetRow.updated_at)
                .limit(max(1, limit))
            )
        ).all()
    )
    synced = 0
    for row in rows:
        await sync_row(session, row)
        if row.sync_status == LoadingSheetSyncStatus.SYNCED.value:
            synced += 1
    return synced


def list_query(
    *,
    search: str | None = None,
    sync_status: str | None = None,
    supplier: str | None = None,
    commodity_code: str | None = None,
) -> Select[tuple[LoadingSheetRow]]:
    statement = select(LoadingSheetRow)
    if sync_status:
        statement = statement.where(LoadingSheetRow.sync_status == sync_status)
    if supplier:
        statement = statement.where(LoadingSheetRow.supplier_name.ilike(f"%{supplier.strip()}%"))
    if commodity_code:
        statement = statement.where(LoadingSheetRow.commodity_code == commodity_code)
    if search and search.strip():
        needle = f"%{search.strip()}%"
        statement = statement.where(
            or_(
                LoadingSheetRow.batch_number.ilike(needle),
                LoadingSheetRow.supplier_name.ilike(needle),
                LoadingSheetRow.contract_number.ilike(needle),
                LoadingSheetRow.supplier_invoice_number.ilike(needle),
                LoadingSheetRow.port_of_loading.ilike(needle),
            )
        )
    return statement


def apply_visibility(statement: Select, streams: frozenset[str]) -> Select:
    """Scope a Loading Sheet query the way the transaction list is scoped, and by the same rule.

    A row is a view onto a transaction, so it is visible to exactly whoever may see that
    transaction. An account holding no recognised platform role reaches nothing at all.
    """
    if not streams:
        return statement.where(LoadingSheetRow.id.is_(None))
    return statement.where(
        LoadingSheetRow.transaction_id.in_(
            select(TradeTransaction.id).where(TradeTransaction.stream.in_(sorted(streams)))
        )
    )


async def count(session: AsyncSession, statement: Select) -> int:
    return int(
        await session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    )

"""One Loading Sheet row per batch, mirroring `payloads.tracker_fields` column for column.

This table is not a second tracker and it is not a cache. It is what a deployment with no
SharePoint/Excel workbook configured has instead of one: the same figures, in the same columns,
under this platform's own field names, recorded the moment a purchase transaction is confirmed
with its bundle complete rather than left unwritten until somebody configures Graph.

`sync_status` and `external_reference` are what make that honest. A row written here says
`pending` until the existing integration worker drains it into the real workbook and records the
row reference Graph returned, at which point it says `synced` and names it. Nothing in this
module opens, reads or saves a file: where a workbook is configured the write goes through the
Graph Excel client the tracker adapter already uses, row-level, exactly as it always has.

`tracker_payload` holds the complete `tracker_fields()` output for the transaction as it stood
when the row was written. The named columns below are the ones the Loading Sheet screen filters
and sorts on; the payload is what is actually posted, so the two can never disagree about what
was sent.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, utcnow
from app.db.types import GUID, JSONBType
from app.models.enums import (
    BATCH_NUMBER_SOURCES,
    LOADING_SHEET_SYNC_STATUSES,
    LoadingSheetSyncStatus,
    sql_in_list,
)
from app.models.transactions import TradeTransaction
from app.models.transactions.trade import MONEY, QUANTITY


class LoadingSheetRow(Base):
    __tablename__ = "loading_sheet_rows"
    __table_args__ = (
        CheckConstraint(
            f"sync_status IN ({sql_in_list(LOADING_SHEET_SYNC_STATUSES)})",
            name="loading_sheet_row_sync_status_valid",
        ),
        CheckConstraint(
            f"batch_source IS NULL OR batch_source IN ({sql_in_list(BATCH_NUMBER_SOURCES)})",
            name="loading_sheet_row_batch_source_valid",
        ),
        CheckConstraint("sync_attempts >= 0", name="loading_sheet_row_sync_attempts_valid"),
        # One row per batch, enforced by the database rather than by the service that writes it.
        # Re-confirming a transaction has to update the row it already has; a second row for the
        # same cargo is the one failure a loading sheet cannot survive.
        UniqueConstraint("batch_number", name="uq_loading_sheet_rows_batch_number"),
        Index("ix_loading_sheet_rows_sync_status_updated_at", "sync_status", "updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    batch_number: Mapped[str] = mapped_column(String(32), index=True)
    # Whether the batch number came off a counterparty's paperwork or was allocated here, carried
    # onto the sheet so a reader can tell a real reference from a placeholder.
    batch_source: Mapped[str | None] = mapped_column(String(16), index=True)
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("trade_transactions.id", ondelete="CASCADE"), index=True
    )
    supplier_name: Mapped[str | None] = mapped_column(String(255), index=True)
    commodity_code: Mapped[str | None] = mapped_column(String(32), index=True)
    commodity_name: Mapped[str | None] = mapped_column(String(128))
    quantity_mt: Mapped[Decimal | None] = mapped_column(QUANTITY)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    rate: Mapped[Decimal | None] = mapped_column(MONEY)
    amount: Mapped[Decimal | None] = mapped_column(MONEY)
    port_of_loading: Mapped[str | None] = mapped_column(String(128))
    supplier_invoice_number: Mapped[str | None] = mapped_column(String(64), index=True)
    contract_number: Mapped[str | None] = mapped_column(String(64), index=True)
    # The complete `tracker_fields()` output, exactly as it would be posted to the workbook.
    tracker_payload: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)
    sync_status: Mapped[str] = mapped_column(
        String(16), index=True, default=LoadingSheetSyncStatus.PENDING.value
    )
    # The workbook's own identifier for the row, once one has genuinely been written.
    external_reference: Mapped[str | None] = mapped_column(String(255))
    sync_attempts: Mapped[int] = mapped_column(Integer, default=0)
    sync_error: Mapped[str | None] = mapped_column(Text)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    transaction: Mapped[TradeTransaction] = relationship(lazy="selectin")

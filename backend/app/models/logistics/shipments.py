"""Containers, shipments, bills of lading and post-delivery issues.

One principle runs through every table here and is worth stating before the columns: **a
shipment tracked by a carrier adapter and a shipment tracked by a person typing into a form are
the same row, with the same columns, read by the same screen.** There is no `manual` table, no
`manual` flag that changes what is displayed, and no column that only one of the two paths fills.
The only difference between them is which audit event recorded the last update, which is where a
question about provenance belongs.

That matters because, today, most shipments will have no adapter at all: carrier tracking access
is negotiated carrier by carrier and none has been. A design that made the manual path a
second-class one would make the platform second-class for almost every shipment it holds.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
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
from app.db.types import GUID
from app.models.enums import (
    BILL_OF_LADING_TYPES,
    SHIPMENT_ISSUE_TYPES,
    SHIPMENT_MILESTONES,
    SHIPMENT_STATUSES,
    BillOfLadingType,
    ShipmentMilestone,
    ShipmentStatus,
    sql_in_list,
)
from app.models.identity import User
from app.models.transactions.trade import QUANTITY, TradeTransaction

if TYPE_CHECKING:
    from app.models.intake import Document


class Container(Base):
    """One physical box on one batch.

    `container_number` is indexed because it is BR-03's match key, and BR-03 is a question asked
    across transactions: has this box already been claimed by a different deal? A batch that
    legitimately spans several containers produces several rows here and BR-03 has nothing to say
    about it - the rule is about a container appearing on two unrelated transactions, never about
    a transaction carrying more than one container.
    """

    __tablename__ = "containers"
    __table_args__ = (
        UniqueConstraint(
            "transaction_id", "container_number", name="uq_containers_transaction_number"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("trade_transactions.id", ondelete="CASCADE"), index=True
    )
    container_number: Mapped[str] = mapped_column(String(32), index=True)
    seal_number: Mapped[str | None] = mapped_column(String(32))
    quantity_mt: Mapped[Decimal | None] = mapped_column(QUANTITY)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    transaction: Mapped[TradeTransaction] = relationship(back_populates="containers")


class Shipment(Base):
    """Where one batch's cargo physically is, however that was found out."""

    __tablename__ = "shipments"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({sql_in_list(SHIPMENT_STATUSES)})", name="shipment_status_valid"
        ),
        CheckConstraint(
            f"current_milestone IS NULL OR current_milestone IN "
            f"({sql_in_list(SHIPMENT_MILESTONES)})",
            name="shipment_milestone_valid",
        ),
        Index("ix_shipments_status_last_checked_at", "status", "last_checked_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("trade_transactions.id", ondelete="CASCADE"), index=True
    )
    # Optional: a shipment may cover the whole batch rather than one named box.
    container_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("containers.id", ondelete="SET NULL"), index=True
    )
    bl_number: Mapped[str | None] = mapped_column(String(64), index=True)
    carrier: Mapped[str | None] = mapped_column(String(128), index=True)
    vessel: Mapped[str | None] = mapped_column(String(128))
    port_of_loading: Mapped[str | None] = mapped_column(String(128), index=True)
    port_of_discharge: Mapped[str | None] = mapped_column(String(128), index=True)
    etd: Mapped[date | None] = mapped_column(Date)
    eta: Mapped[date | None] = mapped_column(Date, index=True)
    current_milestone: Mapped[str | None] = mapped_column(String(24), index=True)
    status: Mapped[str] = mapped_column(
        String(16), index=True, default=ShipmentStatus.ON_SCHEDULE.value
    )
    # When somebody or something last established where this cargo was. NULL means nobody has
    # yet, and the dashboard says exactly that rather than showing a comforting timestamp.
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    # How the last update arrived: the adapter's name, or `manual`. Provenance, never behaviour -
    # nothing in the application reads this to decide what to show or what to allow.
    last_checked_source: Mapped[str | None] = mapped_column(String(64))
    # Consecutive failed adapter attempts. Reset by any successful pull or manual update, and
    # read by the staleness sweep, which treats repeated failure the same way it treats silence.
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    # A necessary addition beyond the stated column list, and the only way the plausibility check
    # in Section 9.7 can be real: a change that looks wrong is flagged for a person to look at
    # rather than silently accepted, and the save is never blocked on a heuristic.
    review_flagged: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    review_reason: Mapped[str | None] = mapped_column(Text)
    review_flagged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    transaction: Mapped[TradeTransaction] = relationship(back_populates="shipments")
    container: Mapped[Container | None] = relationship(lazy="selectin")
    bills_of_lading: Mapped[list[BillOfLading]] = relationship(
        back_populates="shipment",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="BillOfLading.created_at",
    )
    issues: Mapped[list[ShipmentIssue]] = relationship(
        back_populates="shipment",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="ShipmentIssue.logged_at",
    )

    @property
    def milestone(self) -> str:
        return self.current_milestone or ShipmentMilestone.UNKNOWN.value


class BillOfLading(Base):
    """The purpose-built record BR-07 now asks, rather than inferring from a document type.

    A draft bill and an original carry the same fields and say the same things; what separates
    them is what they prove, and that is `bl_type` together with `is_original_received`. Reading
    it off `documents.document_type` was always the looser signal, and from this step it is the
    supporting one rather than the authority.
    """

    __tablename__ = "bills_of_lading"
    __table_args__ = (
        CheckConstraint(
            f"bl_type IN ({sql_in_list(BILL_OF_LADING_TYPES)})",
            name="bill_of_lading_type_valid",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    shipment_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("shipments.id", ondelete="CASCADE"), index=True
    )
    bl_type: Mapped[str] = mapped_column(
        String(16), index=True, default=BillOfLadingType.ORIGINAL.value
    )
    bl_number: Mapped[str | None] = mapped_column(String(64), index=True)
    is_original_received: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("documents.id", ondelete="SET NULL"), index=True
    )
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    shipment: Mapped[Shipment] = relationship(back_populates="bills_of_lading")
    document: Mapped[Document | None] = relationship(lazy="selectin")


class ShipmentIssue(Base):
    """Something that went wrong with the cargo after it left, logged against the shipment."""

    __tablename__ = "shipment_issues"
    __table_args__ = (
        CheckConstraint(
            f"issue_type IN ({sql_in_list(SHIPMENT_ISSUE_TYPES)})",
            name="shipment_issue_type_valid",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    shipment_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("shipments.id", ondelete="CASCADE"), index=True
    )
    issue_type: Mapped[str] = mapped_column(String(16), index=True)
    description: Mapped[str] = mapped_column(Text)
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("documents.id", ondelete="SET NULL"), index=True
    )
    logged_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    logged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    shipment: Mapped[Shipment] = relationship(back_populates="issues")
    document: Mapped[Document | None] = relationship(lazy="selectin")
    logged_by: Mapped[User | None] = relationship(lazy="selectin")

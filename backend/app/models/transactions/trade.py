"""The trade transaction, its purchase leg, and the reference data they resolve against.

`TradeTransaction` is the shared parent record for one physical batch of material. It carries
nothing that belongs to a single desk: the commercial terms of the buy live on `PurchaseLeg`,
and the sales and FA legs Steps 5 and 6 introduced hang off this same row through their own
one-to-one foreign keys. Adding those legs never altered this table, and neither did adding the
containers and shipments Step 6 attaches to it.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, utcnow
from app.db.types import GUID, JSONBType
from app.models.enums import (
    BATCH_NUMBER_SOURCES,
    BUSINESS_STREAMS,
    INVOICE_STATUSES,
    MATCH_METHODS,
    PRICE_BASES,
    TRANSACTION_STATUSES,
    BatchNumberSource,
    TransactionStatus,
    sql_in_list,
)
from app.models.identity import User

if TYPE_CHECKING:
    from app.models.logistics import Container, Shipment
    from app.models.transactions.fa import FaLeg
    from app.models.transactions.sales import SalesLeg

# Money and quantity are stored as exact decimals, never floats: the amount tolerance in BR-06
# turns on a one-dollar boundary, and a binary-float representation of 199062.50 cannot be
# trusted to sit on the right side of it.
MONEY = Numeric(18, 4)
QUANTITY = Numeric(14, 3)
PERCENT = Numeric(7, 4)


class CommodityCode(Base):
    """Trade grades the platform recognises.

    A code the extraction reports that is not in this table is never silently accepted: the
    transaction is flagged for a person to resolve, because a wrong grade misprices the deal.
    """

    __tablename__ = "commodity_codes"

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(128))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BatchSequence(Base):
    """One counter row per batch-number prefix.

    The sequence is allocated by incrementing this row in a single atomic statement, never by
    reading the highest batch number and adding one: two requests that read the same maximum
    would both propose the same batch. The unique index on `trade_transactions.batch_number` is
    the second line of defence behind it.
    """

    __tablename__ = "batch_sequences"

    prefix: Mapped[str] = mapped_column(String(16), primary_key=True)
    next_value: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class TradeTransaction(Base):
    __tablename__ = "trade_transactions"
    __table_args__ = (
        CheckConstraint(
            f"stream IN ({sql_in_list(BUSINESS_STREAMS)})", name="trade_transaction_stream_valid"
        ),
        CheckConstraint(
            f"status IN ({sql_in_list(TRANSACTION_STATUSES)})",
            name="trade_transaction_status_valid",
        ),
        CheckConstraint(
            f"price_basis IS NULL OR price_basis IN ({sql_in_list(PRICE_BASES)})",
            name="trade_transaction_price_basis_valid",
        ),
        CheckConstraint(
            f"match_method IS NULL OR match_method IN ({sql_in_list(MATCH_METHODS)})",
            name="trade_transaction_match_method_valid",
        ),
        CheckConstraint(
            f"batch_number_source IN ({sql_in_list(BATCH_NUMBER_SOURCES)})",
            name="trade_transaction_batch_number_source_valid",
        ),
        Index("ix_trade_transactions_stream_status", "stream", "status"),
        Index("ix_trade_transactions_status_created_at", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    # For a purchase-originated transaction this equals the batch number. Stated assumption: the
    # batch is the identity of the physical cargo, and a sales or FA leg added later hangs off the
    # same identity rather than minting a competing one.
    transaction_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    batch_number: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    # Whether the batch number above is the counterparty's own reference or a placeholder the
    # platform allocated because the first document to arrive stated none. See
    # `BatchNumberSource`: a placeholder is adopted onto the stated reference the moment a
    # document carrying one is matched to this transaction, and a stated one never moves.
    batch_number_source: Mapped[str] = mapped_column(
        String(16), default=BatchNumberSource.ALLOCATED.value, nullable=False
    )
    stream: Mapped[str] = mapped_column(String(16), index=True)
    status: Mapped[str] = mapped_column(
        String(32), index=True, default=TransactionStatus.MATCHED.value
    )
    commodity_code: Mapped[str | None] = mapped_column(
        String(16), ForeignKey("commodity_codes.code", ondelete="RESTRICT"), index=True
    )
    # What the document actually said, kept even when it resolved to no known code.
    extracted_commodity_value: Mapped[str | None] = mapped_column(String(128))
    # Set when the extracted grade matched nothing active in `commodity_codes`.
    commodity_needs_review: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    quantity_mt: Mapped[Decimal | None] = mapped_column(QUANTITY)
    price_basis: Mapped[str | None] = mapped_column(String(16), index=True)
    lme_percentage: Mapped[Decimal | None] = mapped_column(PERCENT)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    request_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("requests.id", ondelete="RESTRICT"), index=True
    )
    # The most recent matching decision: how the transaction was opened, or how the last
    # document to arrive was tied to it. The audit trail behind it carries every link in order.
    match_method: Mapped[str | None] = mapped_column(String(32), index=True)
    match_score: Mapped[float | None] = mapped_column(Numeric(6, 2))
    match_rationale: Mapped[str | None] = mapped_column(Text)
    # Correction history for the fields a person may edit here, keyed by "<owner>.<field>". The
    # AI's first value and its confidence are written once and never rewritten, exactly as
    # `extracted_fields` does for the document layer.
    field_overrides: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    submitted_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    # Unused until the closure step much later in the roadmap; declared now so the column does
    # not have to be added under a live table.
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    purchase_leg: Mapped[PurchaseLeg | None] = relationship(
        back_populates="transaction",
        lazy="selectin",
        uselist=False,
        cascade="all, delete-orphan",
    )
    # Added in Step 5. A relationship, not a column: the foreign key that performs the attachment
    # lives on `sales_legs`, so this table's own definition is unchanged - exactly what Step 3
    # said would happen when the sales leg arrived.
    sales_leg: Mapped[SalesLeg | None] = relationship(
        back_populates="transaction",
        lazy="selectin",
        uselist=False,
        cascade="all, delete-orphan",
    )
    # Added in Step 6, and added the same way for the third time: the foreign key that performs
    # the attachment lives on `fa_legs`, so this table's definition is again unchanged.
    fa_leg: Mapped[FaLeg | None] = relationship(
        back_populates="transaction",
        lazy="selectin",
        uselist=False,
        cascade="all, delete-orphan",
    )
    # Every container this batch was loaded into, and every shipment carrying them. Both are
    # relationships for the same reason the legs are: `containers` and `shipments` hold the
    # foreign keys, and this table did not have to change to gain either.
    containers: Mapped[list[Container]] = relationship(
        back_populates="transaction",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="Container.created_at",
    )
    shipments: Mapped[list[Shipment]] = relationship(
        back_populates="transaction",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="Shipment.created_at",
    )
    commodity: Mapped[CommodityCode | None] = relationship(lazy="selectin")
    created_by: Mapped[User | None] = relationship(lazy="selectin", foreign_keys=[created_by_id])


class PurchaseLeg(Base):
    """The buy side of one batch: who it was bought from and on what terms."""

    __tablename__ = "purchase_legs"
    __table_args__ = (
        CheckConstraint(
            f"invoice_status IN ({sql_in_list(INVOICE_STATUSES)})",
            name="purchase_leg_invoice_status_valid",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        ForeignKey("trade_transactions.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    supplier_name: Mapped[str | None] = mapped_column(String(255), index=True)
    supplier_invoice_number: Mapped[str | None] = mapped_column(String(64), index=True)
    contract_number: Mapped[str | None] = mapped_column(String(64), index=True)
    invoice_status: Mapped[str] = mapped_column(String(16), index=True)
    amount: Mapped[Decimal | None] = mapped_column(MONEY)
    rate: Mapped[Decimal | None] = mapped_column(MONEY)
    advance_payment_percent: Mapped[Decimal | None] = mapped_column(PERCENT)
    # The date the price was fixed against the exchange, where the deal is priced on LME.
    hedge_date: Mapped[date | None] = mapped_column(Date)
    # The lowest and highest exchange price observed on the hedging day.
    #
    # Discovery names both the range and, separately, an "LLME" - the lowest LME - which is the
    # low end of that same range rather than a third quantity, so it is `hedge_low_price` here
    # rather than a differently-named column holding the same number twice.
    #
    # Captured and displayed, and nothing else: no rule fires off either value. A range is a
    # record of what the market did that day, and what a tolerable position inside it looks like
    # is a commercial judgement nobody has stated. Inventing a rule from it would be inventing the
    # judgement too. Both nullable, because most deals are not LME-priced at all and a deal that
    # is may still have been hedged before anybody recorded the range.
    hedge_low_price: Mapped[Decimal | None] = mapped_column(MONEY)
    hedge_high_price: Mapped[Decimal | None] = mapped_column(MONEY)
    port_of_loading: Mapped[str | None] = mapped_column(String(128))
    # Whether this purchase is a B2B deal done jointly with a partner, and who that partner is.
    #
    # A tag and a name, and deliberately nothing more. Discovery described a distinct commercial
    # model here - full advance against a provisional invoice, a negotiated profit split, shared
    # expenses - but the only concrete figures anywhere in this platform's material are
    # illustrative examples (50/50, 60/40, 65/35), and no source document says how a split is
    # chosen for a given deal, how shared expenses are captured, or what happens to a loss.
    # Columns for those would be a guess wearing a schema, and every one of them would have to be
    # migrated again once the real answer arrives.
    #
    # What these two do carry is the part that was unambiguous: a B2B deal is distinguishable from
    # an ordinary one, and can be filtered for. See docs/KNOWN-GAPS.md for what is still open.
    is_b2b: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    b2b_partner_name: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    transaction: Mapped[TradeTransaction] = relationship(back_populates="purchase_leg")

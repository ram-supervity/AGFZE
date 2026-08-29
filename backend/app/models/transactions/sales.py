"""The sell side of one batch: who it was sold to, on what terms, and against which contract.

`SalesLeg` attaches to `TradeTransaction` through its own one-to-one foreign key, exactly as
`PurchaseLeg` does. That is the whole of the attachment described throughout  - the parent
table is not altered, gains no column and loses no constraint, which is what 's design
promised and what this module is the proof of.

There is no separate sales-contract entity, and this  does not invent one. A contract is
identified by `sales_contract_no`, and every leg quoting that number is a shipment against it;
`contracted_quantity_mt` is the total that contract covers, expected to be the same figure on
every leg that shares the number. That is what makes the cross-transaction coverage check
possible without a table the roadmap does not put here.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, utcnow
from app.db.types import GUID
from app.models.enums import (
    FIXATION_STATUSES,
    PAYMENT_CONDITIONS,
    TERRITORIES,
    FixationStatus,
    sql_in_list,
)
from app.models.transactions.trade import MONEY, QUANTITY, TradeTransaction


class SalesLeg(Base):
    __tablename__ = "sales_legs"
    __table_args__ = (
        CheckConstraint(
            f"territory IN ({sql_in_list(TERRITORIES)})", name="sales_leg_territory_valid"
        ),
        CheckConstraint(
            f"payment_condition IN ({sql_in_list(PAYMENT_CONDITIONS)})",
            name="sales_leg_payment_condition_valid",
        ),
        CheckConstraint(
            f"customer_fixation_status IN ({sql_in_list(FIXATION_STATUSES)})",
            name="sales_leg_fixation_status_valid",
        ),
        Index("ix_sales_legs_contract_customer", "sales_contract_no", "customer_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        ForeignKey("trade_transactions.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    customer_name: Mapped[str] = mapped_column(String(255), index=True)
    territory: Mapped[str] = mapped_column(String(16), index=True)
    sales_contract_no: Mapped[str] = mapped_column(String(64), index=True)
    # A necessary, well-justified addition beyond the original field list: the invoice-versus-
    # quantity check this 's scope requires needs somewhere to record the total quantity a
    # sales contract actually covers, and there is no separate sales-contract entity to hold it.
    # Expected to be consistent across every leg sharing the contract number.
    contracted_quantity_mt: Mapped[Decimal | None] = mapped_column(QUANTITY)
    sales_invoice_number: Mapped[str | None] = mapped_column(String(64), index=True)
    bl_reference: Mapped[str | None] = mapped_column(String(64), index=True)
    payment_condition: Mapped[str] = mapped_column(String(8), index=True)
    customer_fixation_status: Mapped[str] = mapped_column(
        String(16), index=True, default=FixationStatus.UNFIXED.value
    )
    fixation_rate: Mapped[Decimal | None] = mapped_column(MONEY)
    fixation_date: Mapped[date | None] = mapped_column(Date)
    port_of_discharge: Mapped[str | None] = mapped_column(String(128))
    inland_container_depot: Mapped[str | None] = mapped_column(String(128))
    # What the sales-side document actually said the grade was, kept verbatim. The transaction's
    # own `commodity_code` is shared by construction between the legs, so a genuine disagreement
    # can only show up as a difference between this value and that one - which is a strong signal
    # the wrong transaction was matched, and is exactly what the consistency check looks for.
    # It is never compared against the purchase side's free-text description.
    extracted_commodity_value: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    transaction: Mapped[TradeTransaction] = relationship(back_populates="sales_leg")

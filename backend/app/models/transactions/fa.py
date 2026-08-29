"""AGFZE's second business line, hung off the same parent record the other two use.

`FaLeg` attaches to `TradeTransaction` through its own one-to-one foreign key, exactly as
`PurchaseLeg` and `SalesLeg` do. The parent table gains no column and loses no constraint to make
room for it - the third time that has now held, which is the whole point of proving it again.

What is deliberately thin here is the field list. AGFZE's own material states that FA's exact
fields, document types and tolerances are not finalised, and instructs against inventing them, so
this table carries only what that material actually names: a counterparty, a contract reference, a
document type, and a structured column for everything configuration adds later. When those fields
are agreed they arrive as rows in `document_type_schemas` and land in `extra_fields`; no column,
no migration and no frontend change is needed to carry them.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, utcnow
from app.db.types import GUID, JSONBType
from app.models.transactions.trade import TradeTransaction


def _decimal_from(payload: dict[str, Any] | None, name: str) -> Decimal | None:
    """Read one numeric value out of `extra_fields`, or None when it is absent or unreadable.

    Never raises and never guesses. A value the business has not configured a column for is still
    a value the shared evaluators may want to compare, and this is how they reach it without FA
    growing columns nobody has agreed.
    """
    raw = (payload or {}).get(name)
    if raw is None:
        return None
    try:
        return Decimal(str(raw).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None


class FaLeg(Base):
    __tablename__ = "fa_legs"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        ForeignKey("trade_transactions.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    counterparty_name: Mapped[str | None] = mapped_column(String(255), index=True)
    fa_contract_reference: Mapped[str | None] = mapped_column(String(64), index=True)
    # The FA document type this leg was raised off, as the business names it. Free text on
    # purpose: no FA document-type vocabulary exists to constrain it against, and inventing one
    # is exactly what this  is told not to do.
    document_type: Mapped[str | None] = mapped_column(String(64), index=True)
    # Every confirmed field the configured schema carries that has no named column here, keyed by
    # field name. Written only through the validated correction path, never as arbitrary JSON.
    extra_fields: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    transaction: Mapped[TradeTransaction] = relationship(back_populates="fa_leg")

    @property
    def amount(self) -> Decimal | None:
        """The transaction value, wherever configuration has put it.

        A read-only view over `extra_fields`, not a column: the shared BR-06 evaluator asks a leg
        for its amount, and answering that question for FA must not require this table to grow a
        column AGFZE has not agreed to.
        """
        return _decimal_from(self.extra_fields, "amount")

    @property
    def rate(self) -> Decimal | None:
        return _decimal_from(self.extra_fields, "rate")

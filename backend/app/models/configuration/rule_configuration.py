"""Configuration that drives the business-rule engine.

Not one tolerance, threshold or limit is written in application code. Every evaluator asks this
table for the value it compares against, resolved for the transaction in front of it, so the
business can change a limit through the Step 9 admin screen without a redeploy - and so the value
that was applied to a past decision is recoverable from the row that was live at the time.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import ClassVar

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, utcnow
from app.db.types import GUID
from app.models.enums import BUSINESS_STREAMS, sql_in_list
from app.models.identity import User


class RuleConfiguration(Base):
    __tablename__ = "rule_configurations"
    __table_args__ = (
        CheckConstraint(
            f"scope_stream IS NULL OR scope_stream IN ({sql_in_list(BUSINESS_STREAMS)})",
            name="rule_configuration_scope_stream_valid",
        ),
        CheckConstraint(
            "threshold_unit IN ('percent', 'currency', 'count', 'ratio', 'score')",
            name="rule_configuration_threshold_unit_valid",
        ),
        UniqueConstraint(
            "rule_id",
            "check_key",
            "scope_commodity_code",
            "scope_transaction_type",
            name="uq_rule_configurations_rule_scope",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    rule_id: Mapped[str] = mapped_column(String(8), index=True)
    # A rule that carries more than one boundary names them. BR-06's invoice-amount check has two
    # (the rounding tolerance and the self-approval ceiling) and they are not the same number.
    check_key: Mapped[str] = mapped_column(String(48), index=True)
    # The scope, as typed columns rather than opaque JSON so it can be indexed and so a
    # half-spelled scope cannot be stored. NULL on a column means "applies to anything".
    # `scope_stream` is what Step 6 leans on: the FA stream's own defaults are rows scoped to it,
    # sitting beside the unscoped rows the scrap stream still resolves to, so the two are
    # distinguishable without either one being edited out from under the other.
    scope_commodity_code: Mapped[str | None] = mapped_column(
        String(16), ForeignKey("commodity_codes.code", ondelete="CASCADE"), index=True
    )
    scope_transaction_type: Mapped[str | None] = mapped_column(String(16), index=True)
    scope_stream: Mapped[str | None] = mapped_column(String(16), index=True)
    threshold_value: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    threshold_unit: Mapped[str] = mapped_column(String(16), default="percent")
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    # Mandatory: a threshold that moved without a stated reason is not a change anybody can audit.
    change_reason: Mapped[str] = mapped_column(Text)
    changed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    # Who last moved this threshold. Read by the admin screen so a row shows the person
    # behind its stated reason, not just the reason.
    changed_by: Mapped[User | None] = relationship(lazy="selectin")

    # How much each scope column narrows a row. Weighted rather than counted so the ordering is
    # total: a commodity-scoped row is more specific than a stream-scoped one, and two rows can
    # never tie on specificity and be separated by whichever the query happened to return first.
    SCOPE_WEIGHTS: ClassVar[tuple[tuple[str, int], ...]] = (
        ("scope_commodity_code", 4),
        ("scope_transaction_type", 2),
        ("scope_stream", 1),
    )

    @property
    def specificity(self) -> int:
        """How narrowly this row is scoped. The narrowest matching row wins."""
        return sum(
            weight for column, weight in self.SCOPE_WEIGHTS if getattr(self, column) is not None
        )

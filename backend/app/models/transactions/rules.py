"""The evidence trail the rule engine writes.

`rule_evaluations` is append-only in the same sense `audit_events` is: re-running validation
inserts a fresh row for every check, and never updates or deletes one. The most recent row per
(transaction, rule, check) is the authoritative current result; everything behind it is the
history of how the transaction got there, which is exactly what an auditor needs to read.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, utcnow
from app.db.types import GUID
from app.models.enums import RULE_SEVERITIES, sql_in_list
from app.models.identity import User


class RuleEvaluation(Base):
    __tablename__ = "rule_evaluations"
    __table_args__ = (
        CheckConstraint(
            f"severity IN ({sql_in_list(RULE_SEVERITIES)})", name="rule_evaluation_severity_valid"
        ),
        Index(
            "ix_rule_evaluations_transaction_rule",
            "transaction_id",
            "rule_id",
            "check_key",
            "evaluated_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("trade_transactions.id", ondelete="CASCADE"), index=True
    )
    rule_id: Mapped[str] = mapped_column(String(8), index=True)
    # BR-06 is three genuinely different checks over three different fields. The check key is how
    # they stay distinguishable without pretending they are three separate rules.
    check_key: Mapped[str | None] = mapped_column(String(48), index=True)
    passed: Mapped[bool] = mapped_column(Boolean, index=True)
    severity: Mapped[str] = mapped_column(String(16), index=True)
    field_name: Mapped[str | None] = mapped_column(String(128))
    expected_value: Mapped[str | None] = mapped_column(String(255))
    actual_value: Mapped[str | None] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text)
    # An acknowledged pass is still a pass that a person made, not one the data earned. It is
    # carried forward across a re-run only while the values behind it are unchanged.
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    acknowledgement_reason: Mapped[str | None] = mapped_column(Text)
    acknowledged_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, default=utcnow
    )

    acknowledged_by: Mapped[User | None] = relationship(lazy="selectin")

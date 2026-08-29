"""The exception queue's two tables: the mapping that routes a failure, and the case it opens.

`RuleExceptionMapping` is the piece that keeps this module reusable. Nothing in the orchestration
knows that BR-04 means a missing document or that BR-05 means a quantity breach; it looks the
rule up in this table and uses whatever it finds.  5 and 6 bring their own rules to life by
inserting rows here, not by adding a branch anywhere.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.roles import ALL_ROLES
from app.db.base import Base, utcnow
from app.db.types import GUID
from app.models.enums import (
    EXCEPTION_CATEGORIES,
    EXCEPTION_PRIORITIES,
    ExceptionPriority,
    sql_in_list,
)
from app.models.identity import User


class RuleExceptionMapping(Base):
    """Which exception a failing rule opens, as data the engine reads at call time.

    A row may name a specific check as well as a rule: BR-06's amount check and its quantity check
    are two different problems for two different desks, and collapsing them onto one category
    would send the wrong desk the wrong work. The narrowest matching row wins - a row naming the
    check beats the rule-wide row behind it.
    """

    __tablename__ = "rule_exception_mappings"
    __table_args__ = (
        CheckConstraint(
            f"exception_type IN ({sql_in_list(EXCEPTION_CATEGORIES)})",
            name="rule_exception_mapping_type_valid",
        ),
        # These two are named shorter than reads naturally, and deliberately. With the naming
        # convention's `ck_rule_exception_mappings_` prefix in front of them, the fuller
        # `..._owner_role_valid` and `..._priority_valid` came to 66 and 64 characters, past
        # PostgreSQL's 63-character identifier limit - so what the database actually held was a
        # truncated, hashed name that could never match what the model declared, and
        # `alembic check` reported a difference on every run for ever. Kept inside the limit here
        # rather than left to be silently cut somewhere else.
        CheckConstraint(
            f"owner_role IN ({sql_in_list(ALL_ROLES)})",
            name="rule_exception_mapping_owner_valid",
        ),
        CheckConstraint(
            f"priority IN ({sql_in_list(EXCEPTION_PRIORITIES)})",
            name="rule_exception_priority_valid",
        ),
        UniqueConstraint("rule_id", "check_key", name="uq_rule_exception_mappings_rule_check"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    rule_id: Mapped[str] = mapped_column(String(8), index=True)
    # NULL means the row governs every check the rule carries.
    check_key: Mapped[str | None] = mapped_column(String(48), index=True)
    exception_type: Mapped[str] = mapped_column(String(48), index=True)
    owner_role: Mapped[str] = mapped_column(String(32), index=True)
    priority: Mapped[str] = mapped_column(String(8), default=ExceptionPriority.MEDIUM.value)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    @property
    def specificity(self) -> int:
        return 1 if self.check_key is not None else 0


class ExceptionCase(Base):
    """One real problem, owned by one desk, ageing until somebody deals with it.

    `escalated` is a stored fact about a decision a person made - somebody pressed Escalate to
    HOD. Whether a case is *overdue* is never stored: it is computed from `opened_at` against the
    configured threshold every time the case is read, so it can never be a stale flag left behind
    by a job that did not run.
    """

    __tablename__ = "exception_cases"
    __table_args__ = (
        CheckConstraint(
            f"exception_type IN ({sql_in_list(EXCEPTION_CATEGORIES)})",
            name="exception_case_type_valid",
        ),
        CheckConstraint(
            f"owner_role IN ({sql_in_list(ALL_ROLES)})", name="exception_case_owner_role_valid"
        ),
        CheckConstraint(
            f"priority IN ({sql_in_list(EXCEPTION_PRIORITIES)})",
            name="exception_case_priority_valid",
        ),
        Index("ix_exception_cases_type_resolved_at", "exception_type", "resolved_at"),
        Index("ix_exception_cases_owner_role_resolved_at", "owner_role", "resolved_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    # Nullable, and deliberately so: a low-confidence extraction is a real, ownable exception long
    # before the document it came from has been matched to any batch.
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("trade_transactions.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    request_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("requests.id", ondelete="CASCADE"), index=True
    )
    exception_type: Mapped[str] = mapped_column(String(48), index=True)
    rule_id: Mapped[str | None] = mapped_column(String(8), index=True)
    check_key: Mapped[str | None] = mapped_column(String(48), index=True)
    owner_role: Mapped[str] = mapped_column(String(32), index=True)
    # The specific person already carrying the work, where there is one. The owning role is what
    # the queue filters on; this only says who it landed with first.
    assigned_to_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    priority: Mapped[str] = mapped_column(
        String(8), index=True, default=ExceptionPriority.MEDIUM.value
    )
    summary: Mapped[str] = mapped_column(Text)
    # What the rule actually compared, snapshotted at the moment the case opened. The detail
    # screen also reads the live evaluation, so a reader sees both what went wrong and where the
    # transaction stands now - never a bare "invalid".
    field_name: Mapped[str | None] = mapped_column(String(128))
    expected_value: Mapped[str | None] = mapped_column(String(255))
    actual_value: Mapped[str | None] = mapped_column(String(255))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    resolved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    resolution_note: Mapped[str | None] = mapped_column(Text)
    escalated: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    escalated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    escalation_note: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    assigned_to: Mapped[User | None] = relationship(lazy="selectin", foreign_keys=[assigned_to_id])
    resolved_by: Mapped[User | None] = relationship(lazy="selectin", foreign_keys=[resolved_by_id])
    escalated_by: Mapped[User | None] = relationship(
        lazy="selectin", foreign_keys=[escalated_by_id]
    )

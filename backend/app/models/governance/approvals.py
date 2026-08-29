"""The approval task: one row per transaction that is genuinely waiting on a person.

`decided_by_id` and `decided_at` are written only from the verified JWT subject and the server
clock. Nothing a client sends can reach either column; there is no code path that assigns them
from a request body, and the schema that carries a decision does not have the fields to try.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.roles import ALL_ROLES, PlatformRole
from app.db.base import Base, utcnow
from app.db.types import GUID
from app.models.enums import APPROVAL_DECISIONS, ApprovalDecision, sql_in_list
from app.models.identity import User


class ApprovalTask(Base):
    __tablename__ = "approval_tasks"
    __table_args__ = (
        CheckConstraint(
            f"decision IN ({sql_in_list(APPROVAL_DECISIONS)})", name="approval_task_decision_valid"
        ),
        CheckConstraint(
            f"approver_role IN ({sql_in_list(ALL_ROLES)})",
            name="approval_task_approver_role_valid",
        ),
        Index("ix_approval_tasks_decision_requested_at", "decision", "requested_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("trade_transactions.id", ondelete="CASCADE"), index=True
    )
    approver_role: Mapped[str] = mapped_column(
        String(32), index=True, default=PlatformRole.APPROVER_HOD.value
    )
    # Optional: a task may be put to a named approver, or left to whoever on the desk picks it up.
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    requested_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, default=utcnow
    )
    decision: Mapped[str] = mapped_column(
        String(24), index=True, default=ApprovalDecision.PENDING.value
    )
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    # Required for a rejection or a request for changes; never asked for on an approval.
    reason: Mapped[str | None] = mapped_column(Text)
    # Generated on first view of the decision screen and kept, never regenerated per request. A
    # null summary is a normal, fully usable state: the screen renders from the transaction.
    ai_summary: Mapped[str | None] = mapped_column(Text)
    ai_summary_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ai_summary_error: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    assignee: Mapped[User | None] = relationship(lazy="selectin", foreign_keys=[assignee_id])
    requested_by: Mapped[User | None] = relationship(
        lazy="selectin", foreign_keys=[requested_by_id]
    )
    decided_by: Mapped[User | None] = relationship(lazy="selectin", foreign_keys=[decided_by_id])

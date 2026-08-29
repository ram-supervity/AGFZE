"""Audit trail storage.

The `audit_events` table is append-only. No update or delete route may ever be exposed on it, at
any role, and no service may mutate a row once it is written; a correction is recorded as a new
event that references the same entity.

`event_metadata` holds metadata only - identifiers, role slugs, decision outcomes, counts. It must
never carry document text and never an AI prompt or response. Anything that needs the payload
itself belongs in the owning domain table, not here.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, utcnow
from app.db.types import GUID, JSONBType
from app.models.identity import User


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint("actor_type IN ('user', 'system', 'agent')", name="actor_type_valid"),
        Index("ix_audit_events_entity", "entity_type", "entity_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, default=utcnow
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    actor_type: Mapped[str] = mapped_column(String(16), default="system")
    event_type: Mapped[str] = mapped_column(String(128), index=True)
    entity_type: Mapped[str] = mapped_column(String(128), index=True)
    entity_id: Mapped[str | None] = mapped_column(String(128), index=True)
    # Attribute is event_metadata because SQLAlchemy reserves `metadata` on declarative classes.
    event_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONBType, default=dict)

    actor: Mapped[User | None] = relationship(lazy="selectin")

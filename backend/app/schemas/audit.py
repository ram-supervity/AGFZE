"""Read model for the append-only audit trail. There is deliberately no create, update or
delete schema: rows are written only through ``app.services.audit_service``."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.intake import Page


class AuditEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    occurred_at: datetime
    actor_id: UUID | None
    actor_type: str
    event_type: str
    entity_type: str
    entity_id: str | None
    # The ORM attribute is ``event_metadata`` because SQLAlchemy reserves ``metadata`` on a
    # declarative class; the wire key stays ``metadata`` to match the column.
    event_metadata: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias="event_metadata",
        serialization_alias="metadata",
    )


class AuditEventListItem(BaseModel):
    """One row of the explorer.

    `event_metadata` here is the *summary* the read layer produced, not the stored payload: keys
    that could only ever hold content are redacted by name and long values are truncated. The
    explorer is a governance screen, never a viewer for a source document or a model prompt.
    """

    id: UUID
    occurred_at: datetime
    actor_id: UUID | None
    actor_name: str | None
    actor_email: str | None
    actor_type: str
    event_type: str
    entity_type: str
    entity_id: str | None
    event_metadata: dict[str, Any] = Field(default_factory=dict, serialization_alias="metadata")


class AuditActorRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    display_name: str
    email: str


class AuditEventList(BaseModel):
    items: list[AuditEventListItem]
    page: Page
    # Populated from the data itself rather than a list written by hand, so an event type a later
    #  introduces appears in the filter the moment it is first recorded.
    event_types: list[str]
    entity_types: list[str]
    actors: list[AuditActorRead]

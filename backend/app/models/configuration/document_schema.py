"""Configuration that drives extraction.

`DocumentTypeSchema` is the only place a document type's field list is allowed to live. No
service may carry a hardcoded field list: adding a field or a whole document type is a row
change here, never a code change. Step 9 adds the screen that edits these rows; this step ships
the table, its defaults, and the selection logic that reads it.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, utcnow
from app.db.types import GUID, JSONBType
from app.models.enums import DOCUMENT_TYPES, TERRITORIES, sql_in_list
from app.models.identity import User


class DocumentTypeSchema(Base):
    __tablename__ = "document_type_schemas"
    __table_args__ = (
        CheckConstraint(
            f"document_type IN ({sql_in_list(DOCUMENT_TYPES)})",
            name="document_type_schema_type_valid",
        ),
        CheckConstraint(
            f"territory IS NULL OR territory IN ({sql_in_list(TERRITORIES)})",
            name="document_type_schema_territory_valid",
        ),
        UniqueConstraint(
            "document_type", "territory", name="uq_document_type_schemas_document_type"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    document_type: Mapped[str] = mapped_column(String(32), index=True)
    # NULL means "applies to every territory"; a territory row wins over it when both exist.
    territory: Mapped[str | None] = mapped_column(String(16), index=True)
    # {"fields": [{"name", "label", "type", "required", "tolerance", "section", "description"}]}
    field_schema: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)
    # Completeness checklist for the territory's document pack. Stored now, enforced in Step 3.
    mandatory_documents: Mapped[list[str]] = mapped_column(JSONBType, default=list)
    change_reason: Mapped[str] = mapped_column(Text)
    changed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    # Who last edited this schema, for the admin screen's provenance column.
    changed_by: Mapped[User | None] = relationship(lazy="selectin")

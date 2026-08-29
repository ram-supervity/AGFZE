"""The compiled document package one transaction is filed under.

Scoped narrowly, and on purpose. Step 5 already generates draft contracts and invoices as
`Document` rows, so a table that stored "the documents of a deal" a second time would be the same
capability under two names. What is genuinely new here is *compilation*: taking documents that
already exist - received ones and the drafts the platform wrote - and merging them into one file
a person can hand to the document-management system.

So a pack owns no content of its own. It owns the merged bytes, the list of what went into them,
and the two fields the DMS fills in when the upload finally lands.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow
from app.db.types import GUID, JSONBType
from app.models.enums import DOCUMENT_PACK_TYPES, sql_in_list


class DocumentPack(Base):
    __tablename__ = "document_packs"
    __table_args__ = (
        CheckConstraint(
            f"pack_type IN ({sql_in_list(DOCUMENT_PACK_TYPES)})",
            name="document_pack_type_valid",
        ),
        # One pack per type per transaction. Recompiling after a document arrives rewrites this
        # row rather than leaving two packs and no way to tell which one was filed.
        UniqueConstraint(
            "transaction_id", "pack_type", name="uq_document_packs_transaction_pack_type"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("trade_transactions.id", ondelete="CASCADE"), index=True
    )
    pack_type: Mapped[str] = mapped_column(String(24), index=True)
    # Follows the naming convention the desk already uses: ADV-{contract}-{qty}-{status} for the
    # purchase file, SO-{batch}-{qty}-{Final|Prov} for the sales pack.
    filename: Mapped[str] = mapped_column(String(512))
    storage_ref: Mapped[str] = mapped_column(String(512))
    byte_size: Mapped[int] = mapped_column(Integer, default=0)
    # The documents that went into the merge, in merge order. Without it the pack is an opaque
    # blob and nobody reading the record afterwards can say what was filed.
    source_document_ids: Mapped[list[str]] = mapped_column(JSONBType, default=list)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # Both null until the DMS job genuinely succeeds - by an accepted upload or by an
    # administrator confirming they filed it themselves and supplying the identifier.
    dms_document_id: Mapped[str | None] = mapped_column(String(255))
    dms_uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

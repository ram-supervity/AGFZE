"""Email and document intake tables introduced in Step 2."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, utcnow
from app.db.types import GUID, JSONBType
from app.models.enums import (
    BUSINESS_STREAMS,
    DOCUMENT_SOURCES,
    DOCUMENT_TYPES,
    EXTRACTION_STATUSES,
    REQUEST_CATEGORIES,
    REQUEST_SOURCES,
    REQUEST_STATUSES,
    TERRITORIES,
    DocumentSource,
    ExtractionStatus,
    RequestStatus,
    sql_in_list,
)
from app.models.identity import User


class EmailMessage(Base):
    """One captured mailbox message.

    `provider_message_id` is the deduplication key. The webhook path and the delta-poll path both
    reach the same ingestion function, and the unique index is what makes a race between them
    resolve to a single row rather than two requests for one email.
    """

    __tablename__ = "email_messages"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    provider_message_id: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    mailbox_address: Mapped[str] = mapped_column(String(320), index=True)
    sender_address: Mapped[str | None] = mapped_column(String(320), index=True)
    sender_name: Mapped[str | None] = mapped_column(String(255))
    subject: Mapped[str | None] = mapped_column(String(1024))
    body_text: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    has_attachments: Mapped[bool] = mapped_column(Boolean, default=False)
    # Opaque storage key for the untouched original message, never a filesystem path.
    raw_storage_ref: Mapped[str | None] = mapped_column(String(512))
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Request(Base):
    __tablename__ = "requests"
    __table_args__ = (
        CheckConstraint(f"source IN ({sql_in_list(REQUEST_SOURCES)})", name="request_source_valid"),
        CheckConstraint(
            f"category IS NULL OR category IN ({sql_in_list(REQUEST_CATEGORIES)})",
            name="request_category_valid",
        ),
        CheckConstraint(
            f"stream IS NULL OR stream IN ({sql_in_list(BUSINESS_STREAMS)})",
            name="request_stream_valid",
        ),
        CheckConstraint(
            f"status IN ({sql_in_list(REQUEST_STATUSES)})", name="request_status_valid"
        ),
        Index("ix_requests_status_created_at", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    request_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    source: Mapped[str] = mapped_column(String(16), index=True)
    email_message_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("email_messages.id", ondelete="SET NULL"), index=True
    )
    category: Mapped[str | None] = mapped_column(String(32), index=True)
    category_confidence: Mapped[float | None] = mapped_column(Float, index=True)
    category_rationale: Mapped[str | None] = mapped_column(Text)
    # The AI's first answer survives every correction; nothing overwrites it.
    original_category: Mapped[str | None] = mapped_column(String(32))
    category_overridden: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    category_override_reason: Mapped[str | None] = mapped_column(Text)
    category_overridden_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    category_overridden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stream: Mapped[str | None] = mapped_column(String(16), index=True)
    original_stream: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(
        String(32), index=True, default=RequestStatus.RECEIVED.value
    )
    # Set when classification could not reach the configured confidence, or failed outright.
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    classification_error: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    email_message: Mapped[EmailMessage | None] = relationship(lazy="selectin")
    documents: Mapped[list[Document]] = relationship(
        back_populates="request",
        lazy="selectin",
        order_by="Document.created_at",
        cascade="all, delete-orphan",
    )


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(
            f"document_type IS NULL OR document_type IN ({sql_in_list(DOCUMENT_TYPES)})",
            name="document_type_valid",
        ),
        CheckConstraint(
            f"territory IS NULL OR territory IN ({sql_in_list(TERRITORIES)})",
            name="document_territory_valid",
        ),
        CheckConstraint(
            f"extraction_status IN ({sql_in_list(EXTRACTION_STATUSES)})",
            name="document_extraction_status_valid",
        ),
        CheckConstraint(
            f"source IN ({sql_in_list(DOCUMENT_SOURCES)})", name="document_source_valid"
        ),
        # A generated draft has no request behind it, so the pairing that must always hold is
        # "generated or a request": anything that arrived did so on a request, and only something
        # the platform wrote itself may sit without one.
        CheckConstraint(
            "request_id IS NOT NULL OR source = 'generated'",
            name="document_request_or_generated",
        ),
        Index("ix_documents_type_created_at", "document_type", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    # Nullable from Step 5 onwards. A generated draft is the first document in the platform that
    # originates from no intake event at all: nothing received it, so there is no request to
    # point at, and inventing a synthetic one would put a fiction in the intake queue.
    request_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("requests.id", ondelete="CASCADE"), index=True
    )
    # How this document came to exist. What distinguishes a draft the platform wrote from one
    # that arrived through intake, for the UI and for anything downstream that has to know.
    source: Mapped[str] = mapped_column(
        String(16), index=True, default=DocumentSource.RECEIVED.value
    )
    # Constrained from Step 3 onwards. Set by the matching service once the document has been
    # tied to a batch; a document survives the deletion of the transaction it was linked to.
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("trade_transactions.id", ondelete="SET NULL"), index=True
    )
    filename: Mapped[str] = mapped_column(String(512), index=True)
    content_type: Mapped[str] = mapped_column(String(128))
    byte_size: Mapped[int] = mapped_column(Integer)
    document_type: Mapped[str | None] = mapped_column(String(32), index=True)
    # The specific paperwork this document is, in the vocabulary BR-04's checklists are written
    # in. A list rather than a column because one document can genuinely be two entries on a
    # checklist - a mill certificate printing its own assay table is both the mill test
    # certificate and the chemical analysis - and because a document that is simply an invoice
    # carries none at all. See `DocumentKind`.
    document_kinds: Mapped[list[str]] = mapped_column(JSONBType, default=list)
    # True once somebody has set the kinds by hand. A re-extraction refreshes a machine reading
    # and leaves a human's alone, which is the same rule `extracted_fields.is_overridden` applies
    # one level down.
    kinds_overridden: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    original_document_type: Mapped[str | None] = mapped_column(String(32))
    document_type_hint: Mapped[str | None] = mapped_column(String(32))
    territory: Mapped[str | None] = mapped_column(String(16), index=True)
    storage_ref: Mapped[str] = mapped_column(String(512))
    # Rasterised page images, produced once during extraction and reused by the review viewer.
    page_image_refs: Mapped[list[str]] = mapped_column(JSONBType, default=list)
    # SHA-256 of the stored bytes: the key BR-13's duplicate detection matches on before any
    # fuzzy comparison is attempted.
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    page_count: Mapped[int | None] = mapped_column(Integer)
    extraction_status: Mapped[str] = mapped_column(
        String(16), index=True, default=ExtractionStatus.PENDING.value
    )
    extraction_error: Mapped[str | None] = mapped_column(Text)
    classification_confidence: Mapped[float | None] = mapped_column(Float, index=True)
    classification_rationale: Mapped[str | None] = mapped_column(Text)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    confirmed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, default=utcnow
    )

    request: Mapped[Request | None] = relationship(back_populates="documents", lazy="selectin")
    fields: Mapped[list[ExtractedField]] = relationship(
        back_populates="document",
        lazy="selectin",
        order_by="ExtractedField.field_name",
        cascade="all, delete-orphan",
    )


class ExtractedField(Base):
    __tablename__ = "extracted_fields"
    __table_args__ = (
        UniqueConstraint("document_id", "field_name", name="uq_extracted_fields_document_field"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    field_name: Mapped[str] = mapped_column(String(128), index=True)
    field_value: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float, index=True)
    rationale: Mapped[str | None] = mapped_column(Text)
    source_page: Mapped[int | None] = mapped_column(Integer)
    # Free-form pointer back into the page: a paragraph ordinal for a text layer, a bounding box
    # for a rasterised page. Kept as JSON so neither reading has to win.
    source_reference: Mapped[dict[str, Any] | None] = mapped_column(JSONBType)
    # Set when the same field was read with two different values on different pages and neither
    # could be preferred on confidence.
    has_conflict: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    conflicting_values: Mapped[list[str]] = mapped_column(JSONBType, default=list)
    is_overridden: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    # Never rewritten once the first extraction has landed, override or not.
    original_ai_value: Mapped[str | None] = mapped_column(Text)
    original_confidence: Mapped[float | None] = mapped_column(Float)
    override_reason: Mapped[str | None] = mapped_column(Text)
    overridden_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    overridden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    document: Mapped[Document] = relationship(back_populates="fields")
    overridden_by: Mapped[User | None] = relationship(lazy="selectin")


# The states one composed reply moves through. There is no `sending`: the Graph call is made
# inside the request that a person deliberately made, and it either succeeded or it did not.
REPLY_STATUSES: tuple[str, ...] = ("draft", "sent", "failed", "withdrawn")


class EmailReplyDraft(Base):
    """A reply this platform composed on an inbound thread, and whether a person sent it.

    Discovery asks for the platform to answer a broker or a supplier on the thread their message
    arrived on, "initially via human-approved draft", and for every reply to carry the standing
    disclaimer. This table is the "initially" - and it is not a stage the platform is expected to
    grow out of, because the row exists for the same reason the approval queue does: something
    leaving this platform for a counterparty's inbox is an action with a name on it.

    Three properties are load-bearing.

    **Nothing here can be sent by the platform itself.** There is no scheduler, no worker and no
    retry that reaches the send path. A draft becomes a sent message inside a request a signed-in
    person made, and `sent_by_id` records which one.

    **The body is stored as it was approved.** Not as a template plus parameters resolved later:
    what somebody read before they sent it is what this column holds, so the audit answer to "what
    did we actually tell them" is a column rather than a reconstruction.

    **The disclaimer is not optional and not separable.** It is appended by the composer and is
    part of `body_text`; there is no code path that produces a body without it.
    """

    __tablename__ = "email_reply_drafts"
    __table_args__ = (
        CheckConstraint(f"status IN ({sql_in_list(REPLY_STATUSES)})", name="reply_status_valid"),
        Index("ix_email_reply_drafts_request_status", "request_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("requests.id", ondelete="CASCADE"), index=True
    )
    # The captured message this is a reply to. The thread is Graph's to maintain: the draft is
    # created through `createReply` on this message, so the headers that put it in the right
    # conversation are the provider's work and never this platform's guess at them.
    email_message_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("email_messages.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    subject: Mapped[str | None] = mapped_column(String(1024))
    # Exactly what was composed, disclaimer included, as plain text.
    body_text: Mapped[str] = mapped_column(Text)
    # Graph's id for the draft, once one exists there. NULL while the reply has only been composed
    # here - which is every deployment with outbound replies switched off.
    provider_draft_id: Mapped[str | None] = mapped_column(String(512))
    # Why a send did not happen. The provider's own reason, kept so the desk sees what to fix.
    failure_reason: Mapped[str | None] = mapped_column(Text)
    composed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    composed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # Who sent it. NULL on anything that has not been sent, and never set by anything but the
    # send endpoint acting for a signed-in person.
    sent_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    request: Mapped[Request] = relationship(lazy="selectin")
    email_message: Mapped[EmailMessage] = relationship(lazy="selectin")
    composed_by: Mapped[User | None] = relationship(lazy="selectin", foreign_keys=[composed_by_id])
    sent_by: Mapped[User | None] = relationship(lazy="selectin", foreign_keys=[sent_by_id])

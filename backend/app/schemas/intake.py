"""Wire models for the request queue and request detail."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import BUSINESS_STREAMS, DEAL_DIRECTIONS, REQUEST_CATEGORIES


class EmailMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sender_address: str | None
    sender_name: str | None
    subject: str | None
    # Plain text only. It is rendered as text by the client and never as markup.
    body_text: str | None
    received_at: datetime
    has_attachments: bool


class DocumentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    filename: str
    content_type: str
    byte_size: int
    document_type: str | None
    deal_direction: str | None = None
    deal_direction_confidence: float | None = None
    deal_direction_rationale: str | None = None
    territory: str | None
    page_count: int | None
    extraction_status: str
    classification_confidence: float | None
    needs_review: bool
    confirmed_at: datetime | None
    transaction_id: UUID | None
    created_at: datetime
    thumbnail_url: str | None = None


class RequestSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    request_code: str
    source: str
    category: str | None
    category_confidence: float | None
    category_overridden: bool
    deal_direction: str | None = None
    stream: str | None
    status: str
    needs_review: bool
    created_at: datetime
    updated_at: datetime
    subject: str | None = None
    sender_address: str | None = None
    document_count: int = 0
    transaction_id: UUID | None = None
    transaction_leg_type: str | None = None


class PurchaseBundleItemSummary(BaseModel):
    """One expected purchase document, and whether the intake has it yet."""

    item: str
    label: str
    received: bool
    confirmed: bool
    document_id: UUID | None = None
    filename: str | None = None


class PurchaseBundleSummary(BaseModel):
    """The three-document purchase bundle, as the inbox shows it: received / pending per item."""

    items: list[PurchaseBundleItemSummary] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    complete: bool = False
    confirmed: bool = False
    unexpected: list[PurchaseBundleItemSummary] = Field(default_factory=list)
    summary: str = ""


class RequestDetail(RequestSummary):
    category_rationale: str | None = None
    original_category: str | None = None
    category_override_reason: str | None = None
    category_overridden_at: datetime | None = None
    original_stream: str | None = None
    classification_error: str | None = None
    deal_direction_confidence: float | None = None
    deal_direction_rationale: str | None = None
    email: EmailMessageRead | None = None
    documents: list[DocumentSummary] = Field(default_factory=list)
    # Present only on a purchase intake. A sales or FA request carries None rather than an empty
    # bundle, so no screen can read "nothing received" off a request the bundle is not about.
    purchase_bundle: PurchaseBundleSummary | None = None


class CategoryOverrideRequest(BaseModel):
    category: str
    stream: str | None = None
    deal_direction: str | None = None
    reason: str = Field(min_length=5, max_length=1000)

    @field_validator("category")
    @classmethod
    def _known_category(cls, value: str) -> str:
        if value not in REQUEST_CATEGORIES:
            raise ValueError(f"Category must be one of: {', '.join(REQUEST_CATEGORIES)}")
        return value

    @field_validator("stream")
    @classmethod
    def _known_stream(cls, value: str | None) -> str | None:
        if value is not None and value not in BUSINESS_STREAMS:
            raise ValueError(f"Stream must be one of: {', '.join(BUSINESS_STREAMS)}")
        return value

    @field_validator("deal_direction")
    @classmethod
    def _known_direction(cls, value: str | None) -> str | None:
        if value is not None and value not in DEAL_DIRECTIONS:
            raise ValueError(f"Deal direction must be one of: {', '.join(DEAL_DIRECTIONS)}")
        return value

    @field_validator("reason")
    @classmethod
    def _meaningful_reason(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 5:
            raise ValueError("Give a reason of at least 5 characters for the correction.")
        return cleaned


class Page(BaseModel):
    page: int
    page_size: int
    total: int
    total_pages: int


class RequestQueue(BaseModel):
    items: list[RequestSummary]
    page: Page


class UploadAccepted(BaseModel):
    request_id: UUID
    request_code: str
    job_id: UUID
    document_ids: list[UUID]
    rejected: list[dict[str, str]] = Field(default_factory=list)


# --- replying on the thread a request arrived on ---------------------------------------------


class ReplyDraftRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    request_id: UUID
    status: str
    subject: str | None
    # The body exactly as it was composed, disclaimer included. What a person read before sending
    # is what is stored and what is returned, so "what did we tell them" is never reconstructed.
    body_text: str
    failure_reason: str | None
    composed_at: datetime
    composed_by_name: str | None = None
    sent_at: datetime | None
    sent_by_name: str | None = None


class ReplyDraftList(BaseModel):
    items: list[ReplyDraftRead]
    # Who the next reply on this thread would reach, so the desk is never guessing.
    recipient_address: str | None = None
    # Whether this deployment can actually send. False means a reply can be composed and read here
    # and cannot leave; the screen says so rather than offering a button that can only fail.
    outbound_enabled: bool = False


class ReplyComposeRequest(BaseModel):
    """What the desk wants to say, and nothing else.

    There is no recipient field, no subject field and no attachment field, deliberately. The
    recipient and the thread come from the captured message so a reply cannot be redirected to an
    address nobody on this platform received anything from, and the disclaimer is appended by the
    composer rather than supplied by the caller.
    """

    message: str = Field(min_length=20, max_length=8000)

    @field_validator("message")
    @classmethod
    def _substantial(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 20:
            raise ValueError(
                "Write at least a sentence. This goes to a counterparty over AGFZE's own address."
            )
        return cleaned

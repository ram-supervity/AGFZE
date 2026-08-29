"""Wire models for the request queue and request detail."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import BUSINESS_STREAMS, REQUEST_CATEGORIES


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
    stream: str | None
    status: str
    needs_review: bool
    created_at: datetime
    updated_at: datetime
    subject: str | None = None
    sender_address: str | None = None
    document_count: int = 0


class RequestDetail(RequestSummary):
    category_rationale: str | None = None
    original_category: str | None = None
    category_override_reason: str | None = None
    category_overridden_at: datetime | None = None
    original_stream: str | None = None
    classification_error: str | None = None
    email: EmailMessageRead | None = None
    documents: list[DocumentSummary] = Field(default_factory=list)


class CategoryOverrideRequest(BaseModel):
    category: str
    stream: str | None = None
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

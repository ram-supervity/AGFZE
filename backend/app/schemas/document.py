"""Wire models for the document index and the review screen."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.config import settings
from app.models.enums import DOCUMENT_TYPES, TERRITORIES
from app.schemas.intake import Page
from app.schemas.transaction import MatchOutcomeRead


class FieldSchemaRead(BaseModel):
    name: str
    label: str
    type: str
    required: bool
    tolerance: float | None
    section: str
    description: str


class ExtractedFieldRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    field_name: str
    field_value: str | None
    confidence: float | None
    rationale: str | None
    source_page: int | None
    source_reference: dict[str, Any] | None
    has_conflict: bool
    conflicting_values: list[str] = Field(default_factory=list)
    is_overridden: bool
    original_ai_value: str | None
    original_confidence: float | None
    override_reason: str | None
    overridden_at: datetime | None
    overridden_by_name: str | None = None
    # Resolved from the field's configured type so the client renders the right input.
    label: str | None = None
    type: str = "string"
    required: bool = False
    section: str = "Extracted fields"
    reason_required: bool = False


class DocumentListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    request_id: UUID
    request_code: str | None = None
    filename: str
    document_type: str | None
    territory: str | None
    extraction_status: str
    classification_confidence: float | None
    needs_review: bool
    confirmed_at: datetime | None
    page_count: int | None
    byte_size: int
    created_at: datetime
    # Set once matching has tied the document to a batch.
    transaction_id: UUID | None = None
    thumbnail_url: str | None = None


class DocumentList(BaseModel):
    items: list[DocumentListItem]
    page: Page


class DocumentDetail(DocumentListItem):
    content_type: str
    content_hash: str
    classification_rationale: str | None = None
    original_document_type: str | None = None
    document_type_hint: str | None = None
    extraction_error: str | None = None
    uploaded_by_name: str | None = None
    confirmed_by_name: str | None = None
    source_url: str | None = None
    page_image_urls: list[str] = Field(default_factory=list)
    fields: list[ExtractedFieldRead] = Field(default_factory=list)
    schema_fields: list[FieldSchemaRead] = Field(default_factory=list)
    # The gate the review screen applies when deciding whether a correction needs a reason.
    # Read from configuration rather than restated by the client.
    confidence_threshold: float = Field(
        default_factory=lambda: settings.CONFIDENCE_THRESHOLD_DEFAULT
    )
    mandatory_documents: list[str] = Field(default_factory=list)


class FieldCorrection(BaseModel):
    field_name: str = Field(min_length=1, max_length=128)
    value: str | None = None
    reason: str | None = None


class FieldCorrectionRequest(BaseModel):
    corrections: list[FieldCorrection] = Field(min_length=1, max_length=100)


class ReclassifyRequest(BaseModel):
    document_type: str
    territory: str | None = None
    reason: str = Field(min_length=5, max_length=1000)

    @field_validator("document_type")
    @classmethod
    def _known_type(cls, value: str) -> str:
        if value not in DOCUMENT_TYPES:
            raise ValueError(f"Document type must be one of: {', '.join(DOCUMENT_TYPES)}")
        return value

    @field_validator("territory")
    @classmethod
    def _known_territory(cls, value: str | None) -> str | None:
        if value is not None and value not in TERRITORIES:
            raise ValueError(f"Territory must be one of: {', '.join(TERRITORIES)}")
        return value


class ReclassifyAccepted(BaseModel):
    document_id: UUID
    job_id: UUID


class ConfirmationResult(BaseModel):
    document_id: UUID
    request_id: UUID
    extraction_status: str
    confirmed_at: datetime
    # What matching did with the document the moment it was confirmed. Absent for a document
    # that is not on the purchase pipeline.
    matching: MatchOutcomeRead | None = None

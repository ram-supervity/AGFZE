"""Wire models for the document index and the review screen."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.config import settings
from app.models.enums import DEAL_DIRECTIONS, DOCUMENT_KINDS, DOCUMENT_TYPES, TERRITORIES
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
    # Null on a generated draft, matching the column. That document originates from no intake
    # event at all - nothing received it, so there is no request to point at - and a non-optional
    # type here fails validation for the whole page the moment one exists.
    request_id: UUID | None = None
    request_code: str | None = None
    filename: str
    document_type: str | None
    deal_direction: str | None = None
    deal_direction_confidence: float | None = None
    # What this document is in the mandatory-document checklist's own vocabulary. Empty for a
    # document that is not a checklist entry at all - an invoice, a contract - and occasionally
    # two entries long for one that genuinely evidences both.
    document_kinds: list[str] = Field(default_factory=list)
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
    deal_direction_rationale: str | None = None
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
    deal_direction: str | None = None
    # Omitted leaves the machine reading in place; supplied replaces it and marks it a human's,
    # so a later re-extraction refreshes the fields around it without overwriting the decision.
    document_kinds: list[str] | None = None
    reason: str = Field(min_length=5, max_length=1000)

    @field_validator("document_kinds")
    @classmethod
    def _known_kinds(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        unknown = [item for item in value if item not in DOCUMENT_KINDS]
        if unknown:
            raise ValueError(f"Document kind must be one of: {', '.join(DOCUMENT_KINDS)}")
        deduplicated: list[str] = []
        for item in value:
            if item not in deduplicated:
                deduplicated.append(item)
        return deduplicated

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

    @field_validator("deal_direction")
    @classmethod
    def _known_direction(cls, value: str | None) -> str | None:
        if value is not None and value not in DEAL_DIRECTIONS:
            raise ValueError(f"Deal direction must be one of: {', '.join(DEAL_DIRECTIONS)}")
        return value


class ReclassifyAccepted(BaseModel):
    document_id: UUID
    job_id: UUID


class PurchaseBundleItemRead(BaseModel):
    """One of the three documents a purchase deal arrives as, and whether it is here yet."""

    item: str
    label: str
    received: bool
    confirmed: bool
    document_id: UUID | None = None
    filename: str | None = None


class PurchaseBundleRead(BaseModel):
    """The bundle as a screen shows it: received / pending per document, plus what is spare."""

    items: list[PurchaseBundleItemRead] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    complete: bool = False
    confirmed: bool = False
    # Documents on this intake that a purchase bundle never carries - a contract above all, which
    # this platform generates rather than receives.
    unexpected: list[PurchaseBundleItemRead] = Field(default_factory=list)
    summary: str = ""


class ConfirmationResult(BaseModel):
    document_id: UUID
    request_id: UUID | None = None
    extraction_status: str
    confirmed_at: datetime
    # What matching did with the document the moment it was confirmed. Absent for a document
    # that is not on the purchase pipeline.
    matching: MatchOutcomeRead | None = None
    # What the confirmation set off on the purchase side: the drafts queued from the platform's
    # existing generator, and the Loading Sheet row written for the batch. Absent everywhere
    # else, so no sales confirmation response changes shape to carry it.
    purchase_bundle: PurchaseBundleRead | None = None
    generated_document_types: list[str] = Field(default_factory=list)
    generation_job_ids: list[UUID] = Field(default_factory=list)
    loading_sheet_batch: str | None = None
    loading_sheet_status: str | None = None
    completion_blocker: str | None = None

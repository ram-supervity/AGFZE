"""Request-level and document-level classification.

Both are one model call each, both come back through the AI service's schema validation, and
both fall to a visible "needs human review" state when the call fails or the model reports it
could not be certain. Nothing is guessed on the model's behalf.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field

from app.core.config import settings
from app.models.enums import (
    BUSINESS_STREAMS,
    DOCUMENT_TYPES,
    REQUEST_CATEGORIES,
    TERRITORIES,
    DocumentType,
)
from app.services.gemini_service import (
    AIServiceError,
    ImagePart,
    generate_structured,
    wrap_source_data,
)

CATEGORY_GUIDE = """\
purchase       - buying scrap: supplier offers, purchase confirmations, supplier invoices
sales          - selling scrap: customer enquiries, sales confirmations, customer invoices
fa             - finished aluminium / FA desk business rather than raw scrap
logistics      - freight booking, container movement, transport and customs correspondence
approval       - a request for internal sign-off, or a reply granting or refusing it
follow_up      - chasing something already sent: a reminder, a status question, a resend request
informational  - circulars, market reports, notices with nothing to act on
exception      - a dispute, a claim, a rejection, a quality or quantity discrepancy\
"""

STREAM_GUIDE = (
    "scrap - raw non-ferrous scrap trading; fa - the finished aluminium desk. "
    "Return null when the mail does not make the stream clear."
)

CLASSIFY_REQUEST_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": list(REQUEST_CATEGORIES)},
        "confidence": {"type": "number"},
        "rationale": {"type": "string"},
        "stream": {"type": "string", "nullable": True, "enum": list(BUSINESS_STREAMS)},
    },
    "required": ["category", "confidence", "rationale"],
}

CLASSIFY_DOCUMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "document_type": {"type": "string", "enum": list(DOCUMENT_TYPES)},
        "confidence": {"type": "number"},
        "rationale": {"type": "string"},
        "territory": {"type": "string", "nullable": True, "enum": list(TERRITORIES)},
    },
    "required": ["document_type", "confidence", "rationale"],
}


class RequestClassification(BaseModel):
    category: str = Field(pattern="^(" + "|".join(REQUEST_CATEGORIES) + ")$")
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=1, max_length=600)
    stream: str | None = None

    def normalised_stream(self) -> str | None:
        return self.stream if self.stream in BUSINESS_STREAMS else None


class DocumentClassification(BaseModel):
    document_type: str = Field(pattern="^(" + "|".join(DOCUMENT_TYPES) + ")$")
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=1, max_length=600)
    territory: str | None = None

    def normalised_territory(self) -> str | None:
        return self.territory if self.territory in TERRITORIES else None


@dataclass(frozen=True)
class ClassificationOutcome:
    """What the pipeline records, whether or not the model answered usefully."""

    category: str | None
    confidence: float | None
    rationale: str | None
    stream: str | None
    needs_review: bool
    error: str | None = None


def below_threshold(confidence: float | None) -> bool:
    return confidence is None or confidence < settings.CONFIDENCE_THRESHOLD_DEFAULT


def _request_prompt(subject: str | None, body: str | None, sender: str | None) -> str:
    header = "\n".join(
        [
            "Classify this inbound trade email into exactly one business category.",
            "",
            "Categories:",
            CATEGORY_GUIDE,
            "",
            f"Business stream: {STREAM_GUIDE}",
            "",
            "Return the category, a confidence between 0 and 1, a one-sentence rationale, and "
            "the stream (or null). If the mail could plausibly be two categories, pick the more "
            "specific one and lower the confidence accordingly.",
            "",
        ]
    )
    source = "\n".join(
        [
            f"From: {sender or 'unknown sender'}",
            f"Subject: {subject or '(no subject)'}",
            "",
            body or "(no body text)",
        ]
    )
    return header + wrap_source_data("inbound email", source)


async def classify_request(
    *, subject: str | None, body: str | None, sender: str | None
) -> ClassificationOutcome:
    """Classify one inbound request. A failed call is an outcome, never an exception upwards."""
    try:
        result = await generate_structured(
            prompt=_request_prompt(subject, body, sender),
            response_schema=CLASSIFY_REQUEST_SCHEMA,
            model=RequestClassification,
            purpose="request_classification",
        )
    except AIServiceError as exc:
        return ClassificationOutcome(
            category=None,
            confidence=None,
            rationale=None,
            stream=None,
            needs_review=True,
            error=exc.reason,
        )

    return ClassificationOutcome(
        category=result.category,
        confidence=result.confidence,
        rationale=result.rationale,
        stream=result.normalised_stream(),
        needs_review=below_threshold(result.confidence),
    )


@dataclass(frozen=True)
class DocumentClassificationOutcome:
    document_type: str
    confidence: float | None
    rationale: str | None
    territory: str | None
    needs_review: bool
    error: str | None = None


def _document_prompt(filename: str, text: str, has_images: bool) -> str:
    header = "\n".join(
        [
            "Identify what kind of trade document this is.",
            "",
            "Types:",
            "invoice            - a commercial or proforma invoice",
            "contract           - a sale or purchase contract or deal confirmation",
            "bl                 - a bill of lading",
            "shipping_document  - packing list, certificate of origin, freight certificate and "
            "other shipment paperwork",
            "tracker            - a spreadsheet export listing many shipments or batches",
            "approval_evidence  - a signed approval, authorisation or internal sign-off record",
            "fa_document        - paperwork belonging to the finished aluminium desk",
            "unknown            - none of the above, or too illegible to tell",
            "",
            "Also report the territory the document belongs to (india, china, japan, other) when "
            "the language, addresses, forms or authorities make it clear, otherwise null.",
            "",
            f"File name as supplied by the sender (untrusted, may be wrong): {filename}",
            "The page images attached below are the document." if has_images else "",
            "",
        ]
    )
    return header + wrap_source_data("document text", text, limit=30_000)


async def classify_document(
    *, filename: str, text: str, images: list[ImagePart] | None = None
) -> DocumentClassificationOutcome:
    try:
        result = await generate_structured(
            prompt=_document_prompt(filename, text, bool(images)),
            response_schema=CLASSIFY_DOCUMENT_SCHEMA,
            model=DocumentClassification,
            images=images,
            purpose="document_classification",
        )
    except AIServiceError as exc:
        return DocumentClassificationOutcome(
            document_type=DocumentType.UNKNOWN.value,
            confidence=None,
            rationale=None,
            territory=None,
            needs_review=True,
            error=exc.reason,
        )

    return DocumentClassificationOutcome(
        document_type=result.document_type,
        confidence=result.confidence,
        rationale=result.rationale,
        territory=result.normalised_territory(),
        needs_review=below_threshold(result.confidence)
        or result.document_type == DocumentType.UNKNOWN.value,
    )

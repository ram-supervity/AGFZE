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
    DEAL_DIRECTIONS,
    DOCUMENT_KINDS,
    DOCUMENT_TYPES,
    INBOUND_DOCUMENT_TYPES,
    REQUEST_CATEGORIES,
    TERRITORIES,
    DealDirection,
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
        "document_type": {"type": "string", "enum": list(INBOUND_DOCUMENT_TYPES)},
        "confidence": {"type": "number"},
        "rationale": {"type": "string"},
        "territory": {"type": "string", "nullable": True, "enum": list(TERRITORIES)},
        "deal_direction": {"type": "string", "enum": list(DEAL_DIRECTIONS)},
        "deal_direction_confidence": {"type": "number"},
        "deal_direction_rationale": {"type": "string"},
        "document_kinds": {
            "type": "array",
            "items": {"type": "string", "enum": list(DOCUMENT_KINDS)},
            "description": (
                "Every checklist entry this one document genuinely evidences. Empty where none "
                "of them applies."
            ),
        },
    },
    "required": [
        "document_type",
        "confidence",
        "rationale",
        "deal_direction",
        "deal_direction_confidence",
        "deal_direction_rationale",
    ],
}

# What each kind means, in the words the checklists use. Rendered into the prompt so the
# vocabulary and its description can never drift apart in two places.
KIND_GUIDE = """\
bill_of_lading                 - a bill of lading, sea waybill or carrier shipping confirmation
packing_list                   - a list of packages, bundles or pieces and their weights
certificate_of_origin          - a certificate stating the country the goods originate in
chemical_analysis_certificate  - an assay: elements and their percentages by mass
mill_test_certificate          - a mill, quality or inspection test certificate for the material
freight_certificate            - a certificate stating the freight charged or prepaid
form_6                         - an India-bound Form 6
form_9                         - an India-bound Form 9
weight_slip                    - a weighbridge ticket or draft survey weight note
inspection_certificate         - a pre-shipment or third-party inspection report
bank_document                  - a covering letter, collection instruction or other bank paper
other                          - shipment paperwork that is none of the above\
"""


class RequestClassification(BaseModel):
    category: str = Field(pattern="^(" + "|".join(REQUEST_CATEGORIES) + ")$")
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=1, max_length=600)
    stream: str | None = None

    def normalised_stream(self) -> str | None:
        return self.stream if self.stream in BUSINESS_STREAMS else None


class DocumentClassification(BaseModel):
    document_type: str = Field(pattern="^(" + "|".join(INBOUND_DOCUMENT_TYPES) + ")$")
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=1, max_length=600)
    territory: str | None = None
    deal_direction: str = Field(
        default=DealDirection.NOT_TRADE.value,
        pattern="^(" + "|".join(DEAL_DIRECTIONS) + ")$",
    )
    deal_direction_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    deal_direction_rationale: str = Field(default="", max_length=600)
    document_kinds: list[str] = Field(default_factory=list)

    def normalised_territory(self) -> str | None:
        return self.territory if self.territory in TERRITORIES else None

    def normalised_deal_direction(self) -> str:
        return (
            self.deal_direction
            if self.deal_direction in DEAL_DIRECTIONS
            else DealDirection.NOT_TRADE.value
        )

    def normalised_kinds(self) -> list[str]:
        """Keep only known kinds, de-duplicated, in the order the model reported them.

        A value outside the vocabulary is dropped rather than stored: BR-04 reads this list to
        decide whether a required document is present, and an entry nothing can ever match would
        be a checklist item quietly satisfied by a word the model made up.
        """
        seen: list[str] = []
        for value in self.document_kinds:
            if value in DOCUMENT_KINDS and value not in seen:
                seen.append(value)
        return seen


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
    kinds: tuple[str, ...] = ()
    deal_direction: str | None = None
    deal_direction_confidence: float | None = None
    deal_direction_rationale: str | None = None


def _document_prompt(filename: str, text: str, has_images: bool) -> str:
    header = "\n".join(
        [
            "Identify what kind of trade document this is, and determine its deal direction.",
            "",
            "Types:",
            "invoice            - a commercial, provisional or proforma invoice",
            "contract           - a sale or purchase contract or deal confirmation",
            "bl                 - a bill of lading or sea waybill",
            "bl_draft           - a draft bill of lading",
            "shipping_document  - packing list, certificate of origin, freight certificate and "
            "other shipment paperwork",
            "tracker            - a spreadsheet export listing many shipments or batches",
            "approval_evidence  - a signed approval, authorisation or internal sign-off record",
            "fa_document        - paperwork belonging to the finished aluminium desk",
            "unknown            - none of the above, or too illegible to tell",
            "",
            "Deal Direction Rules (must return deal_direction: purchase | sales | not_trade):",
            "- AGFZE is the BUYER (we pay the counterparty) on supplier offers/quotations, purchase contracts and purchase confirmations, supplier proforma/commercial/provisional invoices and supplier debit notes -> purchase",
            "- AGFZE is the SELLER (we bill the counterparty) on customer enquiries, sales contracts and sales confirmations, proforma or commercial invoices issued BY AGFZE TO a customer, and sales-related bank/collection paper -> sales",
            "- Purely shipping paperwork (bill of lading, draft BL, packing list, certificate of origin, inspection/chemical/mill certificates, weight slips, freight certificates) takes the direction of the deal it evidences and must never flip it. (If evidencing a purchase/inbound cargo -> purchase; if evidencing a sale/outbound cargo -> sales)",
            "- Paperwork belonging to the finished aluminium desk (FA) or non-trade paperwork (approvals, internal trackers, informational notices) -> not_trade",
            "",
            "Report deal_direction as one of purchase, sales, not_trade, with deal_direction_confidence (between 0.0 and 1.0) and deal_direction_rationale (one clear sentence).",
            "",
            "Composite Document Rules:",
            "- Where a file is a composite packet containing multiple documents (for example an invoice followed by supporting contracts, cost sheets or bill of lading), classify it by the primary document presented on the opening pages (e.g. invoice if the leading document is an invoice).",
            "- A provisional, proforma or commercial invoice should be classified as invoice.",
            "",
            "Also report the territory the document belongs to (india, china, japan, other) when "
            "the language, addresses, forms or authorities make it clear, otherwise null.",
            "",
            "Then report `document_kinds`: every entry below that this one document genuinely "
            "evidences, on its own face. Most documents evidence exactly one; some evidence two, "
            "and a commercial invoice or a contract evidences none of them - return an empty "
            "list rather than the nearest guess.",
            "",
            KIND_GUIDE,
            "",
            "Report a kind only where the document itself carries what that kind is: a mill "
            "certificate that prints an elemental assay table on its face is both a mill test "
            "certificate and a chemical analysis certificate; one that merely says an assay was "
            "performed elsewhere is only the mill test certificate.",
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
            deal_direction=None,
            deal_direction_confidence=None,
            deal_direction_rationale=None,
        )

    direction = result.normalised_deal_direction()
    dir_conf = result.deal_direction_confidence
    dir_weak = (
        direction != DealDirection.NOT_TRADE.value and below_threshold(dir_conf)
    )

    return DocumentClassificationOutcome(
        document_type=result.document_type,
        confidence=result.confidence,
        rationale=result.rationale,
        territory=result.normalised_territory(),
        needs_review=below_threshold(result.confidence)
        or result.document_type == DocumentType.UNKNOWN.value
        or dir_weak,
        kinds=tuple(result.normalised_kinds()),
        deal_direction=direction,
        deal_direction_confidence=dir_conf,
        deal_direction_rationale=result.deal_direction_rationale,
    )


async def classify_deal_direction(
    *, filename: str, text: str, images: list[ImagePart] | None = None
) -> tuple[str, float | None, str | None]:
    """Evaluate the deal direction for a document."""
    outcome = await classify_document(filename=filename, text=text, images=images)
    return (
        outcome.deal_direction or DealDirection.NOT_TRADE.value,
        outcome.deal_direction_confidence,
        outcome.deal_direction_rationale,
    )

"""Schema-driven field extraction.

The field list for a document type is never written in this file. It is read from
`document_type_schemas`, selected by (document type, territory) with a fall-back to the
territory-agnostic row, and turned into both the model's response schema and its prompt. Adding
a field or a document type is a row change, not a code change.

Multi-page documents are read a window at a time. A value seen on more than one page is
consolidated by preferring the highest-confidence reading; two confident readings that disagree
are kept as a flagged conflict for a person to settle rather than silently resolved.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.models.configuration import DocumentTypeSchema
from app.services.gemini_service import (
    AIServiceError,
    ImagePart,
    generate_structured,
    wrap_source_data,
)
from app.services.text_extraction import DocumentContent, ExtractionRoute, normalise_text

logger = get_logger(__name__)

FIELD_TYPES = ("string", "number", "date", "currency", "quantity")


class SchemaNotConfiguredError(AppError):
    status_code = 409
    code = "schema_not_configured"
    message = "No extraction schema is configured for that document type."


class FieldValidationError(AppError):
    status_code = 422
    code = "field_invalid"
    message = "The value does not match the field's configured type."


@dataclass(frozen=True)
class SchemaField:
    name: str
    label: str
    type: str
    required: bool
    tolerance: float | None
    section: str
    description: str


@dataclass(frozen=True)
class ResolvedSchema:
    document_type: str
    territory: str | None
    fields: tuple[SchemaField, ...]
    mandatory_documents: tuple[str, ...]

    def field(self, name: str) -> SchemaField | None:
        return next((item for item in self.fields if item.name == name), None)


def _to_schema_field(raw: dict[str, Any]) -> SchemaField | None:
    name = str(raw.get("name") or "").strip()
    if not name:
        return None
    field_type = str(raw.get("type") or "string").strip().lower()
    tolerance = raw.get("tolerance")
    return SchemaField(
        name=name,
        label=str(raw.get("label") or name.replace("_", " ").capitalize()),
        type=field_type if field_type in FIELD_TYPES else "string",
        required=bool(raw.get("required")),
        tolerance=float(tolerance) if isinstance(tolerance, int | float) else None,
        section=str(raw.get("section") or "Extracted fields"),
        description=str(raw.get("description") or ""),
    )


def to_resolved_schema(row: DocumentTypeSchema) -> ResolvedSchema:
    raw_fields = (row.field_schema or {}).get("fields") or []
    fields = tuple(
        resolved
        for resolved in (_to_schema_field(item) for item in raw_fields if isinstance(item, dict))
        if resolved is not None
    )
    return ResolvedSchema(
        document_type=row.document_type,
        territory=row.territory,
        fields=fields,
        mandatory_documents=tuple(row.mandatory_documents or ()),
    )


async def select_schema(
    session: AsyncSession, *, document_type: str, territory: str | None
) -> ResolvedSchema:
    """Exact (type, territory) wins; the territory-agnostic row is the fall-back."""
    statement = select(DocumentTypeSchema).where(DocumentTypeSchema.document_type == document_type)
    if territory:
        # `IN (value, NULL)` never matches a NULL row, so the fall-back is spelled out.
        statement = statement.where(
            or_(
                DocumentTypeSchema.territory == territory,
                DocumentTypeSchema.territory.is_(None),
            )
        )
    else:
        statement = statement.where(DocumentTypeSchema.territory.is_(None))

    rows = (await session.scalars(statement)).all()
    if not rows:
        raise SchemaNotConfiguredError(
            f"No extraction schema is configured for document type '{document_type}'."
        )
    rows = sorted(rows, key=lambda row: 0 if row.territory == territory else 1)
    return to_resolved_schema(rows[0])


async def mandatory_documents_for(
    session: AsyncSession, *, document_type: str, territory: str | None
) -> tuple[str, ...]:
    """Read the stored completeness checklist. Step 3 is what enforces it."""
    try:
        schema = await select_schema(session, document_type=document_type, territory=territory)
    except SchemaNotConfiguredError:
        return ()
    return schema.mandatory_documents


class ExtractedValue(BaseModel):
    name: str
    value: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str | None = Field(default=None, max_length=400)
    page: int | None = None
    paragraph: int | None = None
    bbox: list[float] | None = None


class ExtractionResult(BaseModel):
    fields: list[ExtractedValue] = Field(default_factory=list)


def response_schema_for(schema: ResolvedSchema) -> dict[str, Any]:
    """Build the model's JSON response schema from the configured field list."""
    return {
        "type": "object",
        "properties": {
            "fields": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "enum": [f.name for f in schema.fields]},
                        "value": {"type": "string", "nullable": True},
                        "confidence": {"type": "number"},
                        "rationale": {"type": "string"},
                        "page": {"type": "integer", "nullable": True},
                        "paragraph": {"type": "integer", "nullable": True},
                        "bbox": {
                            "type": "array",
                            "nullable": True,
                            "items": {"type": "number"},
                        },
                    },
                    "required": ["name", "confidence"],
                },
            }
        },
        "required": ["fields"],
    }


def _field_brief(schema: ResolvedSchema) -> str:
    lines = []
    for item in schema.fields:
        requirement = "required" if item.required else "optional"
        description = f" - {item.description}" if item.description else ""
        lines.append(f"{item.name} ({item.type}, {requirement}){description}")
    return "\n".join(lines)


def _prompt(schema: ResolvedSchema, page_numbers: list[int], text: str, has_images: bool) -> str:
    pages = ", ".join(str(number) for number in page_numbers) or "1"
    header = "\n".join(
        [
            f"Read the following {schema.document_type} and report the fields listed below.",
            "",
            "Fields:",
            _field_brief(schema),
            "",
            "Rules:",
            "- Report every field in the list exactly once, using the field name given.",
            "- Return null for any field the source does not state, with a confidence at or "
            "below 0.2. Do not infer, do not calculate, do not carry a value over from a "
            "similar document.",
            "- Give a short rationale naming where on the page you read the value.",
            f"- Set `page` to the page the value was read from. Pages supplied here: {pages}.",
            "- Where the text layer is available, set `paragraph` to the paragraph ordinal shown "
            "in the source block; where you read from an image, set `bbox` to the value's "
            "bounding box as [x0, y0, x1, y1] in page coordinates.",
            "- Where the source is not written in the Latin alphabet, report reference numbers, "
            "quantities, dates and codes in a normalised comparable form: ASCII digits and "
            "letters, decimal point, no thousands separators, dates as YYYY-MM-DD. Keep a party "
            "or place name in its original script only when it has no Latin form on the "
            "document.",
            "- Numbers carry no currency symbol and no unit; a quantity keeps its unit "
            "(for example '24.500 MT').",
            "",
        ]
    )
    if has_images:
        header += "The page images attached below are the pages named above.\n\n"
    return header + wrap_source_data(f"{schema.document_type} pages {pages}", text, limit=40_000)


@dataclass
class ConsolidatedField:
    name: str
    value: str | None
    confidence: float
    rationale: str | None
    page: int | None
    source_reference: dict[str, Any] | None
    has_conflict: bool = False
    conflicting_values: list[str] = dataclass_field(default_factory=list)


def _comparable(value: str | None) -> str:
    return normalise_text(value or "").strip().casefold()


def consolidate(schema: ResolvedSchema, readings: list[ExtractedValue]) -> list[ConsolidatedField]:
    """Prefer the highest-confidence reading; flag a genuine disagreement rather than picking.

    Two readings disagree "genuinely" when both cleared the configured confidence threshold and
    their normalised values differ. A confident reading against a tentative one is not a
    conflict - the confident one simply wins.
    """
    threshold = settings.CONFIDENCE_THRESHOLD_DEFAULT
    by_name: dict[str, list[ExtractedValue]] = {}
    known = {item.name for item in schema.fields}
    for reading in readings:
        if reading.name in known:
            by_name.setdefault(reading.name, []).append(reading)

    consolidated: list[ConsolidatedField] = []
    for item in schema.fields:
        candidates = by_name.get(item.name, [])
        populated = [candidate for candidate in candidates if (candidate.value or "").strip() != ""]
        if not populated:
            consolidated.append(
                ConsolidatedField(
                    name=item.name,
                    value=None,
                    confidence=min((c.confidence for c in candidates), default=0.0),
                    rationale=next((c.rationale for c in candidates if c.rationale), None),
                    page=None,
                    source_reference=None,
                )
            )
            continue

        populated.sort(key=lambda candidate: candidate.confidence, reverse=True)
        best = populated[0]
        confident_values = {
            _comparable(candidate.value)
            for candidate in populated
            if candidate.confidence >= threshold
        }
        conflict = len(confident_values) > 1
        distinct = []
        for candidate in populated:
            rendered = (candidate.value or "").strip()
            if rendered and rendered not in distinct:
                distinct.append(rendered)

        consolidated.append(
            ConsolidatedField(
                name=item.name,
                value=(best.value or "").strip() or None,
                # A conflict cannot be presented as a confident answer, so the surviving score is
                # the weakest of the disagreeing readings.
                confidence=min(candidate.confidence for candidate in populated)
                if conflict
                else best.confidence,
                rationale=best.rationale,
                page=best.page,
                source_reference=_source_reference(best),
                has_conflict=conflict,
                conflicting_values=distinct if conflict else [],
            )
        )
    return consolidated


def _source_reference(reading: ExtractedValue) -> dict[str, Any] | None:
    reference: dict[str, Any] = {}
    if reading.paragraph is not None:
        reference["paragraph"] = reading.paragraph
    if reading.bbox and len(reading.bbox) == 4:
        reference["bbox"] = [round(float(value), 2) for value in reading.bbox]
    return reference or None


def _window_text(content: DocumentContent, window: list[int]) -> str:
    parts: list[str] = []
    for page in content.pages:
        if page.page_number not in window:
            continue
        parts.append(f"--- page {page.page_number} ---")
        if page.blocks:
            for block in page.blocks:
                parts.append(f"[paragraph {block.get('paragraph')}] {block.get('text', '')}")
        elif page.text:
            parts.append(page.text)
        else:
            parts.append("(no text layer on this page; read the attached page image)")
    return "\n".join(parts)


async def extract_fields(
    *, schema: ResolvedSchema, content: DocumentContent
) -> list[ConsolidatedField]:
    """Run the type-specific extraction across the document and consolidate the readings."""
    if not schema.fields:
        raise SchemaNotConfiguredError(
            f"The schema for '{schema.document_type}' declares no fields to extract."
        )

    window_size = max(1, settings.EXTRACTION_PAGE_WINDOW)
    pages = content.pages[: settings.EXTRACTION_MAX_PAGES]
    response_schema = response_schema_for(schema)
    readings: list[ExtractedValue] = []
    failures = 0

    for start in range(0, len(pages), window_size):
        window = pages[start : start + window_size]
        numbers = [page.page_number for page in window]
        images = [
            ImagePart(data=page.image, mime_type=page.image_mime)
            for page in window
            if page.image is not None
        ]
        text = _window_text(content, numbers)
        if not text.strip() and not images:
            continue

        try:
            result = await generate_structured(
                prompt=_prompt(schema, numbers, text, bool(images)),
                response_schema=response_schema,
                model=ExtractionResult,
                images=images or None,
                purpose="field_extraction",
            )
        except AIServiceError:
            failures += 1
            continue

        for reading in result.fields:
            if reading.page is None and len(numbers) == 1:
                reading = reading.model_copy(update={"page": numbers[0]})
            readings.append(reading)

    if not readings:
        raise AIServiceError(reason="no_usable_extraction")
    if failures:
        logger.warning(
            "extraction_window_failures",
            extra={"document_type": schema.document_type, "failed_windows": failures},
        )
    return consolidate(schema, readings)


def validate_field_value(schema_field: SchemaField, value: str | None) -> str | None:
    """Validate a human correction against the field's configured type."""
    cleaned = None if value is None else (normalise_text(value).strip() or None)

    if cleaned is None:
        if schema_field.required:
            raise FieldValidationError(f"{schema_field.label} is required and cannot be cleared.")
        return None

    if schema_field.type in ("number", "currency"):
        try:
            Decimal(cleaned.replace(",", ""))
        except (InvalidOperation, ValueError) as exc:
            raise FieldValidationError(f"{schema_field.label} must be a number.") from exc
        return cleaned.replace(",", "")

    if schema_field.type == "quantity":
        head = cleaned.split()[0].replace(",", "")
        try:
            Decimal(head)
        except (InvalidOperation, ValueError) as exc:
            raise FieldValidationError(
                f"{schema_field.label} must start with a number, optionally followed by a unit."
            ) from exc
        return cleaned

    if schema_field.type == "date":
        return _normalise_date(schema_field, cleaned)

    return cleaned


_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d %b %Y", "%d %B %Y", "%Y/%m/%d")


def _normalise_date(schema_field: SchemaField, value: str) -> str:
    for fmt in _DATE_FORMATS:
        try:
            parsed: date = datetime.strptime(value, fmt).date()
        except ValueError:
            continue
        return parsed.isoformat()
    raise FieldValidationError(
        f"{schema_field.label} must be a date, for example 2026-08-23 or 23/08/2026."
    )


def route_label(content: DocumentContent) -> str:
    """The path a document actually took, surfaced for the review screen and the logs."""
    return content.route.value if isinstance(content.route, ExtractionRoute) else str(content.route)

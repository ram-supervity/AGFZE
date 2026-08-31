"""Orchestration: classify a request, then classify and extract each of its documents.

This is the first real consumer of the Step 1 background-job service, and it reuses it exactly
as built - `create_job` / `update_job_progress` / `complete_job` / `fail_job`, polled by the
frontend through the existing `GET /jobs/{job_id}/status`. There is no parallel mechanism.

A single-document request runs as a lightweight in-process task; a multi-document pack runs
through the same tracked-job pattern, only with per-document progress reported as it goes.
"""

from __future__ import annotations

import asyncio
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.base import utcnow
from app.db.session import AsyncSessionLocal
from app.models.enums import DocumentType, ExtractionStatus, RequestStatus
from app.models.intake import Document, ExtractedField, Request
from app.services import classification_service, extraction_service, job_service
from app.services.audit_service import ActorType, record_audit_event
from app.services.file_intake import IMAGE, PDF, detect_type, storage_key
from app.services.gemini_service import AIServiceError, ImagePart
from app.services.governance import hooks as governance_hooks
from app.services.storage import get_storage_service
from app.services.text_extraction import (
    DocumentContent,
    ExtractionRoute,
    read_document,
    render_document_preview_pages,
    render_pdf_pages,
)

logger = get_logger(__name__)

JOB_TYPE_INTAKE = "intake.request.process"
JOB_TYPE_REEXTRACT = "intake.document.reextract"


class AuditEvent:
    REQUEST_CLASSIFIED = "request.classified"
    REQUEST_CATEGORY_OVERRIDDEN = "request.category_overridden"
    DOCUMENT_CLASSIFIED = "document.classified"
    DOCUMENT_RECLASSIFIED = "document.reclassified"
    DOCUMENT_EXTRACTED = "document.extracted"
    DOCUMENT_EXTRACTION_FAILED = "document.extraction_failed"
    DOCUMENT_FIELD_OVERRIDDEN = "document.field_overridden"
    DOCUMENT_CONFIRMED = "document.extraction_confirmed"
    DOCUMENT_UPLOADED = "document.uploaded"
    EMAIL_INGESTED = "email.ingested"


async def classify_request_row(session: AsyncSession, request: Request) -> None:
    """Assign the business category, or mark the request for a person to decide."""
    email = request.email_message
    outcome = await classification_service.classify_request(
        subject=email.subject if email else None,
        body=email.body_text if email else None,
        sender=email.sender_address if email else None,
    )

    request.category = outcome.category
    request.category_confidence = outcome.confidence
    request.category_rationale = outcome.rationale
    request.needs_review = outcome.needs_review
    request.classification_error = outcome.error
    if request.original_category is None:
        request.original_category = outcome.category
    if outcome.stream and not request.stream:
        request.stream = outcome.stream
        request.original_stream = outcome.stream
    request.status = RequestStatus.CLASSIFIED.value
    request.updated_at = utcnow()

    await record_audit_event(
        session,
        event_type=AuditEvent.REQUEST_CLASSIFIED,
        entity_type="request",
        entity_id=request.id,
        actor_type=ActorType.AGENT,
        metadata={
            "category": outcome.category,
            "confidence": outcome.confidence,
            "stream": outcome.stream,
            "needs_review": outcome.needs_review,
            "error": outcome.error,
        },
    )


async def _load_content(document: Document, data: bytes) -> DocumentContent:
    content_type, family = detect_type(data, document.filename)
    return read_document(data, family=family, content_type=content_type)


async def _persist_page_images(document: Document, content: DocumentContent, data: bytes) -> None:
    """Store the page images once and reuse them as the review viewer's pages.

    Generates page preview images for all supported file types (PDF, images, DOCX, spreadsheets).
    """
    if document.page_image_refs:
        return

    storage = get_storage_service()
    images: list[tuple[bytes, str]] = []
    if content.route is ExtractionRoute.MULTIMODAL:
        images = [(page.image, page.image_mime) for page in content.pages if page.image is not None]

    if not images:
        rendered_pages = render_document_preview_pages(
            document.filename, content, settings.PAGE_RASTER_DPI
        )
        images = [(rendered, "image/png") for rendered in rendered_pages]

    refs: list[str] = []
    for index, (payload, mime) in enumerate(images, start=1):
        suffix = "png" if mime == "image/png" else "jpg"
        key = f"documents/{document.id}/pages/{index:04d}.{suffix}"
        await storage.upload(key, payload, mime)
        refs.append(key)
    document.page_image_refs = refs
    if len(refs) > document.page_count:
        document.page_count = len(refs)


async def _write_fields(session: AsyncSession, document: Document, consolidated: list) -> None:
    """Replace the machine reading of a document, preserving any value a person already fixed."""
    existing = {
        row.field_name: row
        for row in (
            await session.scalars(
                select(ExtractedField).where(ExtractedField.document_id == document.id)
            )
        ).all()
    }

    seen: set[str] = set()
    for item in consolidated:
        seen.add(item.name)
        row = existing.get(item.name)
        if row is None:
            row = ExtractedField(document_id=document.id, field_name=item.name)
            session.add(row)
            row.original_ai_value = item.value
            row.original_confidence = item.confidence
        elif row.is_overridden:
            # A human decision outranks a re-run; only the evidence around it is refreshed.
            row.source_page = item.page
            row.source_reference = item.source_reference
            row.has_conflict = item.has_conflict
            row.conflicting_values = item.conflicting_values
            continue
        else:
            # The original AI value is written once, on the first extraction, and never again.
            if row.original_ai_value is None and row.original_confidence is None:
                row.original_ai_value = item.value
                row.original_confidence = item.confidence

        row.field_value = item.value
        row.confidence = item.confidence
        row.rationale = item.rationale
        row.source_page = item.page
        row.source_reference = item.source_reference
        row.has_conflict = item.has_conflict
        row.conflicting_values = item.conflicting_values

    for name, row in existing.items():
        # A field dropped from the schema, or absent from a re-run against a new type: an
        # untouched machine reading goes, a human's correction stays on the record.
        if name not in seen and not row.is_overridden:
            await session.delete(row)


async def process_document(
    session: AsyncSession,
    document: Document,
    *,
    classify: bool = True,
) -> None:
    """Classify (optionally) and extract one document. Failure is recorded, never raised up."""
    document.extraction_status = ExtractionStatus.PROCESSING.value
    document.extraction_error = None
    await session.flush()

    storage = get_storage_service()
    try:
        data = await storage.download(document.storage_ref)
        content = await _load_content(document, data)
    except Exception as exc:
        logger.exception("document_read_failed", extra={"document_id": str(document.id)})
        document.extraction_status = ExtractionStatus.FAILED.value
        document.extraction_error = "The document could not be read."
        document.needs_review = True
        await record_audit_event(
            session,
            event_type=AuditEvent.DOCUMENT_EXTRACTION_FAILED,
            entity_type="document",
            entity_id=document.id,
            actor_type=ActorType.AGENT,
            metadata={"stage": "read", "reason": type(exc).__name__},
        )
        return

    document.page_count = content.page_count
    await _persist_page_images(document, content, data)

    if classify:
        images = [
            ImagePart(data=page.image, mime_type=page.image_mime)
            for page in content.pages[:2]
            if page.image is not None
        ]
        outcome = await classification_service.classify_document(
            filename=document.filename,
            text=content.full_text[:20_000],
            images=images or None,
        )
        chosen = outcome.document_type
        # An explicit human hint at upload time outranks a model guess it does not agree with.
        if document.document_type_hint and outcome.needs_review:
            chosen = document.document_type_hint
        document.document_type = chosen
        document.classification_confidence = outcome.confidence
        document.classification_rationale = outcome.rationale
        document.territory = document.territory or outcome.territory
        document.needs_review = outcome.needs_review
        # A kind a person set by hand outranks a re-run, exactly as a corrected field value does.
        if not document.kinds_overridden:
            document.document_kinds = list(outcome.kinds)
        if document.original_document_type is None:
            document.original_document_type = outcome.document_type

        await record_audit_event(
            session,
            event_type=AuditEvent.DOCUMENT_CLASSIFIED,
            entity_type="document",
            entity_id=document.id,
            actor_type=ActorType.AGENT,
            metadata={
                "document_type": chosen,
                "document_kinds": list(document.document_kinds or ()),
                "confidence": outcome.confidence,
                "territory": document.territory,
                "route": content.route.value,
                "error": outcome.error,
            },
        )

    document_type = document.document_type or DocumentType.UNKNOWN.value
    if document_type == DocumentType.UNKNOWN.value:
        document.extraction_status = ExtractionStatus.FAILED.value
        document.extraction_error = (
            "The document type could not be identified, so no field schema applies. "
            "Reclassify it to extract its fields."
        )
        document.needs_review = True
        return

    try:
        schema = await extraction_service.select_schema(
            session, document_type=document_type, territory=document.territory
        )
        consolidated = await extraction_service.extract_fields(schema=schema, content=content)
    except extraction_service.SchemaNotConfiguredError as exc:
        document.extraction_status = ExtractionStatus.FAILED.value
        document.extraction_error = exc.message
        document.needs_review = True
        return
    except AIServiceError as exc:
        logger.warning(
            "document_extraction_failed",
            extra={"document_id": str(document.id), "reason": exc.reason},
        )
        document.extraction_status = ExtractionStatus.FAILED.value
        document.extraction_error = (
            "The extraction service could not read this document. It needs a human review."
        )
        document.needs_review = True
        await record_audit_event(
            session,
            event_type=AuditEvent.DOCUMENT_EXTRACTION_FAILED,
            entity_type="document",
            entity_id=document.id,
            actor_type=ActorType.AGENT,
            metadata={"stage": "extract", "reason": exc.reason},
        )
        return

    await _write_fields(session, document, consolidated)
    document.extraction_status = ExtractionStatus.COMPLETED.value

    threshold = settings.CONFIDENCE_THRESHOLD_DEFAULT
    doubtful = [item for item in consolidated if item.has_conflict or item.confidence < threshold]
    document.needs_review = document.needs_review or bool(doubtful)

    # The inline flag above stays exactly where it was: it is what makes a doubtful value obvious
    # to somebody already looking at the document. This opens the owned, ageing case behind it,
    # for the far more common situation where nobody is.
    await _raise_low_confidence_case(session, document, threshold, doubtful)

    await record_audit_event(
        session,
        event_type=AuditEvent.DOCUMENT_EXTRACTED,
        entity_type="document",
        entity_id=document.id,
        actor_type=ActorType.AGENT,
        metadata={
            "document_type": document_type,
            "territory": document.territory,
            "field_count": len(consolidated),
            "conflict_count": sum(1 for item in consolidated if item.has_conflict),
            "route": content.route.value,
        },
    )


async def _raise_low_confidence_case(
    session: AsyncSession,
    document: Document,
    threshold: float,
    doubtful: list,
) -> None:
    """Open a low-confidence exception where the classification or a field fell short.

    Idempotent through the hook: re-extracting a document that is still doubtful does not stack a
    second case on top of the first.
    """
    classification = document.classification_confidence
    weak_classification = classification is not None and classification < threshold
    if not doubtful and not weak_classification:
        return

    scores = [item.confidence for item in doubtful if item.confidence is not None]
    if weak_classification and classification is not None:
        scores.append(classification)

    await governance_hooks.record_low_confidence(
        session,
        document,
        threshold=threshold,
        lowest_confidence=min(scores) if scores else None,
        field_names=[item.name for item in doubtful],
    )


async def process_request(
    session: AsyncSession,
    request_id: UUID,
    job_id: UUID | None,
    *,
    classify_request: bool = True,
) -> None:
    """The whole intake pipeline for one request, reporting progress through the job row.

    `classify_request` is off when the documents were attached straight onto a known transaction:
    the category is settled by construction, and asking the model to guess it again would be
    inventing a decision nobody needs. Per-document type classification and extraction still run.
    """
    request = await session.get(Request, request_id)
    if request is None:
        if job_id:
            await job_service.fail_job(session, job_id, error_message="Request no longer exists.")
            await session.commit()
        return

    try:
        if job_id:
            await job_service.update_job_progress(session, job_id, 5)
        if classify_request:
            await classify_request_row(session, request)
        else:
            request.status = RequestStatus.CLASSIFIED.value
            request.updated_at = utcnow()
        await session.commit()

        documents = (
            await session.scalars(select(Document).where(Document.request_id == request_id))
        ).all()

        request.status = RequestStatus.EXTRACTION_PENDING.value
        request.updated_at = utcnow()
        await session.commit()

        total = len(documents)
        for index, document in enumerate(documents, start=1):
            await process_document(session, document)
            await session.commit()
            if job_id:
                await job_service.update_job_progress(
                    session, job_id, 10 + int(85 * index / max(total, 1))
                )
                await session.commit()

        request.status = RequestStatus.EXTRACTED.value
        request.needs_review = request.needs_review or any(
            document.needs_review for document in documents
        )
        request.updated_at = utcnow()
        await session.commit()

        if job_id:
            await job_service.complete_job(session, job_id, result_ref=f"request:{request_id}")
            await session.commit()
    except Exception:
        logger.exception("intake_pipeline_failed", extra={"request_id": str(request_id)})
        await session.rollback()
        if job_id:
            await job_service.fail_job(
                session, job_id, error_message="Intake processing did not complete."
            )
            await session.commit()
        raise


async def _run_in_background(
    request_id: UUID, job_id: UUID | None, *, classify_request: bool = True
) -> None:
    """Own session, own lifetime: the HTTP request that queued the work is long gone."""
    async with AsyncSessionLocal() as session:
        try:
            await process_request(session, request_id, job_id, classify_request=classify_request)
        except Exception:
            logger.exception("background_intake_failed", extra={"request_id": str(request_id)})


async def queue_request_processing(
    session: AsyncSession,
    request_id: UUID,
    *,
    created_by_id: UUID | None = None,
    classify_request: bool = True,
) -> UUID:
    """Create the tracked job and start the pipeline. Returns the job id the client polls."""
    job = await job_service.create_job(
        session, job_type=JOB_TYPE_INTAKE, created_by_id=created_by_id
    )
    await session.commit()
    task = asyncio.create_task(
        _run_in_background(request_id, job.id, classify_request=classify_request)
    )
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)
    return job.id


async def _reextract_in_background(document_id: UUID, job_id: UUID) -> None:
    async with AsyncSessionLocal() as session:
        try:
            document = await session.get(Document, document_id)
            if document is None:
                await job_service.fail_job(
                    session, job_id, error_message="Document no longer exists."
                )
                await session.commit()
                return
            await job_service.update_job_progress(session, job_id, 20)
            await session.commit()
            await process_document(session, document, classify=False)
            await session.commit()
            await job_service.complete_job(session, job_id, result_ref=f"document:{document_id}")
            await session.commit()
        except Exception:
            logger.exception("reextraction_failed", extra={"document_id": str(document_id)})
            await session.rollback()
            await job_service.fail_job(
                session, job_id, error_message="Re-extraction did not complete."
            )
            await session.commit()


async def queue_reextraction(
    session: AsyncSession, document_id: UUID, *, created_by_id: UUID | None
) -> UUID:
    job = await job_service.create_job(
        session, job_type=JOB_TYPE_REEXTRACT, created_by_id=created_by_id
    )
    await session.commit()
    task = asyncio.create_task(_reextract_in_background(document_id, job.id))
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)
    return job.id


# Strong references so a running pipeline is not collected mid-flight.
_BACKGROUND_TASKS: set[asyncio.Task] = set()


def new_document_storage_key(filename: str) -> str:
    return storage_key("documents/source", filename)

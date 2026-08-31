"""Manual intake, the document index, the review detail, corrections and confirmation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.dependencies import CurrentUser, DbSession, require_roles
from app.core.errors import AppError, BadRequestError, ConflictError, NotFoundError
from app.core.roles import PlatformRole
from app.db.base import utcnow
from app.models.enums import (
    BUSINESS_STREAMS,
    DOCUMENT_TYPES,
    EXTRACTION_STATUSES,
    TERRITORIES,
    DocumentSource,
    DocumentType,
    ExtractionStatus,
    MatchMethod,
    RequestCategory,
    RequestSource,
    RequestStatus,
)
from app.models.identity import User
from app.models.intake import Document, ExtractedField, Request
from app.models.transactions import TradeTransaction
from app.schemas.common import ResponseEnvelope
from app.schemas.document import (
    ConfirmationResult,
    DocumentDetail,
    DocumentList,
    DocumentListItem,
    ExtractedFieldRead,
    FieldCorrectionRequest,
    FieldSchemaRead,
    PurchaseBundleItemRead,
    PurchaseBundleRead,
    ReclassifyAccepted,
    ReclassifyRequest,
)
from app.schemas.intake import Page, UploadAccepted
from app.schemas.transaction import MatchCandidateRead, MatchOutcomeRead, MatchResolution
from app.services import (
    document_service,
    draft_service,
    extraction_service,
    matching_service,
    purchase_completion,
    purchase_intake,
    request_service,
    sales_service,
    transaction_service,
)
from app.services.audit_service import ActorType, record_audit_event
from app.services.file_intake import inspect_bytes, read_within_limit
from app.services.storage import get_storage_service

router = APIRouter(prefix="/documents", tags=["documents"])

CorrectionUser = Annotated[
    User,
    Depends(
        require_roles(
            PlatformRole.PURCHASE_USER.value,
            PlatformRole.SALES_USER.value,
            PlatformRole.FA_USER.value,
            PlatformRole.LOGISTICS_USER.value,
            PlatformRole.ADMIN.value,
        )
    ),
]

# Resolving an ambiguous match creates or attaches a transaction, so it is the purchase desk's
# decision and the admin's, not every correcting role's.
MatchResolutionUser = Annotated[
    User,
    Depends(require_roles(PlatformRole.PURCHASE_USER.value, PlatformRole.ADMIN.value)),
]

MAX_UPLOAD_FILES = 20


def _baseline_confidence(row: ExtractedField) -> float | None:
    """What the machine scored first. A correction is judged against that, not the value shown."""
    return row.original_confidence if row.original_confidence is not None else row.confidence


async def _signed(key: str | None) -> str | None:
    return await get_storage_service().get_signed_url(key) if key else None


async def _load(session: DbSession, document_id: UUID) -> Document:
    document = await session.scalar(
        select(Document)
        .where(Document.id == document_id)
        .options(selectinload(Document.fields), selectinload(Document.request))
    )
    if document is None:
        raise NotFoundError("Document not found.")
    return document


@router.post(
    "/upload",
    response_model=ResponseEnvelope[UploadAccepted],
    status_code=202,
    summary="Manual document intake",
)
async def upload_documents(
    user: CorrectionUser,
    session: DbSession,
    files: list[UploadFile] = File(...),
    stream: str = Form(...),
    document_type_hint: str | None = Form(None),
    transaction_id: UUID | None = Form(None),
) -> ResponseEnvelope[UploadAccepted]:
    if stream not in BUSINESS_STREAMS:
        raise BadRequestError(
            f"Stream must be one of: {', '.join(BUSINESS_STREAMS)}",
            code="invalid_stream",
        )
    if document_type_hint and document_type_hint not in DOCUMENT_TYPES:
        raise BadRequestError(
            "That document type hint is not recognised.", code="invalid_document_type"
        )
    if not files:
        raise BadRequestError("Attach at least one file.", code="no_files")
    if len(files) > MAX_UPLOAD_FILES:
        raise BadRequestError(
            f"Upload at most {MAX_UPLOAD_FILES} files at a time.", code="too_many_files"
        )

    # Attaching straight onto a known transaction: the target is settled by construction, so
    # request-level category classification and the ambiguous-match flow are both skipped. Type
    # classification and field extraction still run in full - a document filed by hand deserves
    # the same confidence-scored, reviewable extraction as one that arrived by email.
    target: TradeTransaction | None = None
    if transaction_id is not None:
        target = await session.scalar(
            transaction_service.apply_visibility(
                select(TradeTransaction).where(TradeTransaction.id == transaction_id), user
            )
        )
        if target is None:
            raise NotFoundError("Transaction not found.")
        if target.status == "approval_pending":
            raise ConflictError(
                "This transaction is awaiting approval; no further documents can be attached."
            )
        stream = target.stream

    storage = get_storage_service()
    accepted: list[tuple[str, bytes, str, str, str]] = []
    rejected: list[dict[str, str]] = []

    for upload in files:
        try:
            # Streamed, chunk by chunk, with the limit applied to the running total: an oversized
            # body is refused before it has ever been fully buffered.
            data = await read_within_limit(upload)
            # The client's filename and content-type are display metadata only. The whitelist
            # decision is made here, on the real leading bytes.
            inspected = inspect_bytes(upload.filename or "attachment", data)
        except AppError as exc:
            rejected.append({"filename": upload.filename or "attachment", "reason": exc.message})
            continue
        finally:
            await upload.close()
        accepted.append(
            (
                inspected.filename,
                inspected.data,
                inspected.content_type,
                inspected.content_hash,
                str(inspected.byte_size),
            )
        )

    if not accepted:
        raise BadRequestError(
            "None of the supplied files could be accepted.",
            code="no_acceptable_files",
            errors=[
                {"code": "rejected_file", "message": item["reason"], "field": item["filename"]}
                for item in rejected
            ],
        )

    request = await request_service.create_request(
        session, source=RequestSource.PORTAL, created_by_id=user.id, stream=stream
    )
    if target is not None:
        # The category is settled by construction rather than classified, and which one it is
        # follows the document being filed: a bill of lading attached to a batch is sales-side
        # work, and typing it as a purchase would send it down the wrong matching path.
        category = (
            RequestCategory.SALES.value
            if document_type_hint in sales_service.SALES_TRIGGER_DOCUMENT_TYPES
            else RequestCategory.PURCHASE.value
        )
        request.category = category
        request.original_category = request.original_category or category

    document_ids: list[UUID] = []
    for filename, data, content_type, content_hash, byte_size in accepted:
        key = document_service.new_document_storage_key(filename)
        await storage.upload(key, data, content_type)
        document = Document(
            request_id=request.id,
            filename=filename,
            content_type=content_type,
            byte_size=int(byte_size),
            storage_ref=key,
            content_hash=content_hash,
            document_type_hint=document_type_hint,
            source=DocumentSource.UPLOADED.value,
            uploaded_by_id=user.id,
            transaction_id=target.id if target is not None else None,
        )
        session.add(document)
        await session.flush()
        document_ids.append(document.id)

    await record_audit_event(
        session,
        event_type=document_service.AuditEvent.DOCUMENT_UPLOADED,
        entity_type="request",
        entity_id=request.id,
        actor_id=user.id,
        actor_type=ActorType.USER,
        metadata={
            "request_code": request.request_code,
            "stream": stream,
            "document_type_hint": document_type_hint,
            "accepted_count": len(document_ids),
            "rejected_count": len(rejected),
            "transaction_id": str(target.id) if target is not None else None,
        },
    )
    await session.commit()

    job_id = await document_service.queue_request_processing(
        session,
        request.id,
        created_by_id=user.id,
        classify_request=target is None,
    )

    return ResponseEnvelope[UploadAccepted](
        data=UploadAccepted(
            request_id=request.id,
            request_code=request.request_code,
            job_id=job_id,
            document_ids=document_ids,
            rejected=rejected,
        ),
        message=(
            f"Upload accepted onto batch {target.batch_number}. Extraction is running."
            if target is not None
            else "Upload accepted. Classification and extraction are running."
        ),
    )


def _index_query(
    *,
    search: str | None,
    document_type: str | None,
    status: str | None,
    territory: str | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> Select[tuple[Document]]:
    statement = select(Document)
    if document_type:
        statement = statement.where(Document.document_type == document_type)
    if status:
        statement = statement.where(Document.extraction_status == status)
    if territory:
        statement = statement.where(Document.territory == territory)
    if date_from:
        statement = statement.where(Document.created_at >= date_from)
    if date_to:
        statement = statement.where(Document.created_at <= date_to)
    if search:
        term = f"%{search.strip().lower()}%"
        statement = (
            statement.join(Request, Document.request_id == Request.id)
            .outerjoin(ExtractedField, ExtractedField.document_id == Document.id)
            .where(
                or_(
                    func.lower(Document.filename).like(term),
                    func.lower(Request.request_code).like(term),
                    func.lower(func.coalesce(ExtractedField.field_value, "")).like(term),
                )
            )
            .distinct()
        )
    return statement


@router.get(
    "",
    response_model=ResponseEnvelope[DocumentList],
    summary="Searchable document index",
)
async def list_documents(
    user: CurrentUser,
    session: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    search: str | None = Query(None, max_length=200),
    document_type: str | None = Query(None),
    status: str | None = Query(None),
    territory: str | None = Query(None),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
) -> ResponseEnvelope[DocumentList]:
    if document_type and document_type not in DOCUMENT_TYPES:
        document_type = None
    if status and status not in EXTRACTION_STATUSES:
        status = None
    if territory and territory not in TERRITORIES:
        territory = None

    statement = _index_query(
        search=search,
        document_type=document_type,
        status=status,
        territory=territory,
        date_from=date_from,
        date_to=date_to,
    )
    total = await request_service.count_query(session, statement)

    rows = (
        await session.scalars(
            statement.options(selectinload(Document.request))
            .order_by(Document.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()

    items: list[DocumentListItem] = []
    for row in rows:
        item = DocumentListItem.model_validate(row)
        item.request_code = row.request.request_code if row.request else None
        item.thumbnail_url = await _signed((row.page_image_refs or [None])[0])
        items.append(item)

    return ResponseEnvelope[DocumentList](
        data=DocumentList(
            items=items,
            page=Page(
                page=page,
                page_size=page_size,
                total=total,
                total_pages=max(1, -(-total // page_size)),
            ),
        )
    )


async def _detail(session: DbSession, document: Document) -> DocumentDetail:
    detail = DocumentDetail.model_validate(document)
    detail.request_code = document.request.request_code if document.request else None
    detail.source_url = await _signed(document.storage_ref)
    detail.page_image_urls = [
        url
        for url in [await _signed(ref) for ref in (document.page_image_refs or [])]
        if url is not None
    ]
    detail.confidence_threshold = settings.CONFIDENCE_THRESHOLD_DEFAULT

    schema_fields: dict[str, extraction_service.SchemaField] = {}
    if document.document_type and document.document_type != DocumentType.UNKNOWN.value:
        try:
            schema = await extraction_service.select_schema(
                session, document_type=document.document_type, territory=document.territory
            )
        except extraction_service.SchemaNotConfiguredError:
            schema = None
        if schema is not None:
            schema_fields = {item.name: item for item in schema.fields}
            detail.mandatory_documents = list(schema.mandatory_documents)
            detail.schema_fields = [
                FieldSchemaRead(
                    name=item.name,
                    label=item.label,
                    type=item.type,
                    required=item.required,
                    tolerance=item.tolerance,
                    section=item.section,
                    description=item.description,
                )
                for item in schema.fields
            ]

    order = {name: index for index, name in enumerate(schema_fields)}
    rows = sorted(
        document.fields, key=lambda row: (order.get(row.field_name, 10_000), row.field_name)
    )

    fields: list[ExtractedFieldRead] = []
    for row in rows:
        read = ExtractedFieldRead.model_validate(row)
        configured = schema_fields.get(row.field_name)
        if configured is not None:
            read.label = configured.label
            read.type = configured.type
            read.required = configured.required
            read.section = configured.section
        else:
            read.label = row.field_name.replace("_", " ").capitalize()
        # The gate is decided by what the machine originally scored, not by the value on screen:
        # correcting a field the AI was unsure about is what needs a reason on the record.
        baseline = _baseline_confidence(row)
        read.reason_required = baseline is None or baseline < settings.CONFIDENCE_THRESHOLD_DEFAULT
        read.overridden_by_name = row.overridden_by.display_name if row.overridden_by else None
        fields.append(read)

    detail.fields = fields
    detail.uploaded_by_name = None
    detail.confirmed_by_name = None
    if document.uploaded_by_id or document.confirmed_by_id:
        names = dict(
            (
                await session.execute(
                    select(User.id, User.display_name).where(
                        User.id.in_(
                            [
                                identifier
                                for identifier in (
                                    document.uploaded_by_id,
                                    document.confirmed_by_id,
                                )
                                if identifier is not None
                            ]
                        )
                    )
                )
            ).all()
        )
        detail.uploaded_by_name = names.get(document.uploaded_by_id)
        detail.confirmed_by_name = names.get(document.confirmed_by_id)
    return detail


@router.get(
    "/{document_id}",
    response_model=ResponseEnvelope[DocumentDetail],
    summary="Full extraction detail with signed page images",
)
async def read_document(
    document_id: UUID,
    user: CurrentUser,
    session: DbSession,
) -> ResponseEnvelope[DocumentDetail]:
    document = await _load(session, document_id)
    return ResponseEnvelope[DocumentDetail](data=await _detail(session, document))


@router.patch(
    "/{document_id}/fields",
    response_model=ResponseEnvelope[DocumentDetail],
    summary="Correct extracted field values",
)
async def correct_fields(
    document_id: UUID,
    payload: FieldCorrectionRequest,
    user: CorrectionUser,
    session: DbSession,
) -> ResponseEnvelope[DocumentDetail]:
    document = await _load(session, document_id)
    if not document.document_type or document.document_type == DocumentType.UNKNOWN.value:
        raise ConflictError("Classify the document before correcting its fields.")

    schema = await extraction_service.select_schema(
        session, document_type=document.document_type, territory=document.territory
    )
    rows = {row.field_name: row for row in document.fields}
    threshold = settings.CONFIDENCE_THRESHOLD_DEFAULT
    changes: list[dict[str, object]] = []

    for correction in payload.corrections:
        configured = schema.field(correction.field_name)
        if configured is None:
            raise BadRequestError(
                f"'{correction.field_name}' is not a field of this document type.",
                code="unknown_field",
            )
        row = rows.get(correction.field_name)
        if row is None:
            row = ExtractedField(document_id=document.id, field_name=correction.field_name)
            session.add(row)
            rows[correction.field_name] = row

        value = extraction_service.validate_field_value(configured, correction.value)
        baseline = _baseline_confidence(row)
        reason_required = baseline is None or baseline < threshold
        reason = (correction.reason or "").strip()
        if reason_required and len(reason) < 5:
            raise BadRequestError(
                f"{configured.label} was extracted below the confidence threshold, so a reason "
                "of at least 5 characters is required for the correction.",
                code="reason_required",
                errors=[
                    {
                        "code": "reason_required",
                        "message": "Give a reason for this correction.",
                        "field": correction.field_name,
                    }
                ],
            )

        previous = row.field_value
        if previous == value and row.is_overridden:
            continue

        # The AI's value is captured the first time a row is touched and kept for good.
        if row.original_ai_value is None and not row.is_overridden:
            row.original_ai_value = previous
            row.original_confidence = row.confidence

        row.field_value = value
        row.is_overridden = True
        row.override_reason = reason or None
        row.overridden_by_id = user.id
        row.overridden_at = utcnow()
        row.has_conflict = False
        row.conflicting_values = []
        changes.append(
            {
                "field_name": correction.field_name,
                "previous_value": previous,
                "new_value": value,
                "original_ai_value": row.original_ai_value,
                "original_confidence": row.original_confidence,
                "reason_required": reason_required,
                "reason": reason or None,
            }
        )

    if changes:
        await record_audit_event(
            session,
            event_type=document_service.AuditEvent.DOCUMENT_FIELD_OVERRIDDEN,
            entity_type="document",
            entity_id=document.id,
            actor_id=user.id,
            actor_type=ActorType.USER,
            metadata={"document_type": document.document_type, "changes": changes},
        )
    await session.commit()

    refreshed = await _load(session, document_id)
    return ResponseEnvelope[DocumentDetail](data=await _detail(session, refreshed))


@router.post(
    "/{document_id}/reclassify",
    response_model=ResponseEnvelope[ReclassifyAccepted],
    status_code=202,
    summary="Reclassify a document and re-run extraction against the new type's schema",
)
async def reclassify_document(
    document_id: UUID,
    payload: ReclassifyRequest,
    user: CorrectionUser,
    session: DbSession,
) -> ResponseEnvelope[ReclassifyAccepted]:
    document = await _load(session, document_id)
    previous_type = document.document_type
    previous_territory = document.territory
    previous_direction = document.deal_direction

    if document.original_document_type is None:
        document.original_document_type = previous_type
    previous_kinds = list(document.document_kinds or ())
    document.document_type = payload.document_type
    if payload.territory is not None:
        document.territory = payload.territory
    if payload.deal_direction is not None:
        document.deal_direction = payload.deal_direction
    if payload.document_kinds is not None:
        # BR-04 reads this list, so a correction here is a correction to whether the pack is
        # complete. It is recorded as a human's and survives the re-extraction queued below.
        document.document_kinds = payload.document_kinds
        document.kinds_overridden = True
    document.extraction_status = ExtractionStatus.PENDING.value
    document.extraction_error = None
    document.confirmed_at = None
    document.confirmed_by_id = None

    await record_audit_event(
        session,
        event_type=document_service.AuditEvent.DOCUMENT_RECLASSIFIED,
        entity_type="document",
        entity_id=document.id,
        actor_id=user.id,
        actor_type=ActorType.USER,
        metadata={
            "previous_document_type": previous_type,
            "new_document_type": payload.document_type,
            "previous_territory": previous_territory,
            "new_territory": document.territory,
            "previous_deal_direction": previous_direction,
            "new_deal_direction": document.deal_direction,
            "previous_document_kinds": previous_kinds,
            "new_document_kinds": list(document.document_kinds or ()),
            "original_ai_document_type": document.original_document_type,
            "reason": payload.reason,
        },
    )
    await session.commit()

    job_id = await document_service.queue_reextraction(session, document.id, created_by_id=user.id)
    return ResponseEnvelope[ReclassifyAccepted](
        data=ReclassifyAccepted(document_id=document.id, job_id=job_id),
        message="Re-extraction queued against the new document type's schema.",
    )


@router.post(
    "/{document_id}/confirm",
    response_model=ResponseEnvelope[ConfirmationResult],
    summary="Confirm the extraction",
)
async def confirm_extraction(
    document_id: UUID,
    user: CorrectionUser,
    session: DbSession,
) -> ResponseEnvelope[ConfirmationResult]:
    document = await _load(session, document_id)
    if document.extraction_status != ExtractionStatus.COMPLETED.value:
        raise ConflictError(
            "Extraction has not completed for this document, so it cannot be confirmed yet."
        )

    # Recorded on the confirmation event so the trail shows what the person signed off over.
    # Whether an incomplete pack may be confirmed at all is Step 3's completeness rule, not this
    # step's, so nothing here blocks on it.
    unresolved = [row.field_name for row in document.fields if row.has_conflict]

    document.confirmed_at = utcnow()
    document.confirmed_by_id = user.id
    document.needs_review = False

    request = document.request
    if request is not None:
        request.status = RequestStatus.EXTRACTED.value
        request.updated_at = utcnow()

    await record_audit_event(
        session,
        event_type=document_service.AuditEvent.DOCUMENT_CONFIRMED,
        entity_type="document",
        entity_id=document.id,
        actor_id=user.id,
        actor_type=ActorType.USER,
        metadata={
            "document_type": document.document_type,
            "deal_direction": document.deal_direction,
            "territory": document.territory,
            "field_count": len(document.fields),
            "overridden_field_count": sum(1 for row in document.fields if row.is_overridden),
            "unresolved_fields": unresolved,
        },
    )
    await session.commit()

    # The seam Step 2 left open. A confirmed extraction is the event matching subscribes to, and
    # it is the only trigger on this path: nothing here decides which batch a document belongs
    # to, it hands the confirmed document to the service whose job that is.
    if sales_service.is_sales_document(document):
        outcome = await sales_service.on_sales_extraction_confirmed(
            session, document, actor_id=user.id
        )
        await session.commit()
        confirmed = await _load(session, document_id)
        return ResponseEnvelope[ConfirmationResult](
            data=ConfirmationResult(
                document_id=confirmed.id,
                request_id=confirmed.request_id,
                extraction_status=confirmed.extraction_status,
                confirmed_at=confirmed.confirmed_at or datetime.now(timezone.utc),
                matching=_match_read(outcome),
            ),
            message=f"Extraction confirmed. {outcome.message}".strip(),
        )

    outcome = await matching_service.on_extraction_confirmed(session, document, actor_id=user.id)
    confirmed = await _load(session, document_id)

    # The purchase side's completion step. Confirming an extraction is where the platform learns
    # the figures are signed off, so it is where the drafts this platform writes for a purchase
    # deal are queued and where the batch's Loading Sheet row is written. Both go through the
    # machinery that already existed - `draft_service.queue_generation` and the tracker payload -
    # and both do nothing at all until the three-document bundle is genuinely complete.
    completion = await _run_purchase_completion(session, confirmed, user)

    result = ConfirmationResult(
        document_id=confirmed.id,
        request_id=confirmed.request_id,
        extraction_status=confirmed.extraction_status,
        confirmed_at=confirmed.confirmed_at or datetime.now(timezone.utc),
        matching=_match_read(outcome),
    )
    message = f"Extraction confirmed. {outcome.message}".strip()
    if completion is not None:
        bundle, run = completion
        result.purchase_bundle = bundle
        result.generated_document_types = sorted(run.generated)
        result.generation_job_ids = [run.generated[name] for name in sorted(run.generated)]
        result.loading_sheet_batch = run.loading_sheet_batch
        result.loading_sheet_status = run.loading_sheet_status
        result.completion_blocker = run.blocker
        trailer = purchase_completion.message(run)
        if trailer:
            message = f"{message} {trailer}".strip()

    return ResponseEnvelope[ConfirmationResult](data=result, message=message)


def _bundle_read(status: purchase_intake.BundleStatus) -> PurchaseBundleRead:
    return PurchaseBundleRead(
        items=[
            PurchaseBundleItemRead(
                item=row.item,
                label=row.label,
                received=row.received,
                confirmed=row.confirmed,
                document_id=row.document_id,
                filename=row.filename,
            )
            for row in status.items
        ],
        missing=list(status.missing),
        complete=status.complete,
        confirmed=status.confirmed,
        unexpected=[
            PurchaseBundleItemRead(
                item=row.document_type or "unknown",
                label=(row.document_type or "unknown").replace("_", " ").title(),
                received=True,
                confirmed=row.confirmed_at is not None,
                document_id=row.id,
                filename=row.filename,
            )
            for row in status.unexpected
        ],
        summary=status.summary(),
    )


async def _run_purchase_completion(
    session: DbSession, document: Document, user: User
) -> tuple[PurchaseBundleRead, purchase_completion.CompletionResult] | None:
    """Report the bundle, and set off what a complete one owes. None for a non-purchase batch."""
    if document.transaction_id is None:
        return None
    transaction = await draft_service.load_transaction(session, document.transaction_id)
    if transaction.purchase_leg is None:
        return None

    run = await purchase_completion.on_purchase_confirmed(session, transaction, actor=user)
    await session.commit()
    status = await purchase_intake.status_for_transaction(session, transaction.id)
    return _bundle_read(status), run


def _sales_match_read(match: sales_service.SalesMatch) -> MatchOutcomeRead:
    """The sales side's own bands, on the response shape the review screen already reads."""
    return MatchOutcomeRead(
        outcome=match.outcome,
        message=match.message,
        transaction_id=match.transaction_id,
        batch_number=match.batch_number,
        score=match.score,
        method=match.method,
        needs_user_decision=match.needs_user_decision,
        candidates=[
            MatchCandidateRead(
                transaction_id=UUID(str(candidate["transaction_id"])),
                batch_number=str(candidate["batch_number"]),
                supplier_name=candidate.get("supplier_name"),
                contract_number=candidate.get("contract_number"),
                score=float(candidate["score"]),
                rationale=str(candidate["rationale"]),
            )
            for candidate in match.candidates
        ],
    )


def _match_read(outcome: matching_service.MatchResult) -> MatchOutcomeRead:
    return MatchOutcomeRead(
        outcome=outcome.outcome,
        message=outcome.message,
        transaction_id=outcome.transaction_id,
        batch_number=outcome.batch_number,
        score=outcome.score,
        method=outcome.method,
        needs_user_decision=outcome.needs_user_decision,
        candidates=[
            MatchCandidateRead(
                transaction_id=UUID(str(candidate["transaction_id"])),
                batch_number=str(candidate["batch_number"]),
                supplier_name=candidate.get("supplier_name"),
                contract_number=candidate.get("contract_number"),
                score=float(candidate["score"]),
                rationale=str(candidate["rationale"]),
            )
            for candidate in outcome.candidates
        ],
    )


@router.get(
    "/{document_id}/match",
    response_model=ResponseEnvelope[MatchOutcomeRead],
    summary="What matching would do with this document, as it stands",
)
async def read_match(
    document_id: UUID,
    user: CurrentUser,
    session: DbSession,
) -> ResponseEnvelope[MatchOutcomeRead]:
    """Re-derive the current matching position rather than storing a pending suggestion.

    Scoring is deterministic, so re-deriving it costs nothing in accuracy and means a reload, a
    second reviewer or a later visit all see exactly what the server would actually do - with no
    half-resolved suggestion sitting in a table waiting to go stale.
    """
    document = await _load(session, document_id)
    if sales_service.is_sales_document(document):
        return ResponseEnvelope[MatchOutcomeRead](
            data=_sales_match_read(await sales_service.evaluate_attachment(session, document))
        )
    outcome = await matching_service.evaluate_match(session, document)
    return ResponseEnvelope[MatchOutcomeRead](data=_match_read(outcome))


@router.post(
    "/{document_id}/match",
    response_model=ResponseEnvelope[MatchOutcomeRead],
    summary="Confirm or reject a suggested batch match",
)
async def resolve_match(
    document_id: UUID,
    payload: MatchResolution,
    user: MatchResolutionUser,
    session: DbSession,
) -> ResponseEnvelope[MatchOutcomeRead]:
    """Settle an ambiguous match before anything is created.

    Added beyond the original module list because Section 9.3's suggested band needs a real
    action behind it: a candidate offered to a person has to be confirmable or rejectable, and
    resolving it here is what keeps the platform free of any merge operation later.
    """
    document = await _load(session, document_id)
    outcome = await matching_service.resolve_suggestion(
        session,
        document,
        decision=payload.decision,
        transaction_id=payload.transaction_id,
        actor_id=user.id,
    )
    return ResponseEnvelope[MatchOutcomeRead](data=_match_read(outcome), message=outcome.message)

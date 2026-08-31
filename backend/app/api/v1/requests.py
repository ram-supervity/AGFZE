"""The inbox queue, one request's detail, and the reply that goes back on its thread.

The reply endpoints are the only place on this platform where something leaves for a
counterparty's inbox, and they are shaped by that. Composing writes a row and touches no mailbox;
sending is its own call, made by a signed-in person, recorded against their account. There is no
endpoint, worker or event here that does both.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.dependencies import CurrentUser, DbSession, require_roles
from app.core.errors import NotFoundError
from app.core.roles import PlatformRole
from app.db.base import utcnow
from app.models.enums import (
    BUSINESS_STREAMS,
    REQUEST_CATEGORIES,
    REQUEST_STATUSES,
    RequestCategory,
)
from app.models.identity import User
from app.models.intake import Document, EmailReplyDraft, Request
from app.models.transactions import TradeTransaction
from app.schemas.common import ResponseEnvelope
from app.schemas.intake import (
    CategoryOverrideRequest,
    DocumentSummary,
    EmailMessageRead,
    Page,
    ReplyComposeRequest,
    ReplyDraftList,
    PurchaseBundleItemSummary,
    PurchaseBundleSummary,
    ReplyDraftRead,
    RequestDetail,
    RequestQueue,
    RequestSummary,
)
from app.services import (
    document_service,
    email_reply_service,
    purchase_intake,
    request_service,
)
from app.services.audit_service import ActorType, record_audit_event
from app.services.storage import get_storage_service

router = APIRouter(prefix="/requests", tags=["requests"])

# The desks that own the work correct it. The approver reviews and signs off, and does not act
# as the correcting party; the auditor observes. Both still read everything below.
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


async def _thumbnail(document: Document) -> str | None:
    refs = document.page_image_refs or []
    if not refs:
        return None
    return await get_storage_service().get_signed_url(refs[0])


def _summary(
    request: Request,
    document_count: int,
    txn: TradeTransaction | None = None,
) -> RequestSummary:
    summary = RequestSummary.model_validate(request)
    summary.document_count = document_count
    if request.email_message is not None:
        summary.subject = request.email_message.subject
        summary.sender_address = request.email_message.sender_address
    if txn is not None:
        summary.transaction_id = txn.id
        if txn.sales_leg is not None and txn.purchase_leg is None:
            summary.transaction_leg_type = "sales"
        elif txn.purchase_leg is not None:
            summary.transaction_leg_type = "purchase"
        elif txn.fa_leg is not None:
            summary.transaction_leg_type = "fa"
    return summary


@router.get(
    "",
    response_model=ResponseEnvelope[RequestQueue],
    summary="Paginated, filterable request queue",
)
async def list_requests(
    user: CurrentUser,
    session: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    category: str | None = Query(None),
    stream: str | None = Query(None),
    status: str | None = Query(None),
    min_confidence: float | None = Query(None, ge=0.0, le=1.0),
    needs_review: bool | None = Query(None),
    search: str | None = Query(None, max_length=200),
) -> ResponseEnvelope[RequestQueue]:
    if category and category not in REQUEST_CATEGORIES:
        category = None
    if stream and stream not in BUSINESS_STREAMS:
        stream = None
    if status and status not in REQUEST_STATUSES:
        status = None

    statement = request_service.queue_query(
        category=category,
        stream=stream,
        status=status,
        min_confidence=min_confidence,
        needs_review=needs_review,
        search=search,
    )
    total = await request_service.count_query(session, statement)

    rows = (
        await session.scalars(
            statement.options(selectinload(Request.email_message))
            .order_by(Request.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()

    request_ids = [row.id for row in rows]
    counts = dict(
        (
            await session.execute(
                select(Document.request_id, func.count(Document.id))
                .where(Document.request_id.in_(request_ids or [None]))
                .group_by(Document.request_id)
            )
        ).all()
    )

    txns = (
        await session.scalars(
            select(TradeTransaction)
            .where(TradeTransaction.request_id.in_(request_ids or [None]))
            .options(
                selectinload(TradeTransaction.purchase_leg),
                selectinload(TradeTransaction.sales_leg),
                selectinload(TradeTransaction.fa_leg),
            )
        )
    ).all()
    txn_by_request: dict[UUID, TradeTransaction] = {t.request_id: t for t in txns if t.request_id}

    return ResponseEnvelope[RequestQueue](
        data=RequestQueue(
            items=[
                _summary(row, int(counts.get(row.id, 0)), txn_by_request.get(row.id))
                for row in rows
            ],
            page=Page(
                page=page,
                page_size=page_size,
                total=total,
                total_pages=max(1, -(-total // page_size)),
            ),
        )
    )


@router.get(
    "/{request_id}",
    response_model=ResponseEnvelope[RequestDetail],
    summary="Full request detail with its attachments",
)
async def read_request(
    request_id: UUID,
    user: CurrentUser,
    session: DbSession,
) -> ResponseEnvelope[RequestDetail]:
    request = await session.scalar(
        select(Request)
        .where(Request.id == request_id)
        .options(selectinload(Request.email_message), selectinload(Request.documents))
    )
    if request is None:
        raise NotFoundError("Request not found.")

    txn = await session.scalar(
        select(TradeTransaction)
        .where(
            or_(
                TradeTransaction.request_id == request_id,
                TradeTransaction.id.in_(
                    [doc.transaction_id for doc in request.documents if doc.transaction_id] or [None]
                ),
            )
        )
        .options(
            selectinload(TradeTransaction.purchase_leg),
            selectinload(TradeTransaction.sales_leg),
            selectinload(TradeTransaction.fa_leg),
        )
    )

    documents: list[DocumentSummary] = []
    for document in request.documents:
        summary = DocumentSummary.model_validate(document)
        summary.thumbnail_url = await _thumbnail(document)
        documents.append(summary)

    detail = RequestDetail.model_validate(request)
    detail.document_count = len(documents)
    detail.documents = documents
    if txn is not None:
        detail.transaction_id = txn.id
        if txn.sales_leg is not None and txn.purchase_leg is None:
            detail.transaction_leg_type = "sales"
        elif txn.purchase_leg is not None:
            detail.transaction_leg_type = "purchase"
        elif txn.fa_leg is not None:
            detail.transaction_leg_type = "fa"

    # The three-document bundle, on the intakes it is about and nowhere else. Computed rather
    # than stored: it is a reading of what is attached right now, and a stored copy would go
    # stale the moment a document was reclassified.
    if purchase_intake.is_purchase_request(request):
        detail.purchase_bundle = _bundle_summary(
            purchase_intake.status_for(list(request.documents))
        )

    if request.email_message is not None:
        detail.email = EmailMessageRead.model_validate(request.email_message)
        detail.subject = request.email_message.subject
        detail.sender_address = request.email_message.sender_address

    return ResponseEnvelope[RequestDetail](data=detail)


def _bundle_summary(status: purchase_intake.BundleStatus) -> PurchaseBundleSummary:
    return PurchaseBundleSummary(
        items=[
            PurchaseBundleItemSummary(
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
            PurchaseBundleItemSummary(
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


@router.patch(
    "/{request_id}/category",
    response_model=ResponseEnvelope[RequestDetail],
    summary="Correct the AI-assigned category",
)
async def override_category(
    request_id: UUID,
    payload: CategoryOverrideRequest,
    user: CorrectionUser,
    session: DbSession,
) -> ResponseEnvelope[RequestDetail]:
    request = await request_service.get_request(session, request_id)

    previous_category = request.category
    previous_stream = request.stream
    previous_direction = request.deal_direction
    # The AI's first answer is captured once and then never rewritten, override or not.
    if request.original_category is None:
        request.original_category = previous_category
    if payload.stream is not None and request.original_stream is None:
        request.original_stream = previous_stream

    request.category = payload.category
    if payload.stream is not None:
        request.stream = payload.stream
    if payload.deal_direction is not None:
        request.deal_direction = payload.deal_direction
    elif payload.category == RequestCategory.PURCHASE.value:
        request.deal_direction = "purchase"
    elif payload.category == RequestCategory.SALES.value:
        request.deal_direction = "sales"

    # Propagate deal direction to child documents if set
    if request.deal_direction:
        docs = (
            await session.scalars(select(Document).where(Document.request_id == request_id))
        ).all()
        for doc in docs:
            doc.deal_direction = request.deal_direction

    request.category_overridden = True
    request.category_override_reason = payload.reason
    request.category_overridden_by_id = user.id
    request.category_overridden_at = utcnow()
    request.needs_review = False
    request_service.mark_updated(request)

    await record_audit_event(
        session,
        event_type=document_service.AuditEvent.REQUEST_CATEGORY_OVERRIDDEN,
        entity_type="request",
        entity_id=request.id,
        actor_id=user.id,
        actor_type=ActorType.USER,
        metadata={
            "request_code": request.request_code,
            "previous_category": previous_category,
            "new_category": payload.category,
            "previous_stream": previous_stream,
            "new_stream": request.stream,
            "previous_deal_direction": previous_direction,
            "new_deal_direction": request.deal_direction,
            "original_ai_category": request.original_category,
            "reason": payload.reason,
        },
    )
    await session.commit()
    await session.refresh(request)

    return await read_request(request_id=request.id, user=user, session=session)


# --- replying on the thread a request arrived on -----------------------------------------------
#
# Two endpoints and never one. Composing a reply reaches no mailbox at all; sending it is a
# separate call a person makes deliberately, and their account is what the audit trail records
# against the message. Nothing on this platform can move a draft to sent on its own.


def _reply_read(draft: EmailReplyDraft) -> ReplyDraftRead:
    read = ReplyDraftRead.model_validate(draft)
    read.composed_by_name = draft.composed_by.display_name if draft.composed_by else None
    read.sent_by_name = draft.sent_by.display_name if draft.sent_by else None
    return read


@router.get(
    "/{request_id}/replies",
    response_model=ResponseEnvelope[ReplyDraftList],
    summary="Every reply composed on this request's thread, sent or not",
)
async def list_replies(
    request_id: UUID,
    user: CurrentUser,
    session: DbSession,
) -> ResponseEnvelope[ReplyDraftList]:
    request = await request_service.get_request(session, request_id)
    drafts = await email_reply_service.list_for_request(session, request.id)
    recipient = request.email_message.sender_address if request.email_message is not None else None
    return ResponseEnvelope[ReplyDraftList](
        data=ReplyDraftList(
            items=[_reply_read(draft) for draft in drafts],
            recipient_address=recipient,
            outbound_enabled=settings.reply_configured,
        )
    )


@router.post(
    "/{request_id}/replies",
    response_model=ResponseEnvelope[ReplyDraftRead],
    summary="Compose a reply on this thread - stored for review, sent to nobody",
)
async def compose_reply(
    request_id: UUID,
    payload: ReplyComposeRequest,
    user: CorrectionUser,
    session: DbSession,
) -> ResponseEnvelope[ReplyDraftRead]:
    """Writes a draft and returns it. No mailbox is contacted by this call, on any deployment."""
    draft = await email_reply_service.compose(
        session, request_id, message=payload.message, composed_by=user
    )
    await session.commit()
    await session.refresh(draft)
    return ResponseEnvelope[ReplyDraftRead](
        data=_reply_read(draft),
        message=(
            "Drafted. Nothing has been sent: read it back, and send it deliberately when it says "
            "what you mean."
        ),
    )


@router.post(
    "/{request_id}/replies/{draft_id}/send",
    response_model=ResponseEnvelope[ReplyDraftRead],
    summary="Send a composed reply on the original thread, recorded against your account",
)
async def send_reply(
    request_id: UUID,
    draft_id: UUID,
    user: CorrectionUser,
    session: DbSession,
) -> ResponseEnvelope[ReplyDraftRead]:
    """The one call on this platform that puts a message into somebody else's inbox.

    It exists as its own endpoint precisely so that nothing else can reach it: there is no branch
    of the compose path, no background task and no event handler that sends. A person did this.
    """
    draft = await email_reply_service.get_draft(session, draft_id)
    if draft.request_id != request_id:
        raise NotFoundError("That reply does not belong to this request.")

    sent = await email_reply_service.send(session, draft_id, sent_by=user)
    await session.commit()
    await session.refresh(sent)
    return ResponseEnvelope[ReplyDraftRead](
        data=_reply_read(sent),
        message="Sent on the original thread, recorded against your account.",
    )


@router.post(
    "/{request_id}/replies/{draft_id}/withdraw",
    response_model=ResponseEnvelope[ReplyDraftRead],
    summary="Abandon a composed reply that has not been sent",
)
async def withdraw_reply(
    request_id: UUID,
    draft_id: UUID,
    user: CorrectionUser,
    session: DbSession,
) -> ResponseEnvelope[ReplyDraftRead]:
    draft = await email_reply_service.get_draft(session, draft_id)
    if draft.request_id != request_id:
        raise NotFoundError("That reply does not belong to this request.")

    withdrawn = await email_reply_service.withdraw(session, draft_id, withdrawn_by=user)
    await session.commit()
    await session.refresh(withdrawn)
    return ResponseEnvelope[ReplyDraftRead](
        data=_reply_read(withdrawn),
        message="Withdrawn. Nothing was sent.",
    )

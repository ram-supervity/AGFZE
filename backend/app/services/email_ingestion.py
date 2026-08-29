"""The single ingestion funnel both mailbox capture paths run through.

The webhook and the delta poll each end at :func:`ingest_message`. Deduplication is strictly on
the mail provider's own message id, enforced by the unique index on
`email_messages.provider_message_id`: whichever path arrives second finds the row and stops, and
two paths arriving at once resolve through the resulting integrity error. One message can never
become two `EmailMessage` rows and never two `Request` rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.models.enums import RequestSource
from app.models.intake import Document, EmailMessage, Request
from app.services import document_service, request_service
from app.services.audit_service import ActorType, record_audit_event
from app.services.file_intake import inspect_bytes, storage_key
from app.services.graph_service import GraphClient, GraphError, get_graph_client
from app.services.storage import get_storage_service

logger = get_logger(__name__)


@dataclass(frozen=True)
class IngestionResult:
    request_id: UUID | None
    email_message_id: UUID | None
    created: bool
    document_count: int = 0
    reason: str | None = None


async def _existing(session: AsyncSession, provider_message_id: str) -> EmailMessage | None:
    return await session.scalar(
        select(EmailMessage).where(EmailMessage.provider_message_id == provider_message_id)
    )


async def _request_for(session: AsyncSession, email_id: UUID) -> Request | None:
    return await session.scalar(select(Request).where(Request.email_message_id == email_id))


async def ingest_message(
    session: AsyncSession,
    provider_message_id: str,
    *,
    client: GraphClient | None = None,
    process: bool = True,
) -> IngestionResult:
    """Capture one mailbox message exactly once.

    Returns without creating anything when the message id has already been seen, whichever path
    saw it first.
    """
    if not provider_message_id:
        return IngestionResult(None, None, created=False, reason="missing_message_id")

    seen = await _existing(session, provider_message_id)
    if seen is not None:
        request = await _request_for(session, seen.id)
        return IngestionResult(
            request_id=request.id if request else None,
            email_message_id=seen.id,
            created=False,
            reason="already_ingested",
        )

    graph = client or get_graph_client()
    message = await graph.get_message(provider_message_id)

    storage = get_storage_service()
    raw_ref: str | None = None
    try:
        raw = await graph.get_raw_message(provider_message_id)
        raw_ref = storage_key("emails/raw", "message.eml")
        await storage.upload(raw_ref, raw, "message/rfc822")
    except (GraphError, OSError):
        # The original MIME is evidence, not a precondition: losing it must not lose the mail.
        logger.warning("raw_message_not_stored", extra={"mailbox": settings.GRAPH_MAILBOX_ADDRESS})
        raw_ref = None

    email = EmailMessage(
        provider_message_id=provider_message_id,
        mailbox_address=settings.GRAPH_MAILBOX_ADDRESS,
        sender_address=message.sender_address,
        sender_name=message.sender_name,
        subject=message.subject,
        body_text=message.body_text,
        received_at=message.received_at,
        has_attachments=message.has_attachments,
        raw_storage_ref=raw_ref,
    )
    session.add(email)
    try:
        await session.flush()
    except IntegrityError:
        # The other capture path won the race. Roll back to its row and report no creation.
        await session.rollback()
        seen = await _existing(session, provider_message_id)
        request = await _request_for(session, seen.id) if seen else None
        return IngestionResult(
            request_id=request.id if request else None,
            email_message_id=seen.id if seen else None,
            created=False,
            reason="already_ingested",
        )

    request = await request_service.create_request(
        session, source=RequestSource.EMAIL, email_message_id=email.id
    )

    document_count = 0
    if message.has_attachments:
        document_count = await _attach_documents(session, graph, provider_message_id, request)

    await record_audit_event(
        session,
        event_type=document_service.AuditEvent.EMAIL_INGESTED,
        entity_type="request",
        entity_id=request.id,
        actor_type=ActorType.SYSTEM,
        metadata={
            "request_code": request.request_code,
            "provider_message_id": provider_message_id,
            "document_count": document_count,
        },
    )
    await session.commit()

    if process:
        await document_service.queue_request_processing(session, request.id)

    return IngestionResult(
        request_id=request.id,
        email_message_id=email.id,
        created=True,
        document_count=document_count,
    )


async def _attach_documents(
    session: AsyncSession, graph: GraphClient, provider_message_id: str, request: Request
) -> int:
    """Fetch each attachment's bytes as it is processed, admitting only what passes inspection."""
    try:
        attachments = await graph.list_attachments(provider_message_id)
    except GraphError:
        logger.warning("attachment_list_failed", extra={"request_id": str(request.id)})
        return 0

    storage = get_storage_service()
    stored = 0
    for attachment in attachments:
        if attachment.is_inline:
            continue
        if attachment.size and attachment.size > settings.MAX_UPLOAD_BYTES:
            logger.info(
                "attachment_rejected",
                extra={"request_id": str(request.id), "reason": "too_large"},
            )
            continue
        try:
            data = await graph.get_attachment_bytes(provider_message_id, attachment.attachment_id)
            # The same magic-byte whitelist and size limit as the portal upload path. A mailbox
            # attachment gets no exemption for arriving over Graph.
            inspected = inspect_bytes(attachment.name, data)
        except (GraphError, AppError) as exc:
            logger.info(
                "attachment_rejected",
                extra={"request_id": str(request.id), "reason": getattr(exc, "code", "invalid")},
            )
            continue

        key = document_service.new_document_storage_key(inspected.filename)
        await storage.upload(key, inspected.data, inspected.content_type)
        session.add(
            Document(
                request_id=request.id,
                filename=inspected.filename,
                content_type=inspected.content_type,
                byte_size=inspected.byte_size,
                storage_ref=key,
                content_hash=inspected.content_hash,
            )
        )
        stored += 1

    await session.flush()
    return stored

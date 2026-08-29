"""Request creation, the request code sequence, and the queue query."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.db.base import utcnow
from app.models.enums import RequestSource, RequestStatus
from app.models.intake import Document, EmailMessage, Request

CODE_PREFIX = "REQ"
MAX_CODE_ATTEMPTS = 5


def _code_for(day: datetime, sequence: int) -> str:
    return f"{CODE_PREFIX}-{day.strftime('%Y%m%d')}-{sequence:04d}"


async def _next_sequence(session: AsyncSession, day: datetime) -> int:
    prefix = f"{CODE_PREFIX}-{day.strftime('%Y%m%d')}-"
    highest = await session.scalar(
        select(func.max(Request.request_code)).where(Request.request_code.like(f"{prefix}%"))
    )
    if not highest:
        return 1
    try:
        return int(highest.rsplit("-", 1)[1]) + 1
    except (IndexError, ValueError):
        return 1


async def create_request(
    session: AsyncSession,
    *,
    source: RequestSource,
    email_message_id: UUID | None = None,
    created_by_id: UUID | None = None,
    stream: str | None = None,
) -> Request:
    """Create a request with the next `REQ-{yyyyMMdd}-{sequence}` code for today.

    The unique index on `request_code` is the arbiter: two concurrent creations resolve by one of
    them retrying against the code the other took.
    """
    day = datetime.now(timezone.utc)
    for attempt in range(MAX_CODE_ATTEMPTS):
        sequence = await _next_sequence(session, day) + attempt
        request = Request(
            request_code=_code_for(day, sequence),
            source=source.value,
            email_message_id=email_message_id,
            created_by_id=created_by_id,
            stream=stream,
            original_stream=stream,
            status=RequestStatus.RECEIVED.value,
        )
        session.add(request)
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            continue
        return request
    raise ConflictError("Could not allocate a request code; please retry.")


async def get_request(session: AsyncSession, request_id: UUID) -> Request:
    request = await session.get(Request, request_id)
    if request is None:
        raise NotFoundError("Request not found.")
    return request


def queue_query(
    *,
    category: str | None = None,
    stream: str | None = None,
    status: str | None = None,
    min_confidence: float | None = None,
    needs_review: bool | None = None,
    search: str | None = None,
) -> Select[tuple[Request]]:
    statement = select(Request)
    if category:
        statement = statement.where(Request.category == category)
    if stream:
        statement = statement.where(Request.stream == stream)
    if status:
        statement = statement.where(Request.status == status)
    if min_confidence is not None:
        statement = statement.where(Request.category_confidence >= min_confidence)
    if needs_review is not None:
        statement = statement.where(Request.needs_review.is_(needs_review))
    if search:
        term = f"%{search.strip().lower()}%"
        statement = (
            statement.outerjoin(EmailMessage, Request.email_message_id == EmailMessage.id)
            .outerjoin(Document, Document.request_id == Request.id)
            .where(
                or_(
                    func.lower(Request.request_code).like(term),
                    func.lower(func.coalesce(EmailMessage.subject, "")).like(term),
                    func.lower(func.coalesce(EmailMessage.sender_address, "")).like(term),
                    func.lower(func.coalesce(Document.filename, "")).like(term),
                )
            )
            .distinct()
        )
    return statement


async def count_query(session: AsyncSession, statement: Select) -> int:
    total = await session.scalar(
        select(func.count()).select_from(statement.order_by(None).subquery())
    )
    return int(total or 0)


def mark_updated(request: Request) -> None:
    request.updated_at = utcnow()

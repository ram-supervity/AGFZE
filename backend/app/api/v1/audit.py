"""The audit explorer: the filtered list, and its streamed CSV export.

Admin and Auditor, enforced server-side. Read-only in the strongest sense - there is no create,
update or delete route on `audit_events` here or anywhere else, at any role, because the table is
append-only and a correction to it is a new event, never an edit.

The export streams. This table has been filling since the very first step and has no upper bound,
so the response is produced row by row from a server-side cursor rather than assembled in memory
and handed to the client in one piece. See `app.services.audit_query.stream_csv`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core.dependencies import DbSession, require_roles
from app.core.roles import PlatformRole
from app.db.base import utcnow
from app.models.audit import AuditEvent
from app.models.identity import User
from app.schemas.audit import AuditActorRead, AuditEventList, AuditEventListItem
from app.schemas.common import ResponseEnvelope
from app.schemas.intake import Page
from app.services import audit_query
from app.services.audit_service import ActorType, record_audit_event

router = APIRouter(prefix="/audit", tags=["audit"])

# Admin for the platform, Auditor for the independent oversight the role exists to give.
AuditReader = Annotated[
    User,
    Depends(require_roles(PlatformRole.ADMIN.value, PlatformRole.AUDITOR.value)),
]

AUDIT_EXPORTED = "audit.exported"


def _item(event: AuditEvent) -> AuditEventListItem:
    actor = event.actor
    return AuditEventListItem(
        id=event.id,
        occurred_at=event.occurred_at,
        actor_id=event.actor_id,
        actor_name=actor.display_name if actor else None,
        actor_email=actor.email if actor else None,
        actor_type=event.actor_type,
        event_type=event.event_type,
        entity_type=event.entity_type,
        entity_id=event.entity_id,
        # Summarised on the way out: redacted by key, bounded by length. The explorer is a
        # governance screen and must never become a viewer for document text or a model prompt.
        event_metadata=audit_query.summarise_metadata(event.event_metadata),
    )


@router.get(
    "",
    response_model=ResponseEnvelope[AuditEventList],
    summary="Every recorded event, filterable by date, type, actor and entity",
)
async def list_audit_events(
    user: AuditReader,
    session: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    event_type: str | None = Query(None),
    actor_id: UUID | None = Query(None),
    entity_type: str | None = Query(None),
    search: str | None = Query(None, description="Entity reference, or the kind of entity"),
) -> ResponseEnvelope[AuditEventList]:
    statement = audit_query.list_query(
        date_from=date_from,
        date_to=date_to,
        event_type=event_type,
        actor_id=actor_id,
        entity_type=entity_type,
        search=search,
    )
    total = int(await session.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    rows = list(
        (
            await session.scalars(
                statement.options(selectinload(AuditEvent.actor))
                .order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )

    return ResponseEnvelope[AuditEventList](
        data=AuditEventList(
            items=[_item(row) for row in rows],
            page=Page(
                page=page,
                page_size=page_size,
                total=total,
                total_pages=max(1, -(-total // page_size)),
            ),
            event_types=await audit_query.event_types(session),
            entity_types=await audit_query.entity_types(session),
            actors=[
                AuditActorRead.model_validate(row) for row in await audit_query.actors(session)
            ],
        )
    )


@router.get(
    "/export",
    summary="The filtered set as CSV, streamed rather than assembled in memory",
    response_class=StreamingResponse,
)
async def export_audit_events(
    user: AuditReader,
    session: DbSession,
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    event_type: str | None = Query(None),
    actor_id: UUID | None = Query(None),
    entity_type: str | None = Query(None),
    search: str | None = Query(None),
) -> StreamingResponse:
    """The export is itself an auditable act, so it is recorded before a byte goes out.

    The filters are recorded with it - counts and parameters, never event content - so it is
    possible to establish afterwards what somebody took a copy of.
    """
    statement = audit_query.list_query(
        date_from=date_from,
        date_to=date_to,
        event_type=event_type,
        actor_id=actor_id,
        entity_type=entity_type,
        search=search,
    )
    matching = int(
        await session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    )
    await record_audit_event(
        session,
        event_type=AUDIT_EXPORTED,
        entity_type="audit_events",
        actor_id=user.id,
        actor_type=ActorType.USER,
        metadata={
            "row_count": matching,
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
            "event_type": event_type,
            "actor_id": str(actor_id) if actor_id else None,
            "entity_type": entity_type,
            "search": search,
        },
    )
    await session.commit()

    filename = audit_query.export_filename(utcnow())
    return StreamingResponse(
        audit_query.stream_csv(session, statement),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            # The count is in a header rather than the body so the CSV stays a clean CSV.
            "X-Total-Rows": str(matching),
        },
    )

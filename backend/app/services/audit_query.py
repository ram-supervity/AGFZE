"""Reading the append-only audit trail: the filtered list, and the streamed export.

Read-only in the strongest sense. Nothing in this module writes, updates or deletes an audit row,
and there is no code path anywhere in this platform that could - a correction to the trail is a
new event referencing the same entity, exactly as `app.models.audit` says.

Two things here are deliberate rather than incidental:

* The event-type filter is populated from a `SELECT DISTINCT` over the data, not from a list
  written here. Ten steps have contributed event types - intake, matching, validation,
  exceptions, approvals, sales drafting, FA, shipments, integration jobs, reporting - and a
  hardcoded list would be wrong on the day the eleventh step adds one.
* The CSV export streams. This table has been accumulating since the very first step and there is
  no upper bound on it, so the export yields row by row from a server-side cursor and never
  materialises the result set. See :func:`stream_csv`.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from sqlalchemy import Select, distinct, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.audit import AuditEvent
from app.models.identity import User

# How much of one metadata value the explorer will render. Metadata is metadata by discipline -
# identifiers, counts, decisions - so nothing legitimate approaches this. It is a backstop, not a
# feature: if a call site ever regressed and put prose in there, the explorer truncates it rather
# than becoming a viewer for document text.
MAX_METADATA_VALUE_CHARS = 160

# Keys the explorer never renders, whatever they hold. None of these is written by any call site
# in the platform today - the suite proves that separately - and listing them here means a future
# mistake is contained by the screen as well as caught by the test.
REDACTED_METADATA_KEYS: frozenset[str] = frozenset(
    {
        "prompt",
        "response",
        "completion",
        "raw_response",
        "body",
        "body_text",
        "text",
        "content",
        "document_text",
        "page_text",
        "extracted_text",
        "secret",
        "password",
        "token",
        "api_key",
        "client_secret",
        "authorization",
    }
)

CSV_COLUMNS: tuple[str, ...] = (
    "occurred_at",
    "event_type",
    "actor_name",
    "actor_email",
    "actor_type",
    "entity_type",
    "entity_id",
    "metadata",
)


def summarise_metadata(payload: dict[str, Any] | None) -> dict[str, Any]:
    """The metadata as the explorer shows it: keys redacted by name, values bounded by length.

    Applied on the read rather than on the write, so the stored row is never altered - the trail
    is append-only and what it holds is what it holds. This governs what leaves the API.
    """
    summary: dict[str, Any] = {}
    for key, value in (payload or {}).items():
        lowered = str(key).lower()
        if lowered in REDACTED_METADATA_KEYS:
            summary[key] = "[redacted]"
            continue
        if isinstance(value, str) and len(value) > MAX_METADATA_VALUE_CHARS:
            summary[key] = value[:MAX_METADATA_VALUE_CHARS] + "…"
            continue
        if isinstance(value, dict | list):
            rendered = json.dumps(value, default=str)
            summary[key] = (
                rendered
                if len(rendered) <= MAX_METADATA_VALUE_CHARS
                else rendered[:MAX_METADATA_VALUE_CHARS] + "…"
            )
            continue
        summary[key] = value
    return summary


def list_query(
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    event_type: str | None = None,
    actor_id: Any | None = None,
    entity_type: str | None = None,
    search: str | None = None,
) -> Select[tuple[AuditEvent]]:
    """The filtered set, as a query. Every filter lands in the WHERE clause, none in Python."""
    statement = select(AuditEvent)
    if date_from is not None:
        statement = statement.where(AuditEvent.occurred_at >= date_from)
    if date_to is not None:
        statement = statement.where(AuditEvent.occurred_at <= date_to)
    if event_type:
        statement = statement.where(AuditEvent.event_type == event_type)
    if actor_id is not None:
        statement = statement.where(AuditEvent.actor_id == actor_id)
    if entity_type:
        statement = statement.where(AuditEvent.entity_type == entity_type)
    if search:
        term = f"%{search.strip().lower()}%"
        # The entity reference search: the id itself, or the kind of thing it refers to.
        statement = statement.where(
            or_(AuditEvent.entity_id.ilike(term), AuditEvent.entity_type.ilike(term))
        )
    return statement


async def event_types(session: AsyncSession) -> list[str]:
    """Every event type that actually exists in the data, alphabetically.

    Read from the table, deliberately. Every step since the first has contributed its own
    vocabulary, and a filter built from a list maintained by hand would quietly stop offering the
    newest one.
    """
    rows = (
        await session.scalars(
            select(distinct(AuditEvent.event_type)).order_by(AuditEvent.event_type)
        )
    ).all()
    return [str(row) for row in rows if row]


async def entity_types(session: AsyncSession) -> list[str]:
    rows = (
        await session.scalars(
            select(distinct(AuditEvent.entity_type)).order_by(AuditEvent.entity_type)
        )
    ).all()
    return [str(row) for row in rows if row]


async def actors(session: AsyncSession) -> list[User]:
    """Every account that has ever appeared as an actor, for the explorer's actor filter."""
    subquery = select(distinct(AuditEvent.actor_id)).where(AuditEvent.actor_id.is_not(None))
    return list(
        (
            await session.scalars(
                select(User).where(User.id.in_(subquery)).order_by(User.display_name)
            )
        ).all()
    )


def _row_values(event: AuditEvent) -> list[str]:
    actor = event.actor
    return [
        event.occurred_at.isoformat() if event.occurred_at else "",
        event.event_type,
        actor.display_name if actor else "",
        actor.email if actor else "",
        event.actor_type,
        event.entity_type,
        event.entity_id or "",
        json.dumps(summarise_metadata(event.event_metadata), default=str, sort_keys=True),
    ]


async def stream_csv(
    session: AsyncSession, statement: Select[tuple[AuditEvent]], *, chunk_size: int = 500
) -> AsyncIterator[str]:
    """Yield the export as CSV, a chunk at a time, never the whole result set at once.

    `stream_results` asks the driver for a server-side cursor and `yield_per` bounds how many ORM
    rows are alive at once, so memory here is a function of `chunk_size` and not of how many
    events the platform has recorded since Step 1. The buffer is a single reusable `StringIO`
    that is truncated after every flush; at no point does this function hold a list of rows.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    writer.writerow(CSV_COLUMNS)
    yield buffer.getvalue()
    buffer.seek(0)
    buffer.truncate(0)

    ordered = statement.order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc()).options(
        selectinload(AuditEvent.actor)
    )
    result = await session.stream(ordered.execution_options(yield_per=chunk_size))
    async for partition in result.partitions(chunk_size):
        for (event,) in partition:
            writer.writerow(_row_values(event))
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)


def export_filename(now: datetime) -> str:
    return f"agfze-audit-{now:%Y%m%d-%H%M%S}.csv"

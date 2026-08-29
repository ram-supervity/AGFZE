"""Governance audit trail writes.

The metadata payload holds metadata only - identifiers, counts, decisions, state transitions.
It must never carry document text, an AI prompt or completion, a credential, or any other
document content.

Every governance event added by a later step is recorded through :func:`record_audit_event`
rather than ad hoc logging, so the append-only table stays the one reconstruction of who did
what. Recurring sign-ins are carried by ``users.last_login_at``; the trail records the first
provisioning of an account, not a row per request.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditEvent


class AuditEventType:
    USER_PROVISIONED = "user.provisioned"
    # Reserved for explicit session events a later step records; not emitted per request.
    USER_LOGIN = "user.login"


class ActorType:
    USER = "user"
    SYSTEM = "system"
    AGENT = "agent"


async def record_audit_event(
    session: AsyncSession,
    *,
    event_type: str,
    entity_type: str,
    entity_id: str | UUID | None = None,
    actor_id: UUID | None = None,
    actor_type: str = ActorType.SYSTEM,
    metadata: dict | None = None,
) -> AuditEvent:
    """Append one audit row and flush it; the caller owns the commit so the event lands in the
    same transaction as the change it describes."""
    event = AuditEvent(
        event_type=event_type,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        actor_id=actor_id,
        actor_type=actor_type,
        event_metadata=dict(metadata or {}),
    )
    session.add(event)
    await session.flush()
    return event

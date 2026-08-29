"""Microsoft Graph change-notification endpoint.

Graph itself is the caller, so this route carries no bearer token. It is protected instead by the
two things Graph guarantees: the validation handshake it performs before it will ever deliver to
a URL, and the `clientState` secret it echoes on every notification, which is compared here in
constant time. A notification that does not carry the configured secret is discarded.

The endpoint does no work of its own. It resolves each notification to a message id and hands it
to the same idempotent ingestion function the delta poll uses, which is what makes double
delivery through both paths harmless.
"""

from __future__ import annotations

import asyncio
import hmac
from typing import Any

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field, ValidationError
from starlette.requests import Request

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import AsyncSessionLocal
from app.services.email_ingestion import ingest_message
from app.services.graph_service import resource_message_id

logger = get_logger(__name__)

router = APIRouter(prefix="/graph", tags=["graph"])

_TASKS: set[asyncio.Task] = set()


class ChangeNotification(BaseModel):
    subscriptionId: str | None = None
    clientState: str | None = None
    resource: str | None = None
    changeType: str | None = None
    resourceData: dict[str, Any] | None = None


class ChangeNotificationCollection(BaseModel):
    value: list[ChangeNotification] = Field(default_factory=list)


def _authentic(notification: ChangeNotification) -> bool:
    expected = settings.GRAPH_WEBHOOK_CLIENT_STATE
    if not expected:
        return False
    return hmac.compare_digest(notification.clientState or "", expected)


async def _ingest(message_id: str) -> None:
    async with AsyncSessionLocal() as session:
        try:
            result = await ingest_message(session, message_id)
        except Exception:
            await session.rollback()
            logger.exception("webhook_ingestion_failed")
            return
    logger.info(
        "webhook_notification_processed",
        extra={"created": result.created, "reason": result.reason},
    )


async def _parse(request: Request) -> ChangeNotificationCollection:
    """Read the body defensively.

    Graph posts its validation handshake with an empty text/plain body and its notifications as
    JSON, so neither shape may be allowed to become a 422 that Graph would then retry.
    """
    raw = await request.body()
    if not raw.strip():
        return ChangeNotificationCollection()
    try:
        return ChangeNotificationCollection.model_validate_json(raw)
    except ValidationError:
        logger.warning("webhook_payload_unreadable")
        return ChangeNotificationCollection()


@router.post(
    "/notifications",
    include_in_schema=False,
    summary="Graph change-notification receiver",
)
async def receive_notifications(
    request: Request,
    validationToken: str | None = Query(None),
) -> Response:
    # Subscription handshake: Graph will not deliver anything until this token is echoed back
    # verbatim as text/plain.
    if validationToken is not None:
        return Response(content=validationToken, media_type="text/plain", status_code=200)

    payload = await _parse(request)
    accepted = 0
    for notification in payload.value:
        if not _authentic(notification):
            logger.warning("webhook_client_state_mismatch")
            continue
        message_id = resource_message_id(notification.resource or "") or (
            (notification.resourceData or {}).get("id")
        )
        if not isinstance(message_id, str) or not message_id:
            continue
        # Graph expects 202 within seconds and retries anything slower, so the ingestion runs
        # detached rather than inline.
        task = asyncio.create_task(_ingest(message_id))
        _TASKS.add(task)
        task.add_done_callback(_TASKS.discard)
        accepted += 1

    logger.info("webhook_notifications_received", extra={"accepted": accepted})
    return Response(status_code=202)

"""The signed-in account's own notifications, and nobody else's.

The ownership constraint lives in the query, not in the routing: every statement in this module
filters on `Notification.user_id == user.id` taken from the verified token subject. There is no
path parameter naming a user, no query parameter that could widen the scope, and no endpoint that
reads or writes another account's rows - so there is nothing here for a crafted request to reach
even if a screen were to ask for it.

Step 10 adds the push-subscription endpoints, under exactly the same rule. `user_id` is taken
from the verified token on every one of them, the body never carries an account identifier, and
the DELETE's ownership predicate is part of the statement rather than a check performed before
it - so quoting somebody else's endpoint deletes nothing.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select

from app.core.config import settings
from app.core.dependencies import CurrentUser, DbSession
from app.models.notifications import Notification
from app.schemas.common import ResponseEnvelope
from app.schemas.intake import Page
from app.schemas.notification import (
    MarkAllReadResult,
    NotificationList,
    NotificationRead,
    PushSubscriptionCreate,
    PushSubscriptionRead,
    PushSubscriptionRemoval,
    PushUnsubscribeResult,
    VapidPublicKey,
)
from app.services import notification_service
from app.services.delivery import push_service

# The browser sends its own identification on every request; there is nothing to ask the client to
# put in the body, and a body field would be a value a client could invent.
USER_AGENT_MAX_LENGTH = 512

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get(
    "",
    response_model=ResponseEnvelope[NotificationList],
    summary="The authenticated user's own notifications",
)
async def list_notifications(
    user: CurrentUser,
    session: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    unread_only: bool = Query(False),
) -> ResponseEnvelope[NotificationList]:
    statement = select(func.count(Notification.id)).where(Notification.user_id == user.id)
    if unread_only:
        statement = statement.where(Notification.is_read.is_(False))
    total = int(await session.scalar(statement) or 0)

    rows = await notification_service.list_for_user(
        session,
        user.id,
        unread_only=unread_only,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    return ResponseEnvelope[NotificationList](
        data=NotificationList(
            items=[NotificationRead.model_validate(row) for row in rows],
            page=Page(
                page=page,
                page_size=page_size,
                total=total,
                total_pages=max(1, -(-total // page_size)),
            ),
            unread_count=await notification_service.unread_count(session, user.id),
        )
    )


@router.post(
    "/mark-all-read",
    response_model=ResponseEnvelope[MarkAllReadResult],
    summary="Mark every one of the caller's own notifications as read",
)
async def mark_all_read(
    user: CurrentUser, session: DbSession
) -> ResponseEnvelope[MarkAllReadResult]:
    marked = await notification_service.mark_all_read(session, user.id)
    await session.commit()
    return ResponseEnvelope[MarkAllReadResult](
        data=MarkAllReadResult(
            marked=marked, unread_count=await notification_service.unread_count(session, user.id)
        ),
        message=(
            f"{marked} notification{'' if marked == 1 else 's'} marked as read."
            if marked
            else "Nothing was unread."
        ),
    )


# --- push subscriptions (Step 10), self-only in exactly the same way -----------------------------


@router.get(
    "/vapid-public-key",
    response_model=ResponseEnvelope[VapidPublicKey],
    summary="The application server key a browser subscribes with",
)
async def read_vapid_public_key(user: CurrentUser) -> ResponseEnvelope[VapidPublicKey]:
    """The one secret-adjacent value on this platform that is meant to be given away.

    The Web Push standard hands the application server's *public* key to the browser so it can
    bind a subscription to this server. The private half signs deliveries, lives in configuration
    and is never returned by any endpoint. `configured` is false where no pair has been generated,
    so the screen can say so rather than offering a button that cannot work.
    """
    return ResponseEnvelope[VapidPublicKey](
        data=VapidPublicKey(
            public_key=settings.VAPID_PUBLIC_KEY if settings.push_configured else "",
            configured=settings.push_configured,
        )
    )


@router.post(
    "/push-subscribe",
    response_model=ResponseEnvelope[PushSubscriptionRead],
    summary="Register or refresh the calling browser's push subscription",
)
async def subscribe_to_push(
    payload: PushSubscriptionCreate,
    request: Request,
    user: CurrentUser,
    session: DbSession,
) -> ResponseEnvelope[PushSubscriptionRead]:
    """Upsert on (caller, endpoint). Re-subscribing the same browser updates it, never duplicates.

    Subscribing is the whole of the push opt-in. There is no preference column to set alongside
    it and there must not be: the presence of this row is what push delivery is gated on.
    """
    row = await push_service.upsert_subscription(
        session,
        user_id=user.id,
        endpoint=payload.endpoint,
        p256dh=payload.keys.p256dh,
        auth=payload.keys.auth,
        user_agent=(request.headers.get("user-agent") or "")[:USER_AGENT_MAX_LENGTH] or None,
    )
    await session.commit()
    return ResponseEnvelope[PushSubscriptionRead](
        data=PushSubscriptionRead.model_validate(row),
        message="This browser will receive push notifications.",
    )


@router.delete(
    "/push-subscribe",
    response_model=ResponseEnvelope[PushUnsubscribeResult],
    summary="Forget the caller's push subscription",
)
async def unsubscribe_from_push(
    user: CurrentUser,
    session: DbSession,
    payload: PushSubscriptionRemoval | None = None,
) -> ResponseEnvelope[PushUnsubscribeResult]:
    """Used on sign-out and on an explicit opt-out in Settings.

    With an endpoint it forgets that one browser; without one it forgets every browser on the
    account, which is what a sign-out on a shared machine should be able to ask for. Removing a
    subscription that is not there is a success returning zero, not an error - a sign-out must
    never fail because there was nothing to clean up.
    """
    removed = await push_service.remove_subscription(
        session, user_id=user.id, endpoint=(payload.endpoint if payload else None)
    )
    await session.commit()
    return ResponseEnvelope[PushUnsubscribeResult](
        data=PushUnsubscribeResult(removed=removed),
        message=(
            "This browser will no longer receive push notifications."
            if removed
            else "There was no push subscription to remove."
        ),
    )

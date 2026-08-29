from __future__ import annotations

from fastapi import APIRouter

from app.core.dependencies import CurrentUser, DbSession
from app.schemas.common import ResponseEnvelope
from app.schemas.user import UserPreferencesUpdate, UserRead
from app.services.audit_service import ActorType, record_audit_event

router = APIRouter(prefix="/users", tags=["users"])

PREFERENCES_UPDATED = "user.preferences_updated"
ONBOARDING_COMPLETED = "user.onboarding_completed"


@router.get(
    "/me",
    response_model=ResponseEnvelope[UserRead],
    summary="Profile of the authenticated user",
)
async def read_current_user(user: CurrentUser) -> ResponseEnvelope[UserRead]:
    return ResponseEnvelope[UserRead](data=UserRead.model_validate(user))


@router.patch(
    "/me/preferences",
    response_model=ResponseEnvelope[UserRead],
    summary="Update the authenticated user's own preferences",
)
async def update_my_preferences(
    payload: UserPreferencesUpdate,
    user: CurrentUser,
    session: DbSession,
) -> ResponseEnvelope[UserRead]:
    """Declared in  and deliberately left unbuilt until the settings page existed.

    Self-only, structurally: the row written is the one the dependency resolved from the verified
    token, and there is no parameter anywhere on this path naming another account. The schema
    carries no `roles`, no `email` and no `is_active` either, so a request cannot reach anything
    the identity provider owns even by asking.

    `notification_channel` means one thing from  onwards: whether this account ALSO
    receives an email. In-app is created either way, for everybody, because it is the platform's
    record rather than a channel. Push is not reachable from here at all - it is gated on the
    existence of a `PushSubscription`, which only the browser's own permission prompt can create.
    """
    fields = payload.model_dump(exclude_unset=True)
    changed: dict[str, str | None] = {}
    if "notification_channel" in fields and payload.notification_channel is not None:
        changed["notification_channel"] = payload.notification_channel
        user.notification_channel = payload.notification_channel
    if "default_stream_filter" in fields:
        changed["default_stream_filter"] = payload.default_stream_filter
        user.default_stream_filter = payload.default_stream_filter

    if changed:
        await session.flush()
        await record_audit_event(
            session,
            event_type=PREFERENCES_UPDATED,
            entity_type="user",
            entity_id=user.id,
            actor_id=user.id,
            actor_type=ActorType.USER,
            metadata={
                **changed,
                # Said plainly on the trail, because the column's name is broader than its
                # meaning: in-app is unconditional, this preference governs email only, and push
                # is governed by subscription and never by this write.
                "delivery_channels_available": ["in_app", "email", "push"],
                "push_governed_by": "push_subscription",
            },
        )
    await session.commit()

    return ResponseEnvelope[UserRead](
        data=UserRead.model_validate(user),
        message="Your preferences are saved." if changed else "Nothing to change.",
    )


@router.post(
    "/me/onboarding-complete",
    response_model=ResponseEnvelope[UserRead],
    summary="Record that this account has seen the first-login walkthrough",
)
async def complete_my_onboarding(
    user: CurrentUser,
    session: DbSession,
) -> ResponseEnvelope[UserRead]:
    """Called when the walkthrough is finished or dismissed. Both are the same fact.

    Self-only in the same structural way as the preferences write above: the row is the one the
    dependency resolved from the verified token, and the request carries no body at all, so there
    is nothing on this path that could name another account.

    Idempotent. A second call is a no-op rather than a conflict - a browser that retried the
    request, or two tabs finishing the tour at once, should not produce an error over a flag
    whose only job is to stop a tooltip reappearing.
    """
    if user.has_completed_onboarding:
        return ResponseEnvelope[UserRead](
            data=UserRead.model_validate(user),
            message="The walkthrough was already marked as seen.",
        )

    user.has_completed_onboarding = True
    await session.flush()
    await record_audit_event(
        session,
        event_type=ONBOARDING_COMPLETED,
        entity_type="user",
        entity_id=user.id,
        actor_id=user.id,
        actor_type=ActorType.USER,
        metadata={"has_completed_onboarding": True},
    )
    await session.commit()

    return ResponseEnvelope[UserRead](
        data=UserRead.model_validate(user),
        message="The walkthrough will not be shown again.",
    )

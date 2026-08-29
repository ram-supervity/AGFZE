"""`PATCH /users/me/preferences` - the endpoint declared in  and left unbuilt until now.

Self-only, structurally: the row written is the one the dependency resolved from the verified
token, and the schema has no field for an account identifier, a role, an email or an active flag.
The tests below prove both halves - that a caller can change their own preferences, and that
there is no shape of request that lets them reach anybody else's.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditEvent
from app.models.identity import User
from app.schemas.user import NOTIFICATION_CHANNELS, UserPreferencesUpdate
from tests.utils.admin import admin_user, purchase_user

pytestmark = pytest.mark.usefixtures("patched_jwks")

PREFERENCES = "/api/v1/users/me/preferences"
ME = "/api/v1/users/me"


async def test_a_user_updates_their_own_preferences(
    client: AsyncClient, db_session: AsyncSession, signed_in
):
    user, headers = await purchase_user(signed_in)
    user_id = user.id

    response = await client.patch(
        PREFERENCES,
        headers=headers,
        json={"notification_channel": "in_app", "default_stream_filter": "fa"},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["notification_channel"] == "in_app"
    assert data["default_stream_filter"] == "fa"

    db_session.expire_all()
    stored = await db_session.get(User, user_id)
    assert stored is not None
    assert stored.notification_channel == "in_app"
    assert stored.default_stream_filter == "fa"


async def test_a_preference_change_is_audited_and_says_what_the_column_governs(
    client: AsyncClient, db_session: AsyncSession, signed_in
):
    user, headers = await purchase_user(signed_in)
    user_id = user.id

    response = await client.patch(
        PREFERENCES, headers=headers, json={"notification_channel": "email"}
    )
    assert response.status_code == 200, response.text

    event = await db_session.scalar(
        select(AuditEvent).where(AuditEvent.event_type == "user.preferences_updated")
    )
    assert event is not None
    assert event.actor_id == user_id
    assert event.event_metadata["notification_channel"] == "email"
    # The column's name is broader than its meaning, so the trail spells the meaning out: all
    # three channels deliver from , but this write governs email only - in-app happens for
    # everybody regardless, and push is governed by the browser subscription.
    assert event.event_metadata["delivery_channels_available"] == ["in_app", "email", "push"]
    assert event.event_metadata["push_governed_by"] == "push_subscription"


async def test_every_recognised_channel_value_is_still_accepted(client: AsyncClient, signed_in):
    """`push` is accepted so a value stored before  still validates.

    It grants nothing on its own: push delivery is gated solely on an active `PushSubscription`,
    which only the browser's own permission prompt can create. Stored here it behaves as `in_app`.
    """
    _, headers = await purchase_user(signed_in)

    for channel in ("in_app", "email", "push"):
        response = await client.patch(
            PREFERENCES, headers=headers, json={"notification_channel": channel}
        )
        assert response.status_code == 200, channel
        assert response.json()["data"]["notification_channel"] == channel

    assert set(NOTIFICATION_CHANNELS) == {"in_app", "email", "push"}


async def test_an_unknown_channel_or_stream_is_refused(client: AsyncClient, signed_in):
    _, headers = await purchase_user(signed_in)

    assert (
        await client.patch(PREFERENCES, headers=headers, json={"notification_channel": "sms"})
    ).status_code == 422
    assert (
        await client.patch(PREFERENCES, headers=headers, json={"default_stream_filter": "metals"})
    ).status_code == 422


async def test_one_field_never_silently_resets_the_other(
    client: AsyncClient, db_session: AsyncSession, signed_in
):
    user, headers = await purchase_user(signed_in)
    user_id = user.id

    await client.patch(
        PREFERENCES,
        headers=headers,
        json={"notification_channel": "in_app", "default_stream_filter": "scrap"},
    )
    await client.patch(PREFERENCES, headers=headers, json={"notification_channel": "email"})

    db_session.expire_all()
    stored = await db_session.get(User, user_id)
    assert stored is not None
    assert stored.notification_channel == "email"
    # Untouched, because it was not in the payload.
    assert stored.default_stream_filter == "scrap"


async def test_the_stream_filter_can_be_cleared_back_to_everything(
    client: AsyncClient, db_session: AsyncSession, signed_in
):
    user, headers = await purchase_user(signed_in)
    user_id = user.id

    await client.patch(PREFERENCES, headers=headers, json={"default_stream_filter": "fa"})
    await client.patch(PREFERENCES, headers=headers, json={"default_stream_filter": None})

    db_session.expire_all()
    stored = await db_session.get(User, user_id)
    assert stored is not None
    assert stored.default_stream_filter is None


async def test_the_schema_has_no_field_that_could_reach_another_account(
    client: AsyncClient, db_session: AsyncSession, signed_in
):
    """The strongest form of the guarantee: there is nothing to ignore.

    A payload naming another user, a role or an active flag is not filtered out by the handler -
    those fields do not exist on the schema at all, so they never become anything the endpoint
    could act on.
    """
    caller, headers = await purchase_user(signed_in)
    other, _ = await admin_user(signed_in)
    caller_id, other_id = caller.id, other.id
    other_channel = other.notification_channel
    other_roles = list(other.roles)

    fields = set(UserPreferencesUpdate.model_fields)
    assert fields == {"notification_channel", "default_stream_filter"}

    response = await client.patch(
        PREFERENCES,
        headers=headers,
        json={
            "notification_channel": "in_app",
            "user_id": str(other_id),
            "id": str(other_id),
            "email": "attacker@example.com",
            "roles": ["admin"],
            "is_active": False,
        },
    )
    assert response.status_code == 200, response.text
    # The response is the caller's own row, not the account they named.
    assert response.json()["data"]["id"] == str(caller_id)

    db_session.expire_all()
    untouched = await db_session.get(User, other_id)
    assert untouched is not None
    assert untouched.notification_channel == other_channel
    assert list(untouched.roles) == other_roles
    assert untouched.is_active is True

    caller_row = await db_session.get(User, caller_id)
    assert caller_row is not None
    assert caller_row.email == "marco.purchase@agfze.ae"
    assert list(caller_row.roles) == ["purchase_user"]


async def test_the_preferences_endpoint_needs_a_token(client: AsyncClient):
    response = await client.patch(PREFERENCES, json={"notification_channel": "in_app"})
    assert response.status_code == 401


async def test_the_profile_read_still_answers_with_the_callers_own_row(
    client: AsyncClient, signed_in
):
    user, headers = await purchase_user(signed_in)
    response = await client.get(ME, headers=headers)
    assert response.status_code == 200
    assert response.json()["data"]["id"] == str(user.id)


# --- the first-login walkthrough -------------------------------------------------------------


async def test_a_new_account_has_not_seen_the_walkthrough(client: AsyncClient, signed_in) -> None:
    user, headers = await signed_in(
        "0a1b2c3d-0000-4000-8000-00000000e001",
        "onboarding.new@agfze.ae",
        "Nina Kovac",
        ["purchase_user"],
    )
    response = await client.get("/api/v1/users/me", headers=headers)

    assert response.status_code == 200
    assert response.json()["data"]["has_completed_onboarding"] is False
    assert user.has_completed_onboarding is False


async def test_completing_the_walkthrough_persists_and_is_audited(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    user, headers = await signed_in(
        "0a1b2c3d-0000-4000-8000-00000000e002",
        "onboarding.done@agfze.ae",
        "Tomas Weber",
        ["purchase_user"],
    )

    response = await client.post("/api/v1/users/me/onboarding-complete", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["has_completed_onboarding"] is True

    await db_session.refresh(user)
    assert user.has_completed_onboarding is True

    events = (
        await db_session.scalars(
            select(AuditEvent).where(AuditEvent.event_type == "user.onboarding_completed")
        )
    ).all()
    assert len(events) == 1
    assert events[0].actor_id == user.id


async def test_completing_it_twice_is_a_no_op_rather_than_a_conflict(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    """Two tabs finishing the tour at once must not produce an error over a tooltip flag."""
    _user, headers = await signed_in(
        "0a1b2c3d-0000-4000-8000-00000000e003",
        "onboarding.twice@agfze.ae",
        "Ines Duarte",
        ["purchase_user"],
    )

    first = await client.post("/api/v1/users/me/onboarding-complete", headers=headers)
    second = await client.post("/api/v1/users/me/onboarding-complete", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["data"]["has_completed_onboarding"] is True

    # One event, not two: the second call recorded nothing because nothing changed.
    events = (
        await db_session.scalars(
            select(AuditEvent).where(AuditEvent.event_type == "user.onboarding_completed")
        )
    ).all()
    assert len(events) == 1


async def test_the_walkthrough_flag_cannot_be_set_on_another_account(
    client: AsyncClient, signed_in
) -> None:
    """No body, no parameter, no path segment naming an account. Self-only by construction."""
    _user, headers = await signed_in(
        "0a1b2c3d-0000-4000-8000-00000000e004",
        "onboarding.self@agfze.ae",
        "Karim Haddad",
        ["purchase_user"],
    )

    # The route takes no identifier at all, so the only account it can touch is the token's.
    response = await client.post(
        "/api/v1/users/me/onboarding-complete",
        headers=headers,
        json={"user_id": "11111111-2222-4333-8444-555555555555"},
    )
    assert response.status_code == 200
    assert response.json()["data"]["email"] == "onboarding.self@agfze.ae"


async def test_signing_in_alone_never_marks_the_walkthrough_as_seen(
    client: AsyncClient, signed_in
) -> None:
    _user, headers = await signed_in(
        "0a1b2c3d-0000-4000-8000-00000000e005",
        "onboarding.readonly@agfze.ae",
        "Priya Raman",
        ["sales_user"],
    )

    for _ in range(3):
        response = await client.get("/api/v1/users/me", headers=headers)
        assert response.json()["data"]["has_completed_onboarding"] is False

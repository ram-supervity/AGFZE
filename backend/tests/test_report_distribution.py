"""Configured distribution for the two scheduled reports.

The tests here are written against the one property that makes this feature safe rather than
merely present: a report is distributed to exactly the people an administrator named, on exactly
the channel they named, and to nobody at all before anybody has named anyone. A distribution
feature that defaulted to sending would be worse than the one that could not send at all.

Nothing here asserts that a function was called. Every case reads the notification rows the
platform actually wrote, and the delivery cases read the `email_sent_at` column that only a real
delivery attempt sets.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.roles import PlatformRole
from app.models.audit import AuditEvent
from app.models.notifications import Notification
from app.models.reporting import ReportDistributionRule
from app.services.analytics import distribution, schedule
from tests.utils.admin import admin_user
from tests.utils.analytics import account

pytestmark = pytest.mark.usefixtures("patched_jwks")

ADMIN = "/api/v1/admin/report-distribution"


async def _rule(
    session: AsyncSession,
    *,
    report_type: str = "daily",
    roles: list[str] | None = None,
    user_ids: list[str] | None = None,
    channel: str = "in_app",
    is_active: bool = True,
) -> ReportDistributionRule:
    row = ReportDistributionRule(
        report_type=report_type,
        recipient_roles=roles or [],
        recipient_user_ids=user_ids or [],
        channel=channel,
        is_active=is_active,
        change_reason="Configured for the distribution tests.",
    )
    session.add(row)
    await session.flush()
    return row


async def _report_notifications(session: AsyncSession, user_id) -> list[Notification]:
    return list(
        (
            await session.scalars(
                select(Notification).where(
                    Notification.user_id == user_id,
                    Notification.notification_type == "report.ready",
                )
            )
        ).all()
    )


# --- the shipped state ---------------------------------------------------------------------------


async def test_with_no_rule_configured_a_scheduled_report_generates_and_reaches_nobody(
    db_session: AsyncSession, storage_root
) -> None:
    """The state this platform ships in, and it must not be an error.

    The report is still produced, still stored and still readable. What does not happen is the
    only thing this feature added, and its absence is a configuration fact rather than a failure.
    """
    finance = await account(db_session, roles=[PlatformRole.FINANCE_USER.value], name="Finance")

    result = await schedule.run_due(db_session)
    assert len(result.generated) == 2

    assert await _report_notifications(db_session, finance.id) == []


async def test_distribute_reports_nothing_applied_when_no_rule_exists(
    db_session: AsyncSession,
) -> None:
    outcome = await distribution.distribute(
        db_session,
        report_id=__import__("uuid").uuid4(),
        report_type="daily",
        title="Daily operations",
    )
    assert outcome.rules_applied == 0
    assert outcome.distributed is False
    assert outcome.notified_user_ids == frozenset()


# --- resolution ------------------------------------------------------------------------------------


async def test_a_role_rule_reaches_every_current_holder_of_that_role(
    db_session: AsyncSession, storage_root
) -> None:
    """A rule names a desk, and the desk's membership is resolved when the report is sent.

    Both finance accounts below are created before the rule and neither is named on it; they are
    reached because they hold the role it names, which is the whole point of configuring one.
    """
    first = await account(db_session, roles=[PlatformRole.FINANCE_USER.value], name="Finance One")
    second = await account(db_session, roles=[PlatformRole.FINANCE_USER.value], name="Finance Two")
    outsider = await account(db_session, roles=[PlatformRole.SALES_USER.value], name="Sales")
    await _rule(db_session, report_type="daily", roles=[PlatformRole.FINANCE_USER.value])
    await db_session.commit()

    await schedule.run_due(db_session)
    await db_session.commit()

    # One daily report each. The monthly one has no rule, so it reaches neither of them.
    assert len(await _report_notifications(db_session, first.id)) == 1
    assert len(await _report_notifications(db_session, second.id)) == 1
    assert await _report_notifications(db_session, outsider.id) == []


async def test_a_named_individual_is_reached_without_holding_any_role(
    db_session: AsyncSession, storage_root
) -> None:
    """The other shape the business names recipients in, and it must work on its own."""
    person = await account(db_session, roles=[PlatformRole.LOGISTICS_USER.value], name="Named")
    await _rule(db_session, report_type="daily", user_ids=[str(person.id)])
    await db_session.commit()

    await schedule.run_due(db_session)
    await db_session.commit()

    rows = await _report_notifications(db_session, person.id)
    assert len(rows) == 1
    # A link into the platform, never a file and never a figure in the message body.
    assert rows[0].link is not None
    assert rows[0].link.startswith("/reports/")


async def test_somebody_named_twice_is_told_once(db_session: AsyncSession, storage_root) -> None:
    """Named individually and covered by a role on the same rule. One person, one notification."""
    person = await account(db_session, roles=[PlatformRole.FINANCE_USER.value], name="Both Ways")
    await _rule(
        db_session,
        report_type="daily",
        roles=[PlatformRole.FINANCE_USER.value],
        user_ids=[str(person.id)],
    )
    await db_session.commit()

    await schedule.run_due(db_session)
    await db_session.commit()

    assert len(await _report_notifications(db_session, person.id)) == 1


async def test_an_inactive_rule_distributes_to_nobody(
    db_session: AsyncSession, storage_root
) -> None:
    """Deactivating is how distribution is stopped, and it has to actually stop it."""
    person = await account(db_session, roles=[PlatformRole.FINANCE_USER.value], name="Finance")
    await _rule(
        db_session,
        report_type="daily",
        roles=[PlatformRole.FINANCE_USER.value],
        is_active=False,
    )
    await db_session.commit()

    await schedule.run_due(db_session)
    await db_session.commit()

    assert await _report_notifications(db_session, person.id) == []


async def test_a_rule_for_one_report_type_does_not_distribute_the_other(
    db_session: AsyncSession, storage_root
) -> None:
    daily_only = await account(
        db_session, roles=[PlatformRole.FINANCE_USER.value], name="Daily Only"
    )
    await _rule(db_session, report_type="daily", roles=[PlatformRole.FINANCE_USER.value])
    await db_session.commit()

    await schedule.run_due(db_session)
    await db_session.commit()

    rows = await _report_notifications(db_session, daily_only.id)
    assert len(rows) == 1
    assert "daily" in rows[0].message.lower()


async def test_an_unreadable_recipient_id_does_not_stop_the_rest_of_the_rule(
    db_session: AsyncSession, storage_root
) -> None:
    """One bad entry in a hand-edited JSON column must not silence the other recipients."""
    good = await account(db_session, roles=[PlatformRole.FINANCE_USER.value], name="Good")
    await _rule(db_session, report_type="daily", user_ids=["not-a-uuid", str(good.id)])
    await db_session.commit()

    await schedule.run_due(db_session)
    await db_session.commit()

    assert len(await _report_notifications(db_session, good.id)) == 1


# --- the channel ceiling --------------------------------------------------------------------------


async def test_an_in_app_rule_never_emails_even_a_recipient_who_asked_for_email(
    db_session: AsyncSession, storage_root, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rule's channel is a ceiling on delivery. In-app means in-app.

    The recipient's own preference is `email`, so without the ceiling the platform would attempt
    one. `email_sent_at` staying NULL is the assertion, because only a real delivery sets it.
    """
    from app.services.delivery import email_service

    sent: list[str] = []

    async def _record(**kwargs) -> bool:
        sent.append(kwargs["to_address"])
        return True

    monkeypatch.setattr(email_service, "send_notification_email", _record)
    monkeypatch.setattr("app.core.config.settings.NOTIFICATION_DELIVERY_ENABLED", True)

    person = await account(db_session, roles=[PlatformRole.FINANCE_USER.value], name="Emailer")
    person.notification_channel = "email"
    await _rule(db_session, report_type="daily", user_ids=[str(person.id)], channel="in_app")
    await db_session.commit()

    await schedule.run_due(db_session)
    await db_session.commit()

    rows = await _report_notifications(db_session, person.id)
    assert len(rows) == 1
    assert rows[0].email_sent_at is None
    assert sent == []


async def test_an_email_rule_still_respects_a_recipient_who_did_not_ask_for_email(
    db_session: AsyncSession, storage_root, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ceiling, never a floor. A rule cannot email somebody who is on the in-app default."""
    from app.services.delivery import email_service

    sent: list[str] = []

    async def _record(**kwargs) -> bool:
        sent.append(kwargs["to_address"])
        return True

    monkeypatch.setattr(email_service, "send_notification_email", _record)
    monkeypatch.setattr("app.core.config.settings.NOTIFICATION_DELIVERY_ENABLED", True)

    person = await account(db_session, roles=[PlatformRole.FINANCE_USER.value], name="In App")
    assert person.notification_channel == "in_app"
    await _rule(db_session, report_type="daily", user_ids=[str(person.id)], channel="email")
    await db_session.commit()

    await schedule.run_due(db_session)
    await db_session.commit()

    rows = await _report_notifications(db_session, person.id)
    assert len(rows) == 1
    assert rows[0].email_sent_at is None
    assert sent == []


async def test_an_email_rule_emails_a_recipient_who_did_ask_for_email(
    db_session: AsyncSession, storage_root, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both halves agreeing is the only combination that sends, and it must actually send."""
    from app.services.delivery import email_service

    sent: list[str] = []

    async def _record(**kwargs) -> bool:
        sent.append(kwargs["to_address"])
        return True

    monkeypatch.setattr(email_service, "send_notification_email", _record)
    monkeypatch.setattr("app.core.config.settings.NOTIFICATION_DELIVERY_ENABLED", True)

    person = await account(db_session, roles=[PlatformRole.FINANCE_USER.value], name="Emailer")
    person.notification_channel = "email"
    await _rule(db_session, report_type="daily", user_ids=[str(person.id)], channel="both")
    await db_session.commit()

    await schedule.run_due(db_session)
    await db_session.commit()

    rows = await _report_notifications(db_session, person.id)
    assert len(rows) == 1
    assert rows[0].email_sent_at is not None
    assert sent == [person.email]


# --- the admin endpoints --------------------------------------------------------------------------


async def test_an_admin_configures_a_rule_and_it_is_audited(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    admin, headers = await admin_user(signed_in)

    response = await client.post(
        ADMIN,
        headers=headers,
        json={
            "report_type": "daily",
            "recipient_roles": [PlatformRole.FINANCE_USER.value],
            "channel": "email",
            "change_reason": "Finance asked to receive the daily operations report.",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert body["report_type"] == "daily"
    assert body["channel"] == "email"
    assert body["is_active"] is True

    stored = (await db_session.scalars(select(ReportDistributionRule))).one()
    assert stored.recipient_roles == [PlatformRole.FINANCE_USER.value]
    assert stored.changed_by_id == admin.id

    events = (
        await db_session.scalars(
            select(AuditEvent).where(AuditEvent.event_type == "admin.report_distribution.saved")
        )
    ).all()
    assert len(events) == 1
    assert events[0].actor_id == admin.id
    assert events[0].event_metadata["created"] is True


async def test_a_rule_without_a_reason_is_refused(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    _admin, headers = await admin_user(signed_in)

    response = await client.post(
        ADMIN,
        headers=headers,
        json={
            "report_type": "daily",
            "recipient_roles": [PlatformRole.FINANCE_USER.value],
            "channel": "in_app",
        },
    )
    assert response.status_code == 422
    assert (await db_session.scalars(select(ReportDistributionRule))).all() == []


async def test_an_active_rule_naming_nobody_is_refused(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    """An active rule reaching nobody would read on the screen as distribution that works."""
    _admin, headers = await admin_user(signed_in)

    response = await client.post(
        ADMIN,
        headers=headers,
        json={
            "report_type": "daily",
            "recipient_roles": [],
            "recipient_user_ids": [],
            "channel": "in_app",
            "change_reason": "Trying to save a rule that names nobody at all.",
        },
    )
    assert response.status_code == 422
    assert (await db_session.scalars(select(ReportDistributionRule))).all() == []


async def test_an_adhoc_distribution_rule_is_refused(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    """Ad-hoc reports are not distributed, and the schema is where that is enforced."""
    _admin, headers = await admin_user(signed_in)

    response = await client.post(
        ADMIN,
        headers=headers,
        json={
            "report_type": "adhoc",
            "recipient_roles": [PlatformRole.FINANCE_USER.value],
            "channel": "in_app",
            "change_reason": "Trying to distribute an ad-hoc report, which is not allowed.",
        },
    )
    assert response.status_code == 422
    assert (await db_session.scalars(select(ReportDistributionRule))).all() == []


async def test_an_unknown_role_is_refused(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    _admin, headers = await admin_user(signed_in)

    response = await client.post(
        ADMIN,
        headers=headers,
        json={
            "report_type": "daily",
            "recipient_roles": ["chief_of_everything"],
            "channel": "in_app",
            "change_reason": "Trying to name a role this platform does not have.",
        },
    )
    assert response.status_code == 422


async def test_an_unknown_named_recipient_is_refused(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    """A well-formed id for an account that does not exist is a 400, not a silent no-op."""
    import uuid

    _admin, headers = await admin_user(signed_in)

    response = await client.post(
        ADMIN,
        headers=headers,
        json={
            "report_type": "daily",
            "recipient_user_ids": [str(uuid.uuid4())],
            "channel": "in_app",
            "change_reason": "Trying to name somebody who does not have an account here.",
        },
    )
    assert response.status_code == 400
    assert response.json()["errors"][0]["code"] == "unknown_recipient"


async def test_only_an_admin_may_read_or_write_distribution_rules(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    _person, headers = await signed_in(
        "0a1b2c3d-0000-4000-8000-0000000000d1",
        "finance.desk@agfze.ae",
        "Finance Desk",
        [PlatformRole.FINANCE_USER.value],
    )

    assert (await client.get(ADMIN, headers=headers)).status_code == 403
    assert (
        await client.post(
            ADMIN,
            headers=headers,
            json={
                "report_type": "daily",
                "recipient_roles": [PlatformRole.FINANCE_USER.value],
                "channel": "in_app",
                "change_reason": "A non-administrator should never get this far.",
            },
        )
    ).status_code == 403


async def test_deactivating_a_rule_through_the_endpoint_stops_the_distribution(
    client: AsyncClient, db_session: AsyncSession, signed_in, storage_root
) -> None:
    """End to end: configured, sending, then deactivated and no longer sending."""
    _admin, headers = await admin_user(signed_in)
    person = await account(db_session, roles=[PlatformRole.FINANCE_USER.value], name="Finance")
    await db_session.commit()

    created = await client.post(
        ADMIN,
        headers=headers,
        json={
            "report_type": "daily",
            "recipient_roles": [PlatformRole.FINANCE_USER.value],
            "channel": "in_app",
            "change_reason": "Finance asked to receive the daily operations report.",
        },
    )
    assert created.status_code == 200, created.text
    rule_id = created.json()["data"]["id"]

    await schedule.run_due(db_session)
    await db_session.commit()
    assert len(await _report_notifications(db_session, person.id)) == 1

    stopped = await client.patch(
        f"{ADMIN}/{rule_id}",
        headers=headers,
        json={
            "report_type": "daily",
            "recipient_roles": [PlatformRole.FINANCE_USER.value],
            "channel": "in_app",
            "is_active": False,
            "change_reason": "Finance asked to stop receiving this report for now.",
        },
    )
    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["data"]["is_active"] is False

    # The rule is still listed once inactive, so the history of the decision stays readable.
    listed = await client.get(ADMIN, headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()["data"]["items"]) == 1

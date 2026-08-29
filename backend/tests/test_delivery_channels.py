"""Email and push delivery, proved through Step 9's own five trigger points.

The thing this file guards hardest is stated first, because it is the architectural rule of the
step: **not one of the five trigger points changed**. Email and push reach every one of them
through the internals of `notification_service.notify`, which is the seam this platform was built
around. `test_no_trigger_point_module_knows_anything_about_a_delivery_channel` reads the source of
all four modules that call a trigger and fails if any of them so much as mentions a channel.

Everything else follows from Section 9.4's rule that the three channels are independent:

* in-app is created for everybody, always, whatever the preference column says;
* email is additional, and governed by `notification_channel`;
* push is additional, and governed by nothing except whether a subscription exists.
"""

from __future__ import annotations

import json
from typing import ClassVar

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.roles import PlatformRole
from app.models.audit import AuditEvent
from app.models.enums import (
    ApprovalDecision,
    ExceptionCategory,
    ExceptionPriority,
    IntegrationJobStatus,
    IntegrationTargetSystem,
    TransactionStatus,
)
from app.models.governance import ApprovalTask
from app.models.integration import IntegrationJob
from app.models.notifications import Notification
from app.models.push import PushSubscription
from app.services.delivery import email_service, push_service
from app.services.governance import approval_service, hooks
from app.services.integration import integration_service
from app.services.integration.adapters import IntegrationOutcome
from tests.utils.admin import admin_user, approver_user, purchase_user
from tests.utils.delivery import (
    FakePushService,
    FakeRelay,
    install_push,
    install_relay,
    record_backoff,
    set_channel,
    subscribe,
)
from tests.utils.governance import seeded_transaction

pytestmark = pytest.mark.usefixtures("patched_jwks")

NOTIFICATIONS = "/api/v1/notifications"
TRANSACTIONS = "/api/v1/transactions"
APPROVALS = "/api/v1/approvals"

PUSH_ENDPOINT = "https://push.test/endpoint/marco-laptop"

# What a browser actually hands over: a point that is genuinely on P-256, and a 16-byte secret.
# Registration verifies both, so a placeholder string will not do here.
P256DH = (
    "BEl62iUYgUivxIkv69yViEuiBIa-Ib9-SkvMeAtA3LFgDzkrxZJjSgSnfckjBJuBkr3qBUYIHBQFLXYp5Nksh8U"
)
P256DH_ROTATED = (
    "BEKw6DaJNkCy4HB2WQTDM2Alc8Egegqz8QRK0WYGK396cRY6tsInTzkptrimnJcTr0N1NHbCykLnY5iHZ_OMn8s"
)
AUTH_SECRET = "8eDyX_uCN0XRhSbY5hs7Hg"
AUTH_SECRET_ROTATED = "tBHItJI5svbpez7KI4CCXg"
SECOND_ENDPOINT = "https://push.test/endpoint/marco-phone"


async def rows_for(session: AsyncSession, user_id) -> list[Notification]:
    return list(
        (
            await session.scalars(
                select(Notification)
                .where(Notification.user_id == user_id)
                .order_by(Notification.created_at)
            )
        ).all()
    )


# --- the rule this whole step rests on -----------------------------------------------------------


def test_no_trigger_point_module_knows_anything_about_a_delivery_channel():
    """The duplication this step exists to avoid, checked by reading the source.

    Every one of Step 9's five triggers gained email and push in this step. If any of them gained
    it by having delivery code pasted into the module that raises it, the platform would have five
    answers to "how is this delivered" instead of one - and they would drift the first time one of
    them was edited. These four modules hold all five call sites and must know nothing but
    `notify_*`.
    """
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1] / "app"
    modules = [
        root / "services" / "governance" / "hooks.py",
        root / "services" / "governance" / "approval_service.py",
        root / "services" / "integration" / "integration_service.py",
        root / "services" / "analytics" / "schedule.py",
    ]
    forbidden = ("email_service", "push_service", "smtp", "webpush", "vapid", "PushSubscription")
    for module in modules:
        source = module.read_text()
        assert module.exists(), module
        for token in forbidden:
            assert token.lower() not in source.lower(), f"{module.name} mentions {token}"


def test_the_notification_table_records_both_deliveries():
    """The columns Step 9 withheld, arriving with the code that writes them."""
    columns = set(Notification.__table__.columns.keys())
    assert "email_sent_at" in columns
    assert "push_sent_at" in columns


# --- the five trigger points, each reaching both channels ----------------------------------------


async def test_a_new_exception_emails_and_pushes_the_owning_desk(
    db_session: AsyncSession, signed_in, monkeypatch
):
    user, _ = await purchase_user(signed_in)
    await set_channel(db_session, user, "email")
    await subscribe(db_session, user.id, PUSH_ENDPOINT)
    await db_session.commit()

    relay = install_relay(monkeypatch)
    push = install_push(monkeypatch)
    transaction = await seeded_transaction(db_session, validate=False)

    case = await hooks.open_case(
        db_session,
        category=ExceptionCategory.QUANTITY_VARIATION_OUTSIDE_TOLERANCE.value,
        owner_role=PlatformRole.PURCHASE_USER.value,
        priority=ExceptionPriority.HIGH.value,
        summary="Quantity is 4% under the contracted figure.",
        transaction_id=transaction.id,
    )
    await db_session.commit()
    assert case is not None

    rows = await rows_for(db_session, user.id)
    assert len(rows) == 1
    assert rows[0].email_sent_at is not None
    assert rows[0].push_sent_at is not None

    assert relay.recipients == [user.email]
    text, html = relay.for_subject("exception")
    assert "An exception needs attention" in html
    assert f"https://command-centre.agfze.test/exceptions/{case.id}" in html
    assert f"https://command-centre.agfze.test/exceptions/{case.id}" in text

    payload = json.loads(push.delivered[0][1])
    assert payload["title"] == "Exception needs attention"
    assert payload["url"].endswith(f"/exceptions/{case.id}")


async def test_a_new_approval_task_emails_and_pushes_the_approver(
    db_session: AsyncSession, signed_in, monkeypatch
):
    submitter, _ = await purchase_user(signed_in)
    approver, _ = await approver_user(signed_in)
    await set_channel(db_session, approver, "email")
    await subscribe(db_session, approver.id, PUSH_ENDPOINT)
    await db_session.commit()

    relay = install_relay(monkeypatch)
    push = install_push(monkeypatch)
    transaction = await seeded_transaction(db_session, validate=False)

    await approval_service.create_task(db_session, transaction, requested_by_id=submitter.id)
    await db_session.commit()

    rows = await rows_for(db_session, approver.id)
    assert len(rows) == 1
    assert rows[0].email_sent_at is not None and rows[0].push_sent_at is not None
    assert relay.recipients == [approver.email]
    assert "A decision is waiting on you" in relay.for_subject("decision is waiting")[1]
    assert json.loads(push.delivered[0][1])["title"] == "Decision waiting on you"

    # The person who asked for the decision is told nothing, on any channel.
    assert await rows_for(db_session, submitter.id) == []


async def test_a_decision_emails_and_pushes_the_submitter(
    client: AsyncClient, db_session: AsyncSession, signed_in, monkeypatch
):
    submitter, purchase_headers = await purchase_user(signed_in)
    _, approver_headers = await approver_user(signed_in)
    await set_channel(db_session, submitter, "email")
    await subscribe(db_session, submitter.id, PUSH_ENDPOINT)
    await db_session.commit()
    submitter_id = submitter.id

    relay = install_relay(monkeypatch)
    push = install_push(monkeypatch)

    transaction = await seeded_transaction(db_session)
    submitted = await client.post(
        f"{TRANSACTIONS}/{transaction.id}/submit", headers=purchase_headers, json={}
    )
    assert submitted.status_code == 200, submitted.text
    task = await db_session.scalar(
        select(ApprovalTask).where(ApprovalTask.transaction_id == transaction.id)
    )
    assert task is not None

    decided = await client.post(
        f"{APPROVALS}/{task.id}/decide",
        headers=approver_headers,
        json={"decision": ApprovalDecision.APPROVED.value},
    )
    assert decided.status_code == 200, decided.text

    db_session.expire_all()
    decisions = [
        row
        for row in await rows_for(db_session, submitter_id)
        if row.notification_type == "approval.decided"
    ]
    assert len(decisions) == 1
    assert decisions[0].email_sent_at is not None
    assert decisions[0].push_sent_at is not None
    assert "Your submission has been decided" in relay.for_subject("decided")[1]
    assert json.loads(push.delivered[-1][1])["type"] == "approval.decided"


async def test_an_integration_job_needing_a_person_emails_and_pushes_admin(
    db_session: AsyncSession, signed_in, monkeypatch
):
    admin, _ = await admin_user(signed_in)
    await set_channel(db_session, admin, "email")
    await subscribe(db_session, admin.id, PUSH_ENDPOINT)
    await db_session.commit()

    relay = install_relay(monkeypatch)
    push = install_push(monkeypatch)

    transaction = await seeded_transaction(db_session, validate=False)
    transaction.status = TransactionStatus.APPROVED.value
    job = IntegrationJob(
        transaction_id=transaction.id,
        target_system=IntegrationTargetSystem.SAP.value,
        status=IntegrationJobStatus.QUEUED.value,
        attempt_count=99,
    )
    db_session.add(job)
    await db_session.flush()

    await integration_service._apply_failure(
        db_session,
        job,
        transaction,
        IntegrationOutcome.failed("SAP rejected the posting.", retryable=False),
    )
    await db_session.commit()

    rows = [
        row
        for row in await rows_for(db_session, admin.id)
        if row.notification_type == "integration.attention"
    ]
    assert len(rows) == 1
    assert rows[0].email_sent_at is not None and rows[0].push_sent_at is not None
    text, html = relay.for_subject("integration job")
    assert "An integration job needs a person" in html
    # A downstream posting is not AI-derived, so this is the one notification that carries no
    # AI disclaimer.
    assert "AI-extracted information" not in html
    assert "AI-extracted information" not in text
    # A failed posting also opens a support-owned exception, so this administrator is genuinely
    # told two things. The push that matters is the one about the posting.
    types = [json.loads(payload)["type"] for _, payload in push.delivered]
    assert "integration.attention" in types


async def test_a_scheduled_report_emails_and_pushes_its_recipients(
    db_session: AsyncSession, signed_in, monkeypatch, storage_root
):
    from app.services.analytics import schedule

    admin, _ = await admin_user(signed_in)
    approver, _ = await approver_user(signed_in)
    await set_channel(db_session, admin, "email")
    await subscribe(db_session, approver.id, PUSH_ENDPOINT)
    await db_session.commit()

    relay = install_relay(monkeypatch)
    push = install_push(monkeypatch)

    result = await schedule.run_due(db_session)
    assert len(result.generated) == 2
    await db_session.commit()

    admin_rows = [
        row
        for row in await rows_for(db_session, admin.id)
        if row.notification_type == "report.ready"
    ]
    approver_rows = [
        row
        for row in await rows_for(db_session, approver.id)
        if row.notification_type == "report.ready"
    ]
    # The administrator is on email and has no browser subscribed; the approver is the other way
    # round. Neither arrangement is a setting the other can see.
    assert len(admin_rows) == 2
    assert all(row.email_sent_at is not None and row.push_sent_at is None for row in admin_rows)
    assert all(row.email_sent_at is None and row.push_sent_at is not None for row in approver_rows)
    assert relay.recipients == [admin.email, admin.email]
    assert push.endpoints == [PUSH_ENDPOINT, PUSH_ENDPOINT]


# --- Section 9.4: the three channels, and their independence -------------------------------------


async def test_in_app_is_created_for_everybody_regardless_of_channel_or_subscription(
    db_session: AsyncSession, signed_in, monkeypatch
):
    from app.services import notification_service

    user, _ = await purchase_user(signed_in)
    await db_session.commit()
    relay = install_relay(monkeypatch)
    push = install_push(monkeypatch)

    created = await notification_service.notify(
        db_session,
        notification_type=notification_service.NotificationType.EXCEPTION_OPENED,
        message="In-app is not optional.",
        user_ids=[user.id],
    )
    await db_session.commit()

    assert len(created) == 1
    assert created[0].email_sent_at is None
    assert created[0].push_sent_at is None
    assert relay.sent == []
    assert push.delivered == []


async def test_a_user_can_be_on_all_three_channels_at_once(
    db_session: AsyncSession, signed_in, monkeypatch
):
    from app.services import notification_service

    user, _ = await purchase_user(signed_in)
    await set_channel(db_session, user, "email")
    await subscribe(db_session, user.id, PUSH_ENDPOINT)
    await subscribe(db_session, user.id, SECOND_ENDPOINT)
    await db_session.commit()

    relay = install_relay(monkeypatch)
    push = install_push(monkeypatch)

    created = await notification_service.notify(
        db_session,
        notification_type=notification_service.NotificationType.APPROVAL_REQUESTED,
        message="All three at once.",
        link="/approvals/abc",
        user_ids=[user.id],
    )
    await db_session.commit()

    row = created[0]
    assert row.email_sent_at is not None
    assert row.push_sent_at is not None
    assert len(relay.sent) == 1
    # Every browser this person subscribed, not just the first.
    assert sorted(push.endpoints) == sorted([PUSH_ENDPOINT, SECOND_ENDPOINT])


async def test_push_is_gated_on_the_subscription_and_never_on_the_preference(
    db_session: AsyncSession, signed_in, monkeypatch
):
    """The prohibition stated in Section 15, proved from both directions.

    A user left on the `in_app` default who has granted the browser permission receives push. A
    user set to `email` who never granted it does not, however much the column implies otherwise.
    """
    from app.services import notification_service

    subscribed_only, _ = await purchase_user(signed_in)
    email_only, _ = await approver_user(signed_in)
    await subscribe(db_session, subscribed_only.id, PUSH_ENDPOINT)
    await set_channel(db_session, email_only, "email")
    await db_session.commit()
    assert subscribed_only.notification_channel == "in_app"

    relay = install_relay(monkeypatch)
    push = install_push(monkeypatch)

    created = await notification_service.notify(
        db_session,
        notification_type=notification_service.NotificationType.REPORT_READY,
        message="Two people, two entirely separate answers.",
        user_ids=[subscribed_only.id, email_only.id],
    )
    await db_session.commit()

    by_user = {row.user_id: row for row in created}
    assert by_user[subscribed_only.id].push_sent_at is not None
    assert by_user[subscribed_only.id].email_sent_at is None
    assert by_user[email_only.id].push_sent_at is None
    assert by_user[email_only.id].email_sent_at is not None
    assert push.endpoints == [PUSH_ENDPOINT]
    assert relay.recipients == [email_only.email]


async def test_a_channel_value_of_push_grants_no_email_and_no_push_by_itself(
    db_session: AsyncSession, signed_in, monkeypatch
):
    """`push` stored in the column is a pre-Step-10 value. It behaves as `in_app`."""
    from app.services import notification_service

    user, _ = await purchase_user(signed_in)
    await set_channel(db_session, user, "push")
    await db_session.commit()

    relay = install_relay(monkeypatch)
    push = install_push(monkeypatch)
    created = await notification_service.notify(
        db_session,
        notification_type=notification_service.NotificationType.EXCEPTION_OPENED,
        message="A stored value is not a permission.",
        user_ids=[user.id],
    )
    await db_session.commit()

    assert created[0].email_sent_at is None and created[0].push_sent_at is None
    assert relay.sent == [] and push.delivered == []


# --- dead subscriptions --------------------------------------------------------------------------


@pytest.mark.parametrize("status", [410, 404])
async def test_a_dead_subscription_is_removed_rather_than_retried(
    db_session: AsyncSession, signed_in, monkeypatch, status: int
):
    from app.services import notification_service

    user, _ = await purchase_user(signed_in)
    await subscribe(db_session, user.id, PUSH_ENDPOINT)
    await subscribe(db_session, user.id, SECOND_ENDPOINT)
    await db_session.commit()

    push = install_push(monkeypatch, FakePushService(status_by_endpoint={PUSH_ENDPOINT: status}))

    for index in range(3):
        await notification_service.notify(
            db_session,
            notification_type=notification_service.NotificationType.APPROVAL_REQUESTED,
            message=f"Notification {index}.",
            user_ids=[user.id],
        )
    await db_session.commit()

    remaining = [
        row.endpoint
        for row in (
            await db_session.scalars(
                select(PushSubscription).where(PushSubscription.user_id == user.id)
            )
        ).all()
    ]
    assert remaining == [SECOND_ENDPOINT]
    # Tried once, found gone, deleted - not tried again for the two notifications that followed.
    assert push.attempts_by_endpoint[PUSH_ENDPOINT] == 1
    assert push.attempts_by_endpoint[SECOND_ENDPOINT] == 3


async def test_a_transient_push_failure_keeps_the_subscription(
    db_session: AsyncSession, signed_in, monkeypatch
):
    from app.services import notification_service

    user, _ = await purchase_user(signed_in)
    await subscribe(db_session, user.id, PUSH_ENDPOINT)
    await db_session.commit()

    install_push(monkeypatch, FakePushService(status_by_endpoint={PUSH_ENDPOINT: 503}))
    created = await notification_service.notify(
        db_session,
        notification_type=notification_service.NotificationType.EXCEPTION_OPENED,
        message="The push service is having a bad afternoon.",
        user_ids=[user.id],
    )
    await db_session.commit()

    assert created[0].push_sent_at is None
    assert await db_session.scalar(
        select(PushSubscription).where(PushSubscription.user_id == user.id)
    )


# --- email retry, and the failure that changes nothing --------------------------------------------


async def test_email_retries_three_times_with_backoff_and_then_stops(
    db_session: AsyncSession, signed_in, monkeypatch
):
    from app.services import notification_service

    user, _ = await purchase_user(signed_in)
    await set_channel(db_session, user, "email")
    await db_session.commit()

    monkeypatch.setattr(settings, "EMAIL_RETRY_BASE_SECONDS", 2.0)
    waits = record_backoff(monkeypatch)
    relay = install_relay(monkeypatch, FakeRelay(fail_times=99))
    monkeypatch.setattr(settings, "EMAIL_RETRY_BASE_SECONDS", 2.0)

    created = await notification_service.notify(
        db_session,
        notification_type=notification_service.NotificationType.EXCEPTION_OPENED,
        message="The relay is down.",
        user_ids=[user.id],
    )
    await db_session.commit()

    assert relay.attempts == 3
    # Backoff between attempts, not before the first and not after the last.
    assert waits == [2.0, 4.0]
    assert created[0].email_sent_at is None
    # The failure is on the audit trail, so it is visible on /admin/audit rather than only in a
    # log stream nobody on this platform can open.
    failures = (
        await db_session.scalars(
            select(AuditEvent).where(AuditEvent.event_type == "notification.email_failed")
        )
    ).all()
    assert len(list(failures)) == 1


async def test_a_transient_relay_failure_is_retried_and_then_succeeds(
    db_session: AsyncSession, signed_in, monkeypatch
):
    from app.services import notification_service

    user, _ = await purchase_user(signed_in)
    await set_channel(db_session, user, "email")
    await db_session.commit()

    record_backoff(monkeypatch)
    relay = install_relay(monkeypatch, FakeRelay(fail_times=2))

    created = await notification_service.notify(
        db_session,
        notification_type=notification_service.NotificationType.REPORT_READY,
        message="The relay came back.",
        user_ids=[user.id],
    )
    await db_session.commit()

    assert relay.attempts == 3
    assert len(relay.sent) == 1
    assert created[0].email_sent_at is not None


async def test_a_failed_delivery_never_reverses_the_business_event(
    client: AsyncClient, db_session: AsyncSession, signed_in, monkeypatch
):
    """The whole point of the channel being best effort, proved on a real approval decision.

    The relay refuses every attempt and the push service raises something nobody anticipated. The
    decision still stands, the task is still decided, and the in-app notification - the record -
    still exists.
    """
    submitter, purchase_headers = await purchase_user(signed_in)
    _, approver_headers = await approver_user(signed_in)
    await set_channel(db_session, submitter, "email")
    await subscribe(db_session, submitter.id, PUSH_ENDPOINT)
    await db_session.commit()

    submitter_id = submitter.id
    record_backoff(monkeypatch)
    install_relay(monkeypatch, FakeRelay(fail_times=99))
    install_push(monkeypatch)

    def _explode(subscription_info: dict, payload: str) -> None:
        raise RuntimeError("The push library did something entirely unexpected.")

    monkeypatch.setattr(push_service, "_send_webpush", _explode)

    transaction = await seeded_transaction(db_session)
    submitted = await client.post(
        f"{TRANSACTIONS}/{transaction.id}/submit", headers=purchase_headers, json={}
    )
    assert submitted.status_code == 200, submitted.text
    task = await db_session.scalar(
        select(ApprovalTask).where(ApprovalTask.transaction_id == transaction.id)
    )
    assert task is not None
    task_id = task.id

    decided = await client.post(
        f"{APPROVALS}/{task_id}/decide",
        headers=approver_headers,
        json={"decision": ApprovalDecision.APPROVED.value},
    )
    assert decided.status_code == 200, decided.text

    db_session.expire_all()
    stored = await db_session.get(ApprovalTask, task_id)
    assert stored is not None
    assert stored.decision == ApprovalDecision.APPROVED.value
    decisions = [
        row
        for row in await rows_for(db_session, submitter_id)
        if row.notification_type == "approval.decided"
    ]
    assert len(decisions) == 1
    assert decisions[0].email_sent_at is None
    assert decisions[0].push_sent_at is None


# --- rendering -------------------------------------------------------------------------------------


def test_every_notification_type_renders_a_named_template_with_both_parts(monkeypatch):
    monkeypatch.setattr(settings, "APP_BASE_URL", "https://command-centre.agfze.test")
    for notification_type in email_service.TEMPLATE_BY_TYPE:
        rendered = email_service.render_email(
            notification_type,
            recipient_name="Marco Bellini",
            message="Something happened that needs you.",
            link="/exceptions/1",
        )
        assert rendered.subject
        assert "AGFZE" in rendered.html and "AGFZE" in rendered.text
        # The palette the platform has used since Step 1, in both the header and the button.
        assert "#182338" in rendered.html and "#A75D35" in rendered.html
        assert "https://command-centre.agfze.test/exceptions/1" in rendered.html
        assert "https://command-centre.agfze.test/exceptions/1" in rendered.text
        assert "Something happened that needs you." in rendered.text


def test_an_ai_related_notification_carries_the_platform_disclaimer_verbatim(monkeypatch):
    monkeypatch.setattr(settings, "APP_BASE_URL", "https://command-centre.agfze.test")
    rendered = email_service.render_email(
        "approval.requested",
        recipient_name="Rania Haddad",
        message="A decision.",
        link="/approvals/1",
    )
    assert email_service.AI_DISCLAIMER_TEXT in rendered.text
    assert "AI-extracted information may contain errors" in rendered.html


def test_a_multipart_message_carries_a_real_plaintext_part(monkeypatch):
    monkeypatch.setattr(settings, "SMTP_FROM_ADDRESS", "command-centre@agfze.test")
    rendered = email_service.render_email(
        "report.ready", recipient_name="Sofia", message="A report.", link="/reports/1"
    )
    message = email_service.build_message("sofia@agfze.test", rendered)
    assert message.is_multipart()
    types = {part.get_content_type() for part in message.walk()}
    assert "text/plain" in types and "text/html" in types


def test_a_link_that_is_not_a_relative_path_never_leaves_the_platform(monkeypatch):
    monkeypatch.setattr(settings, "APP_BASE_URL", "https://command-centre.agfze.test")
    for link in ("https://evil.test/steal", "//evil.test/steal", "javascript:alert(1)", None):
        assert email_service.absolute_url(link).startswith("https://command-centre.agfze.test/")
        assert "evil.test" not in email_service.absolute_url(link)


def test_a_push_payload_carries_a_summary_and_a_path_and_nothing_else():
    payload = json.loads(
        push_service.build_payload(
            "approval.requested", "I2626-B1 is awaiting a decision.", "https://app.test/approvals/1"
        )
    )
    assert set(payload) == {"title", "body", "url", "icon", "badge", "type"}
    assert payload["icon"].startswith("/icons/")


# --- the real signing path, without a request leaving the machine ---------------------------------


async def test_a_real_delivery_is_vapid_signed_and_the_payload_is_encrypted(monkeypatch):
    """The one test that runs pywebpush for real, over a fake HTTP session.

    Everything else in this file replaces `_send_webpush`, which is right for asserting on the
    platform's own behaviour but proves nothing about the key format. This one generates a pair
    exactly as `make vapid-keys` does, signs a genuine delivery with it, and asserts on what would
    have gone over the wire: a VAPID Authorization header, and a body that is not the payload in
    the clear. A push travels through a third-party service, and this is what makes it opaque
    to it.
    """
    from scripts.generate_vapid_keys import generate

    public, private = generate()
    monkeypatch.setattr(settings, "VAPID_PUBLIC_KEY", public)
    monkeypatch.setattr(settings, "VAPID_PRIVATE_KEY", private)
    monkeypatch.setattr(settings, "VAPID_SUBJECT", "mailto:ops@agfze.test")

    captured: dict = {}

    class FakeResponse:
        status_code = 201
        text = ""
        headers: ClassVar[dict] = {}

    class FakeSession:
        def post(self, endpoint, **kwargs):
            captured["endpoint"] = endpoint
            captured.update(kwargs)
            return FakeResponse()

    push_service.set_requests_session(FakeSession())
    try:
        push_service._send_webpush(
            {
                "endpoint": "https://fcm.googleapis.com/fcm/send/abc",
                # A real, valid P-256 point and auth secret, so the encryption runs for real.
                "keys": {
                    "p256dh": (
                        "BEl62iUYgUivxIkv69yViEuiBIa-Ib9-SkvMeAtA3LFgDzkrxZJjSgSnfckjBJuBkr3q"
                        "BUYIHBQFLXYp5Nksh8U"
                    ),
                    "auth": "8eDyX_uCN0XRhSbY5hs7Hg",
                },
            },
            '{"title":"Decision waiting on you","body":"I2626-B1 is awaiting a decision."}',
        )
    finally:
        push_service.set_requests_session(None)

    headers = captured["headers"]
    assert headers["Authorization"].startswith("vapid ")
    assert headers["Content-Encoding"] == "aes128gcm"
    assert headers["TTL"] == str(settings.PUSH_TTL_SECONDS)
    body = captured["data"]
    assert isinstance(body, bytes)
    # Encrypted end to end: the push service that relays this cannot read the sentence in it.
    assert b"awaiting a decision" not in body


# --- the endpoints, self-only ----------------------------------------------------------------------


async def test_the_public_key_is_served_and_the_private_one_is_not(
    client: AsyncClient, signed_in, monkeypatch
):
    _, headers = await purchase_user(signed_in)
    monkeypatch.setattr(settings, "VAPID_PUBLIC_KEY", "the-public-half")
    monkeypatch.setattr(settings, "VAPID_PRIVATE_KEY", "the-private-half-nobody-sees")

    response = await client.get(f"{NOTIFICATIONS}/vapid-public-key", headers=headers)
    assert response.status_code == 200, response.text
    body = response.text
    assert response.json()["data"] == {"public_key": "the-public-half", "configured": True}
    assert "the-private-half-nobody-sees" not in body


async def test_an_unconfigured_deployment_says_so_rather_than_serving_an_empty_key(
    client: AsyncClient, signed_in, monkeypatch
):
    _, headers = await purchase_user(signed_in)
    monkeypatch.setattr(settings, "VAPID_PUBLIC_KEY", "")
    monkeypatch.setattr(settings, "VAPID_PRIVATE_KEY", "")

    response = await client.get(f"{NOTIFICATIONS}/vapid-public-key", headers=headers)
    assert response.json()["data"]["configured"] is False


async def test_resubscribing_the_same_browser_updates_rather_than_duplicates(
    client: AsyncClient, db_session: AsyncSession, signed_in
):
    user, headers = await purchase_user(signed_in)
    body = {"endpoint": PUSH_ENDPOINT, "keys": {"p256dh": P256DH, "auth": AUTH_SECRET}}

    first = await client.post(f"{NOTIFICATIONS}/push-subscribe", headers=headers, json=body)
    assert first.status_code == 200, first.text

    rotated = {
        "endpoint": PUSH_ENDPOINT,
        "keys": {"p256dh": P256DH_ROTATED, "auth": AUTH_SECRET_ROTATED},
    }
    second = await client.post(f"{NOTIFICATIONS}/push-subscribe", headers=headers, json=rotated)
    assert second.status_code == 200, second.text
    assert second.json()["data"]["id"] == first.json()["data"]["id"]

    rows = list(
        (
            await db_session.scalars(
                select(PushSubscription).where(PushSubscription.user_id == user.id)
            )
        ).all()
    )
    assert len(rows) == 1
    assert rows[0].p256dh == P256DH_ROTATED


async def test_a_subscription_endpoint_must_be_https(client: AsyncClient, signed_in):
    _, headers = await purchase_user(signed_in)
    response = await client.post(
        f"{NOTIFICATIONS}/push-subscribe",
        headers=headers,
        json={
            "endpoint": "http://push.test/x",
            "keys": {"p256dh": P256DH, "auth": AUTH_SECRET},
        },
    )
    assert response.status_code == 422


async def test_a_subscription_key_that_is_not_really_a_key_is_refused(
    client: AsyncClient, signed_in, db_session: AsyncSession
):
    """The regression: 65 bytes with the right prefix, and not a point on the curve.

    Stored, it would have failed inside the encryption on every delivery for ever - before any
    push service was contacted, so nothing would ever have returned the 410 that prunes it.
    """
    forged = "BLc4xRzKlKORKWlbdgFaBrrPK3ydWAHo4M0gs0i1oek330lRWNfrEG1jSxKGiSJfxLcuAqjPQMUS-QwGLbmtRXY"
    _, headers = await purchase_user(signed_in)

    response = await client.post(
        f"{NOTIFICATIONS}/push-subscribe",
        json={"endpoint": PUSH_ENDPOINT, "keys": {"p256dh": forged, "auth": AUTH_SECRET}},
        headers=headers,
    )

    assert response.status_code == 422
    rows = (await db_session.execute(select(PushSubscription))).scalars().all()
    assert rows == []


async def test_an_auth_secret_of_the_wrong_length_is_refused(client: AsyncClient, signed_in):
    _, headers = await purchase_user(signed_in)

    response = await client.post(
        f"{NOTIFICATIONS}/push-subscribe",
        json={"endpoint": PUSH_ENDPOINT, "keys": {"p256dh": P256DH, "auth": "dG9vLXNob3J0"}},
        headers=headers,
    )

    assert response.status_code == 422


async def test_a_browsers_unpadded_base64_is_accepted_as_sent(
    client: AsyncClient, signed_in, db_session: AsyncSession
):
    """JavaScript strips the padding. Demanding it back would reject every real browser."""
    assert not P256DH.endswith("=") and not AUTH_SECRET.endswith("=")
    _, headers = await purchase_user(signed_in)

    response = await client.post(
        f"{NOTIFICATIONS}/push-subscribe",
        json={"endpoint": PUSH_ENDPOINT, "keys": {"p256dh": P256DH, "auth": AUTH_SECRET}},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    rows = (await db_session.execute(select(PushSubscription))).scalars().all()
    assert [row.p256dh for row in rows] == [P256DH]


async def test_unsubscribing_touches_nobody_elses_browser(
    client: AsyncClient, db_session: AsyncSession, signed_in
):
    first, first_headers = await purchase_user(signed_in)
    second, _ = await approver_user(signed_in)
    await subscribe(db_session, first.id, PUSH_ENDPOINT)
    # The other account's browser, quoted verbatim in the request below.
    await subscribe(db_session, second.id, SECOND_ENDPOINT)
    await db_session.commit()

    response = await client.request(
        "DELETE",
        f"{NOTIFICATIONS}/push-subscribe",
        headers=first_headers,
        json={"endpoint": SECOND_ENDPOINT},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["removed"] == 0

    remaining = list((await db_session.scalars(select(PushSubscription))).all())
    assert {row.endpoint for row in remaining} == {PUSH_ENDPOINT, SECOND_ENDPOINT}


async def test_unsubscribing_without_an_endpoint_forgets_every_browser_on_the_account(
    client: AsyncClient, db_session: AsyncSession, signed_in
):
    user, headers = await purchase_user(signed_in)
    await subscribe(db_session, user.id, PUSH_ENDPOINT)
    await subscribe(db_session, user.id, SECOND_ENDPOINT)
    await db_session.commit()

    response = await client.request("DELETE", f"{NOTIFICATIONS}/push-subscribe", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["removed"] == 2

    assert (
        await db_session.scalar(select(PushSubscription).where(PushSubscription.user_id == user.id))
    ) is None


async def test_a_sign_out_with_nothing_to_remove_still_succeeds(client: AsyncClient, signed_in):
    _, headers = await purchase_user(signed_in)
    response = await client.request("DELETE", f"{NOTIFICATIONS}/push-subscribe", headers=headers)
    assert response.status_code == 200
    assert response.json()["data"]["removed"] == 0


async def test_the_push_endpoints_need_a_token(client: AsyncClient):
    assert (await client.get(f"{NOTIFICATIONS}/vapid-public-key")).status_code == 401
    assert (
        await client.post(
            f"{NOTIFICATIONS}/push-subscribe",
            json={"endpoint": PUSH_ENDPOINT, "keys": {"p256dh": P256DH, "auth": AUTH_SECRET}},
        )
    ).status_code == 401
    assert (await client.request("DELETE", f"{NOTIFICATIONS}/push-subscribe")).status_code == 401

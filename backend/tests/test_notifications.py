"""Every notification trigger point, its recipients, and the self-only reads.

The trigger points are exercised through the real services and the real endpoints that produce
them - the rule engine opens the exception, the submit endpoint raises the approval task, the
decision endpoint records the decision - so what is proved is the wiring as it actually runs,
not a hand-built call to the notification service.

Two of these tests matter more than the rest:

* the exception broadcast, because `ExceptionCase` records an owner *role* and no assignee, so
  the notification has to reach every active holder of that role rather than one arbitrary person;
* the bulk decision, because a batch approval is N decisions that happened to be asked for
  together, and each of them is somebody's own submission coming back to them.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.roles import PlatformRole
from app.models.configuration import RuleConfiguration
from app.models.enums import (
    ApprovalDecision,
    ExceptionCategory,
    ExceptionPriority,
    IntegrationJobStatus,
    IntegrationTargetSystem,
    TransactionStatus,
)
from app.models.governance import ApprovalTask, ExceptionCase
from app.models.identity import User
from app.models.integration import IntegrationJob
from app.models.notifications import Notification
from app.services import notification_service
from app.services.governance import approval_service, hooks, thresholds
from app.services.integration import integration_service
from app.services.integration.adapters import IntegrationOutcome
from tests.utils.admin import admin_user, approver_user, purchase_user
from tests.utils.governance import seeded_transaction

pytestmark = pytest.mark.usefixtures("patched_jwks")

NOTIFICATIONS = "/api/v1/notifications"
TRANSACTIONS = "/api/v1/transactions"
APPROVALS = "/api/v1/approvals"


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


async def second_purchase_user(signed_in):
    return await signed_in(
        "0a1b2c3d-0000-4000-8000-0000000009b1",
        "second.purchase@agfze.ae",
        "Yousef Karim",
        ["purchase_user"],
    )


# --- the service itself ---------------------------------------------------------------------------


async def test_a_role_broadcast_reaches_every_active_holder_and_no_disabled_one(
    db_session: AsyncSession, signed_in
):
    first, _ = await purchase_user(signed_in)
    second, _ = await second_purchase_user(signed_in)
    approver, _ = await approver_user(signed_in)

    disabled = await db_session.get(User, second.id)
    assert disabled is not None
    disabled.is_active = False
    await db_session.commit()

    created = await notification_service.notify(
        db_session,
        notification_type=notification_service.NotificationType.EXCEPTION_OPENED,
        message="A broadcast to the purchase desk.",
        roles=[PlatformRole.PURCHASE_USER.value],
    )
    await db_session.commit()

    recipients = {row.user_id for row in created}
    assert first.id in recipients
    # Disabled accounts are not told about work they cannot pick up.
    assert second.id not in recipients
    # And a role broadcast reaches that role only.
    assert approver.id not in recipients


async def test_the_service_deduplicates_a_person_who_is_named_and_in_the_role(
    db_session: AsyncSession, signed_in
):
    user, _ = await purchase_user(signed_in)

    created = await notification_service.notify(
        db_session,
        notification_type=notification_service.NotificationType.APPROVAL_REQUESTED,
        message="Named and in the role.",
        user_ids=[user.id],
        roles=[PlatformRole.PURCHASE_USER.value],
    )
    await db_session.commit()

    assert len(created) == 1


async def test_a_role_with_no_active_holder_notifies_nobody_rather_than_failing(
    db_session: AsyncSession,
):
    created = await notification_service.notify(
        db_session,
        notification_type=notification_service.NotificationType.REPORT_READY,
        message="Nobody holds this role on this deployment.",
        roles=[PlatformRole.AUDITOR.value],
    )
    assert created == []


# --- trigger: a new exception case -------------------------------------------------------------


async def test_opening_an_exception_broadcasts_to_the_owning_desk(
    db_session: AsyncSession, signed_in
):
    first, _ = await purchase_user(signed_in)
    second, _ = await second_purchase_user(signed_in)
    approver, _ = await approver_user(signed_in)
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

    for user in (first, second):
        rows = await rows_for(db_session, user.id)
        assert len(rows) == 1
        assert rows[0].notification_type == "exception.opened"
        assert rows[0].link == f"/exceptions/{case.id}"
        assert transaction.batch_number in rows[0].message
        assert rows[0].is_read is False

    # The approver's desk does not own this category, so nothing reaches them.
    assert await rows_for(db_session, approver.id) == []


async def test_a_duplicate_exception_notifies_nobody_a_second_time(
    db_session: AsyncSession, signed_in
):
    """`open_case` is idempotent on an unresolved case, and the notification rides that."""
    user, _ = await purchase_user(signed_in)
    transaction = await seeded_transaction(db_session, validate=False)

    for _ in range(3):
        await hooks.open_case(
            db_session,
            category=ExceptionCategory.UNMATCHED_REFERENCE.value,
            owner_role=PlatformRole.PURCHASE_USER.value,
            summary="The same problem, re-evaluated.",
            transaction_id=transaction.id,
        )
    await db_session.commit()

    assert len(await rows_for(db_session, user.id)) == 1


# --- trigger: a new approval task ----------------------------------------------------------------


async def test_a_task_with_no_assignee_broadcasts_to_the_approving_desk(
    db_session: AsyncSession, signed_in
):
    submitter, _ = await purchase_user(signed_in)
    approver, _ = await approver_user(signed_in)
    transaction = await seeded_transaction(db_session, validate=False)

    await approval_service.create_task(db_session, transaction, requested_by_id=submitter.id)
    await db_session.commit()

    rows = await rows_for(db_session, approver.id)
    assert len(rows) == 1
    assert rows[0].notification_type == "approval.requested"
    assert transaction.batch_number in rows[0].message
    # The person who asked for the decision is not told that they asked for it.
    assert await rows_for(db_session, submitter.id) == []


async def test_a_task_with_a_named_assignee_reaches_only_that_person(
    db_session: AsyncSession, signed_in
):
    submitter, _ = await purchase_user(signed_in)
    approver, _ = await approver_user(signed_in)
    named, _ = await admin_user(signed_in)
    transaction = await seeded_transaction(db_session, validate=False)

    task = await approval_service.create_task(
        db_session, transaction, requested_by_id=submitter.id, assignee_id=named.id
    )
    await db_session.commit()

    rows = await rows_for(db_session, named.id)
    assert len(rows) == 1
    assert rows[0].link == f"/approvals/{task.id}"
    # A named assignee means the desk-wide broadcast is not sent.
    assert await rows_for(db_session, approver.id) == []


# --- trigger: an approval decision ---------------------------------------------------------------


async def submit_for_approval(client: AsyncClient, db_session: AsyncSession, headers) -> UUID:
    transaction = await seeded_transaction(db_session)
    response = await client.post(
        f"{TRANSACTIONS}/{transaction.id}/submit", headers=headers, json={}
    )
    assert response.status_code == 200, response.text
    # The identifier itself, not a rendering of it: it is compared against a UUID column, and the
    # SQLite fallback binds a string against one as a string rather than coercing it.
    return transaction.id


async def test_a_decision_reaches_the_submitter_resolved_from_the_audit_trail(
    client: AsyncClient, db_session: AsyncSession, signed_in
):
    """There is no column recording who submitted, so the trail is what answers."""
    submitter, purchase_headers = await purchase_user(signed_in)
    _, approver_headers = await approver_user(signed_in)

    transaction_id = await submit_for_approval(client, db_session, purchase_headers)
    task = await db_session.scalar(
        select(ApprovalTask).where(ApprovalTask.transaction_id == transaction_id)
    )
    assert task is not None

    response = await client.post(
        f"{APPROVALS}/{task.id}/decide",
        headers=approver_headers,
        json={
            "decision": ApprovalDecision.CHANGES_REQUESTED.value,
            "reason": "The contract reference on the invoice does not match the pack.",
        },
    )
    assert response.status_code == 200, response.text

    rows = [
        row
        for row in await rows_for(db_session, submitter.id)
        if row.notification_type == "approval.decided"
    ]
    assert len(rows) == 1
    assert "sent back for changes" in rows[0].message
    assert rows[0].link == f"/approvals/{task.id}"


async def test_a_bulk_decision_creates_one_notification_per_transaction(
    client: AsyncClient, db_session: AsyncSession, signed_in
):
    """Never one notification standing in for several.

    A batch approval is N approvals that happened to be requested together, and each of them is
    an individual submitter's own transaction coming back to them.
    """
    submitter, purchase_headers = await purchase_user(signed_in)
    _, approver_headers = await approver_user(signed_in)

    # A ceiling high enough that these transactions are genuinely bulk-eligible. Raised through
    # the configured row, which is where the ceiling has always lived.
    ceiling = await db_session.scalar(
        select(RuleConfiguration).where(
            RuleConfiguration.check_key == thresholds.GovernanceKey.BULK_APPROVAL_VALUE_CEILING
        )
    )
    assert ceiling is not None
    ceiling.threshold_value = Decimal("1000000")
    await db_session.commit()

    approval_ids: list[str] = []
    for index in range(3):
        transaction = await seeded_transaction(db_session, batch_number=f"I2626-B{index}")
        submitted = await client.post(
            f"{TRANSACTIONS}/{transaction.id}/submit", headers=purchase_headers, json={}
        )
        assert submitted.status_code == 200, submitted.text
        task = await db_session.scalar(
            select(ApprovalTask).where(ApprovalTask.transaction_id == transaction.id)
        )
        assert task is not None
        approval_ids.append(str(task.id))

    response = await client.post(
        f"{APPROVALS}/bulk-decide",
        headers=approver_headers,
        json={"approval_ids": approval_ids},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["approved_count"] == 3

    decided = [
        row
        for row in await rows_for(db_session, submitter.id)
        if row.notification_type == "approval.decided"
    ]
    # Three transactions, three notifications - not one for the batch.
    assert len(decided) == 3
    assert len({row.link for row in decided}) == 3
    for row in decided:
        assert "approved" in row.message


# --- trigger: an integration job that needs a person ---------------------------------------------


async def test_a_failed_integration_job_notifies_admin(db_session: AsyncSession, signed_in):
    admin, _ = await admin_user(signed_in)
    purchase, _ = await purchase_user(signed_in)
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
    assert "every automatic attempt has been used up" in rows[0].message.lower()
    assert rows[0].link == f"/admin/integrations?transaction_id={transaction.id}"

    # The buying desk is not told about a posting they cannot fix.
    assert [
        row
        for row in await rows_for(db_session, purchase.id)
        if row.notification_type == "integration.attention"
    ] == []


async def test_a_job_awaiting_a_person_notifies_admin_without_calling_it_a_failure(
    db_session: AsyncSession, signed_in
):
    admin, _ = await admin_user(signed_in)
    transaction = await seeded_transaction(db_session, validate=False)

    job = IntegrationJob(
        transaction_id=transaction.id,
        target_system=IntegrationTargetSystem.DMS.value,
        status=IntegrationJobStatus.QUEUED.value,
    )
    db_session.add(job)
    await db_session.flush()

    await integration_service._apply_awaiting_manual(
        db_session,
        job,
        transaction,
        IntegrationOutcome.awaiting_manual_action(
            "File the compiled pack in the document store.",
            payload={"pack": "sales_bank_docs"},
            reason="not_configured",
        ),
    )
    await db_session.commit()

    rows = [
        row
        for row in await rows_for(db_session, admin.id)
        if row.notification_type == "integration.attention"
    ]
    assert len(rows) == 1
    message = rows[0].message.lower()
    assert "completed by a person" in message
    # A posting waiting on somebody is not a failure and must never read as one.
    assert "failed" not in message


# --- trigger: a scheduled report ------------------------------------------------------------------


async def test_a_scheduled_report_notifies_admin_and_the_approving_desk(
    db_session: AsyncSession, signed_in, storage_root
):
    from app.services.analytics import schedule

    admin, _ = await admin_user(signed_in)
    approver, _ = await approver_user(signed_in)
    purchase, _ = await purchase_user(signed_in)

    result = await schedule.run_due(db_session)
    assert len(result.generated) == 2

    for user in (admin, approver):
        rows = [
            row
            for row in await rows_for(db_session, user.id)
            if row.notification_type == "report.ready"
        ]
        # One daily and one monthly.
        assert len(rows) == 2
        assert all(row.link.startswith("/reports/") for row in rows)

    # An ad-hoc report's requester is already watching a progress indicator; nobody else asked.
    assert [
        row
        for row in await rows_for(db_session, purchase.id)
        if row.notification_type == "report.ready"
    ] == []


# --- the endpoints, and their self-only scope ------------------------------------------------------


async def test_a_user_sees_only_their_own_notifications(
    client: AsyncClient, db_session: AsyncSession, signed_in
):
    first, first_headers = await purchase_user(signed_in)
    second, second_headers = await second_purchase_user(signed_in)

    await notification_service.notify(
        db_session,
        notification_type=notification_service.NotificationType.EXCEPTION_OPENED,
        message="For the first user only.",
        user_ids=[first.id],
    )
    await notification_service.notify(
        db_session,
        notification_type=notification_service.NotificationType.EXCEPTION_OPENED,
        message="For the second user only.",
        user_ids=[second.id],
    )
    await db_session.commit()

    mine = await client.get(NOTIFICATIONS, headers=first_headers)
    assert mine.status_code == 200
    messages = [row["message"] for row in mine.json()["data"]["items"]]
    assert messages == ["For the first user only."]
    assert mine.json()["data"]["unread_count"] == 1

    theirs = await client.get(NOTIFICATIONS, headers=second_headers)
    assert [row["message"] for row in theirs.json()["data"]["items"]] == [
        "For the second user only."
    ]


async def test_marking_all_read_touches_nobody_elses_rows(
    client: AsyncClient, db_session: AsyncSession, signed_in
):
    first, first_headers = await purchase_user(signed_in)
    second, _ = await second_purchase_user(signed_in)
    first_id, second_id = first.id, second.id

    for user in (first, second):
        await notification_service.notify(
            db_session,
            notification_type=notification_service.NotificationType.EXCEPTION_OPENED,
            message="Unread to begin with.",
            user_ids=[user.id],
        )
    await db_session.commit()

    response = await client.post(f"{NOTIFICATIONS}/mark-all-read", headers=first_headers)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["marked"] == 1
    assert response.json()["data"]["unread_count"] == 0

    db_session.expire_all()
    assert all(row.is_read for row in await rows_for(db_session, first_id))
    # The other account's row is untouched.
    assert all(not row.is_read for row in await rows_for(db_session, second_id))


async def test_the_notification_endpoints_need_a_token(client: AsyncClient):
    assert (await client.get(NOTIFICATIONS)).status_code == 401
    assert (await client.post(f"{NOTIFICATIONS}/mark-all-read")).status_code == 401


async def test_the_unread_filter_narrows_to_unread(
    client: AsyncClient, db_session: AsyncSession, signed_in
):
    user, headers = await purchase_user(signed_in)
    rows = await notification_service.notify(
        db_session,
        notification_type=notification_service.NotificationType.EXCEPTION_OPENED,
        message="Two of these.",
        user_ids=[user.id],
    )
    more = await notification_service.notify(
        db_session,
        notification_type=notification_service.NotificationType.APPROVAL_REQUESTED,
        message="And one more.",
        user_ids=[user.id],
    )
    rows[0].is_read = True
    await db_session.commit()
    assert len(more) == 1

    response = await client.get(NOTIFICATIONS, headers=headers, params={"unread_only": True})
    assert response.json()["data"]["page"]["total"] == 1
    assert response.json()["data"]["unread_count"] == 1


def test_the_notification_table_records_delivery_per_channel():
    """The two columns Step 9 withheld, arriving in Step 10 with the code that writes them.

    They are recorded per channel and never inferred from one another, because the channels are
    genuinely independent: email follows a preference, push follows a browser subscription, and a
    person can be on either, both or neither while in-app happens for everybody regardless.
    """
    columns = set(Notification.__table__.columns.keys())
    assert "email_sent_at" in columns
    assert "push_sent_at" in columns
    assert Notification.__table__.c.email_sent_at.nullable
    assert Notification.__table__.c.push_sent_at.nullable


def test_nothing_outside_the_service_writes_a_notification_row():
    """One writer, checked by reading the source of every module that could have a second.

    Word-bounded, so Graph's own `GraphNotification` - a different thing entirely, and not a row
    in this table - is not mistaken for a second writer.
    """
    import pathlib
    import re

    constructor = re.compile(r"(?<![A-Za-z0-9_])Notification\(")
    root = pathlib.Path(__file__).resolve().parents[1] / "app"
    offenders = [
        str(path.relative_to(root))
        for path in root.rglob("*.py")
        if path.name not in {"notification_service.py", "notifications.py"}
        and constructor.search(path.read_text())
    ]
    assert offenders == []


async def test_open_exception_cases_still_carry_their_owning_role(
    db_session: AsyncSession, signed_in
):
    """A guard on the assumption the broadcast rests on.

    The exception notification is a role broadcast precisely because `ExceptionCase` records an
    owner role and no assignee is guaranteed. If that ever stopped being true, this fails first.
    """
    await purchase_user(signed_in)
    transaction = await seeded_transaction(db_session, validate=False)
    case = await hooks.open_case(
        db_session,
        category=ExceptionCategory.LOW_CONFIDENCE.value,
        owner_role=PlatformRole.PURCHASE_USER.value,
        summary="Read at 61%.",
        transaction_id=transaction.id,
    )
    await db_session.commit()

    assert case is not None
    stored = await db_session.get(ExceptionCase, case.id)
    assert stored is not None
    assert stored.owner_role == PlatformRole.PURCHASE_USER.value

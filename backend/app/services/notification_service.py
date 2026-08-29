"""The one function that creates a notification, and the only one that may.

Analogous in spirit to `record_audit_event`: every trigger point in the platform calls
:func:`notify` and nothing anywhere constructs a `Notification` directly. That is what keeps one
answer to "who gets told about this" rather than one per calling module.

Recipients are specified two ways, because the platform genuinely has two shapes of ownership:

* by **user**, for work that has a named person on it - an approval put to a specific approver,
  or the reply to whoever submitted a transaction;
* by **role**, for work that belongs to a desk rather than a person. An `ExceptionCase` records
  an owner *role* and no assignee, so an exception notification is a broadcast to every currently
  active holder of that role, which is exactly who could pick it up.

Step 10 gave `notify` two more delivery channels, and gave them to it *inside its own body*. Not
one of the five trigger points below - nor any of their callers - changed by a line, which is the
whole reason this function was built as the single seam in the first place: attaching a channel is
an edit here, not an edit in five places that then have to be kept in agreement for ever.

The three channels are independent and a person can be on all of them at once:

* **in-app**, always, for everybody, regardless of any preference. It is the platform's durable
  record of having told somebody something, not an option;
* **email**, additionally, for a recipient whose `notification_channel` is `email`;
* **push**, additionally, for a recipient who currently has an active `PushSubscription` - a
  browser permission, never a settings-page flag, and never gated on `notification_channel`.

Delivery is best effort and is structurally incapable of harming the event it describes. Every
dispatch path is wrapped, every failure is logged and audited, and no exception raised by a relay
or a push service can reach the transaction that created the notification.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.roles import PlatformRole
from app.db.base import utcnow
from app.models.audit import AuditEvent
from app.models.identity import User
from app.models.notifications import Notification
from app.services.audit_service import ActorType, record_audit_event
from app.services.delivery import email_service, push_service

logger = get_logger(__name__)

# The one value of `users.notification_channel` that means "email me as well". Every other value,
# including the `in_app` default, means in-app only - which every user gets regardless.
EMAIL_CHANNEL = "email"

# Written to the audit trail when a delivery this platform attempted did not land, so a failure
# is visible on /admin/audit rather than only in a log stream.
EMAIL_FAILED_EVENT = "notification.email_failed"


class NotificationType:
    """What a notification is about. Kept parallel to the audit event vocabulary on purpose."""

    EXCEPTION_OPENED = "exception.opened"
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_DECIDED = "approval.decided"
    INTEGRATION_ATTENTION = "integration.attention"
    REPORT_READY = "report.ready"


# The audit events that mean "this person put this transaction up for a decision", newest first.
# There is no column recording the original submitter of a request for approval, so the trail is
# the record - and it is the right record: it is written at the moment of the act, by the acting
# user, and is already indexed by entity.
SUBMISSION_EVENT_TYPES: tuple[str, ...] = (
    "transaction.submitted",
    "approval.requested",
)


async def active_users_with_role(session: AsyncSession, role: str) -> list[User]:
    """Every enabled account currently holding one platform role.

    Filtered in Python rather than in SQL, deliberately. `users.roles` is a PostgreSQL array with
    a plain-JSON variant for the container-less test database, and there is no membership
    predicate that behaves identically on both. The set being scanned is this company's staff
    list - bounded, small, and read on a write path that runs once per exception - so a portable
    scan is worth more here than a dialect-specific query.
    """
    rows = (await session.scalars(select(User).where(User.is_active.is_(True)))).all()
    return [user for user in rows if role in (user.roles or ())]


async def notify(
    session: AsyncSession,
    *,
    notification_type: str,
    message: str,
    link: str | None = None,
    user_ids: Iterable[UUID] | None = None,
    roles: Iterable[str] | None = None,
    exclude_user_id: UUID | None = None,
    allow_email: bool = True,
) -> list[Notification]:
    """Create one notification per resolved recipient, and flush them.

    The caller owns the commit, exactly as `record_audit_event` does, so a notification lands in
    the same database transaction as the thing it is telling somebody about. A trigger that rolls
    back tells nobody anything, which is correct: the event it described did not happen.

    `exclude_user_id` drops one person from the resolved set, however they got into it. It is what
    keeps somebody from being notified about their own action - the approver who just decided
    something, or a requester who happens to hold the approving role themselves.

    Returns the rows created. An empty list is a normal outcome, not a failure: a role with no
    active holder has nobody to tell, and the audit trail already records what happened.

    `allow_email` is a ceiling on delivery and never a floor. The default leaves every existing
    caller exactly as it was - the recipient's own `notification_channel` decides whether an email
    is attempted. Passing False declines the attempt for this one trigger regardless of that
    preference, which is what a report distribution rule set to in-app-only needs. It cannot work
    the other way round: nothing here can email somebody who did not ask to be emailed.
    """
    recipients: dict[UUID, None] = {}
    for user_id in user_ids or ():
        if user_id is not None:
            recipients[user_id] = None
    for role in roles or ():
        for user in await active_users_with_role(session, role):
            recipients[user.id] = None
    if exclude_user_id is not None:
        recipients.pop(exclude_user_id, None)

    created: list[Notification] = []
    for user_id in recipients:
        row = Notification(
            user_id=user_id,
            notification_type=notification_type,
            message=message,
            link=link,
            is_read=False,
        )
        session.add(row)
        created.append(row)
    if created:
        await session.flush()
        # Everything above this line is Step 9, unchanged. Everything below it is Step 10, and it
        # is here rather than at any call site on purpose.
        await dispatch_deliveries(session, created, allow_email=allow_email)
    return created


# --- delivery, added in Step 10 inside this function rather than at any of its callers ----------


async def dispatch_deliveries(
    session: AsyncSession,
    notifications: Sequence[Notification],
    *,
    allow_email: bool = True,
) -> None:
    """Attempt email and push for rows that have already been created and flushed.

    Deliberately after the flush and deliberately in the same session: a delivery timestamp is a
    column on the notification, so it commits or rolls back with the notification and with the
    business event, and a rolled-back trigger leaves neither a row nor a claim that anything was
    sent.

    Nothing raised in here escapes. The outer guard is not belt-and-braces over the inner ones -
    it is the guarantee this step is built on, and the reason a mail relay refusing a connection
    cannot reverse an approval.
    """
    if not settings.NOTIFICATION_DELIVERY_ENABLED or not notifications:
        return
    try:
        user_ids = {row.user_id for row in notifications}
        users = {
            user.id: user
            for user in (await session.scalars(select(User).where(User.id.in_(user_ids)))).all()
        }
        for row in notifications:
            user = users.get(row.user_id)
            # A disabled account is told nothing off-platform. The in-app row already exists and
            # is the record; reaching somebody who can no longer sign in is not a courtesy.
            if user is None or not user.is_active:
                continue
            if allow_email:
                await _deliver_email(session, row, user)
            await _deliver_push(session, row, user)
    # A courtesy channel never takes the business event with it.
    except Exception:
        logger.exception("notification.dispatch_failed")


async def _deliver_email(session: AsyncSession, row: Notification, user: User) -> None:
    """Email, for a recipient who asked for it. In-app has already happened either way."""
    if (user.notification_channel or "").strip().lower() != EMAIL_CHANNEL:
        return
    try:
        sent = await email_service.send_notification_email(
            to_address=user.email,
            recipient_name=user.display_name,
            notification_type=row.notification_type,
            message=row.message,
            link=row.link,
        )
    except Exception:
        logger.exception(
            "notification.email_failed", extra={"notification_type": row.notification_type}
        )
        sent = False

    if sent:
        row.email_sent_at = utcnow()
        await session.flush()
        return
    if not settings.email_configured:
        # Nothing to report to an administrator: this deployment has no relay, which is a
        # configuration fact rather than a delivery that went wrong.
        return
    await record_audit_event(
        session,
        event_type=EMAIL_FAILED_EVENT,
        entity_type="notification",
        entity_id=row.id,
        actor_type=ActorType.SYSTEM,
        metadata={
            "notification_type": row.notification_type,
            "recipient_user_id": str(user.id),
            "attempts": settings.EMAIL_MAX_ATTEMPTS,
        },
    )


async def _deliver_push(session: AsyncSession, row: Notification, user: User) -> None:
    """Push, for a recipient whose browser is subscribed - and for no other reason.

    `notification_channel` is not consulted here and must not be. A user on the `in_app` default
    who has granted notification permission receives push; a user set to `email` who never
    granted it does not.
    """
    try:
        delivered = await push_service.push_to_user(
            session,
            user_id=user.id,
            notification_type=row.notification_type,
            message=row.message,
            url=email_service.absolute_url(row.link),
        )
    except Exception:
        logger.exception(
            "notification.push_failed", extra={"notification_type": row.notification_type}
        )
        return
    if delivered:
        row.push_sent_at = utcnow()
        await session.flush()


async def resolve_submitter_id(session: AsyncSession, transaction_id: UUID) -> UUID | None:
    """Who put this transaction up for a decision, read off the audit trail.

    The most recent submission-related entry for the entity wins, because a transaction that was
    sent back and re-submitted belongs to whoever re-submitted it, not to whoever raised it the
    first time. Returns None where the trail has no such entry - a transaction submitted by a
    background path, or one whose submitter's account has since been removed - and the caller
    simply notifies nobody rather than guessing at a recipient.
    """
    return await session.scalar(
        select(AuditEvent.actor_id)
        .where(
            AuditEvent.entity_type == "trade_transaction",
            AuditEvent.entity_id == str(transaction_id),
            AuditEvent.event_type.in_(SUBMISSION_EVENT_TYPES),
            AuditEvent.actor_id.is_not(None),
        )
        .order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc())
        .limit(1)
    )


# --- the trigger points, each one a thin call onto `notify` -------------------------------------


async def notify_exception_opened(
    session: AsyncSession,
    *,
    case_id: UUID,
    owner_role: str,
    summary: str,
    batch_number: str | None,
) -> list[Notification]:
    """Every active holder of the owning desk's role. The case names a role, not a person."""
    subject = f"batch {batch_number}" if batch_number else "an unmatched document"
    return await notify(
        session,
        notification_type=NotificationType.EXCEPTION_OPENED,
        message=f"A new exception needs attention on {subject}. {summary}",
        link=f"/exceptions/{case_id}",
        roles=[owner_role],
    )


async def notify_approval_requested(
    session: AsyncSession,
    *,
    task_id: UUID,
    approver_role: str,
    assignee_id: UUID | None,
    batch_number: str,
    requested_by_id: UUID | None,
) -> list[Notification]:
    """The named approver where the task has one, and the approving desk where it does not."""
    message = f"{batch_number} is awaiting a decision."
    if assignee_id is not None:
        return await notify(
            session,
            notification_type=NotificationType.APPROVAL_REQUESTED,
            message=message,
            link=f"/approvals/{task_id}",
            user_ids=[assignee_id],
        )
    return await notify(
        session,
        notification_type=NotificationType.APPROVAL_REQUESTED,
        message=message,
        link=f"/approvals/{task_id}",
        roles=[approver_role],
        # The person who asked for the decision is not told that they asked for it, even where
        # they happen to hold the approving role themselves.
        exclude_user_id=requested_by_id,
    )


DECISION_WORDING: dict[str, str] = {
    "approved": "approved",
    "rejected": "rejected",
    "changes_requested": "sent back for changes",
}


async def notify_approval_decided(
    session: AsyncSession,
    *,
    transaction_id: UUID,
    task_id: UUID,
    batch_number: str,
    decision: str,
    reason: str | None,
    decided_by_id: UUID | None,
) -> list[Notification]:
    """The transaction's original submitter, resolved from the audit trail.

    Called once per decided transaction, including each individual transaction inside a bulk
    decision. A batch of approvals is N decisions that were asked for together, and each of them
    is somebody's own submission coming back to them.
    """
    submitter_id = await resolve_submitter_id(session, transaction_id)
    if submitter_id is None:
        return []
    wording = DECISION_WORDING.get(decision, decision.replace("_", " "))
    message = f"Your submission {batch_number} was {wording}."
    if reason:
        message = f"{message} {reason}"
    return await notify(
        session,
        notification_type=NotificationType.APPROVAL_DECIDED,
        message=message,
        link=f"/approvals/{task_id}",
        user_ids=[submitter_id],
        exclude_user_id=decided_by_id,
    )


async def notify_integration_attention(
    session: AsyncSession,
    *,
    transaction_id: UUID,
    target_label: str,
    batch_number: str | None,
    state: str,
) -> list[Notification]:
    """Admin, because on this platform Admin is the integration-support function.

    Both states that need a person are reported and they are reported differently: a failure is a
    posting that was rejected, and `awaiting_manual_action` is a posting this deployment has no
    automated route for. Collapsing them into one sentence would tell an administrator to retry
    something that has nothing left to retry.
    """
    subject = f" for {batch_number}" if batch_number else ""
    detail = (
        f"{target_label} could not accept the posting{subject} and every automatic attempt has "
        "been used up."
        if state == "failed"
        else f"The {target_label} posting{subject} has to be completed by a person."
    )
    return await notify(
        session,
        notification_type=NotificationType.INTEGRATION_ATTENTION,
        message=f"An integration job needs attention. {detail}",
        link=f"/admin/integrations?transaction_id={transaction_id}",
        roles=[PlatformRole.ADMIN.value],
    )


async def notify_report_ready(
    session: AsyncSession,
    *,
    report_id: UUID,
    report_type: str,
    title: str,
) -> list[Notification]:
    """Admin and the approving desk, for a scheduled report only.

    An ad-hoc report is deliberately absent: its requester is already watching the job-progress
    indicator the report builder shows them, and a notification saying what the screen in front of
    them already says is noise.
    """
    return await notify(
        session,
        notification_type=NotificationType.REPORT_READY,
        message=f"The {report_type} report is ready: {title}.",
        link=f"/reports/{report_id}",
        roles=[PlatformRole.ADMIN.value, PlatformRole.APPROVER_HOD.value],
    )


# --- reads, all of them scoped to one account ---------------------------------------------------


async def list_for_user(
    session: AsyncSession,
    user_id: UUID,
    *,
    unread_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> Sequence[Notification]:
    """One user's own notifications. The `user_id` filter is in the query, always."""
    statement = select(Notification).where(Notification.user_id == user_id)
    if unread_only:
        statement = statement.where(Notification.is_read.is_(False))
    return (
        await session.scalars(
            statement.order_by(Notification.created_at.desc(), Notification.id.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()


async def unread_count(session: AsyncSession, user_id: UUID) -> int:
    from sqlalchemy import func

    return int(
        await session.scalar(
            select(func.count(Notification.id)).where(
                Notification.user_id == user_id, Notification.is_read.is_(False)
            )
        )
        or 0
    )


async def mark_all_read(session: AsyncSession, user_id: UUID) -> int:
    """Mark this account's unread notifications read, and nobody else's.

    The ownership predicate is part of the UPDATE rather than a check performed before it, so
    there is no window in which a mis-scoped call could touch another user's row.
    """
    rows = list(
        (
            await session.scalars(
                select(Notification).where(
                    Notification.user_id == user_id, Notification.is_read.is_(False)
                )
            )
        ).all()
    )
    for row in rows:
        row.is_read = True
    if rows:
        await session.flush()
    return len(rows)

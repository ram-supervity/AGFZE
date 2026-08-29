"""Who a generated scheduled report is told about, and on which channel.

Distribution on this platform is a notification pointing at a report, never a report. Nothing here
attaches a file to an email, embeds a figure in a message body, or sends anything to an address
that is not an active platform account - the link in every message resolves to the report's
authenticated detail page, and a recipient who cannot sign in sees nothing. That is the same rule
the rest of the platform already follows for documents, and this module is not the place it starts
being bent.

The resolution below is deliberately thin. It reads the active rules for a report type, expands
them to recipients, and hands the result to `notification_service.notify`, which is the one
function on this platform allowed to create a notification and the one place delivery happens. No
second delivery mechanism exists here, and none should: an email sent from this module would not
be recorded on the notification row, would not respect a recipient's own channel preference, and
would not be visible on the audit trail beside every other message the platform has sent.

A report type with no active rule distributes to nobody, and that is a correct, quiet outcome
rather than an error. The report still generated, is still stored, and is still readable by anyone
whose role lets them open it.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.notifications import Notification
from app.models.reporting import ReportDistributionRule
from app.services import notification_service
from app.services.notification_service import NotificationType

logger = get_logger(__name__)

# The channels on a rule that permit an email attempt. `in_app` is the third value and permits
# none - see `ReportDistributionRule.channel`, where the ceiling-not-floor reasoning lives.
EMAIL_CHANNELS = frozenset({"email", "both"})


@dataclass(frozen=True)
class DistributionOutcome:
    """What one report's distribution actually did, in terms a caller can log or assert on."""

    rules_applied: int
    notified_user_ids: frozenset[UUID]
    email_permitted: bool

    @property
    def distributed(self) -> bool:
        return bool(self.notified_user_ids)


async def active_rules(session: AsyncSession, report_type: str) -> list[ReportDistributionRule]:
    """Active rules for one report type, oldest first, so a log reads in the order they were set."""
    return list(
        (
            await session.scalars(
                select(ReportDistributionRule)
                .where(
                    ReportDistributionRule.report_type == report_type,
                    ReportDistributionRule.is_active.is_(True),
                )
                .order_by(ReportDistributionRule.created_at)
            )
        ).all()
    )


def _recipient_user_ids(rule: ReportDistributionRule) -> list[UUID]:
    """The rule's named individuals, skipping anything that is not a readable UUID.

    A malformed id is skipped rather than raised on. The column is JSON and a rule is edited by
    hand through an admin screen; one bad entry must not stop the other recipients on the same
    rule from being told, and the API layer validates on the way in so this is a backstop.
    """
    resolved: list[UUID] = []
    for raw in rule.recipient_user_ids or ():
        try:
            resolved.append(raw if isinstance(raw, UUID) else UUID(str(raw)))
        except (ValueError, AttributeError, TypeError):
            logger.warning(
                "report_distribution.unreadable_recipient",
                extra={"rule_id": str(rule.id), "report_type": rule.report_type},
            )
    return resolved


async def distribute(
    session: AsyncSession,
    *,
    report_id: UUID,
    report_type: str,
    title: str,
) -> DistributionOutcome:
    """Tell every configured recipient that this scheduled report exists.

    One `notify` call per rule rather than one for all of them, because the channel ceiling is a
    property of the rule: two rules on the same report type can legitimately name different desks
    on different channels, and collapsing them would have to pick one ceiling for both.

    `notify` de-duplicates within a call, and the returned set de-duplicates across calls, so a
    person named by a role on one rule and individually on another is told once and counted once.
    """
    rules = await active_rules(session, report_type)
    if not rules:
        # Not an error, and deliberately not a warning either. Distribution is opt-in
        # configuration, and a deployment that has not configured it is in its shipped state.
        logger.info(
            "report_distribution.no_active_rule",
            extra={"report_type": report_type, "report_id": str(report_id)},
        )
        return DistributionOutcome(
            rules_applied=0, notified_user_ids=frozenset(), email_permitted=False
        )

    notified: set[UUID] = set()
    email_permitted = False
    for rule in rules:
        allow_email = rule.channel in EMAIL_CHANNELS
        email_permitted = email_permitted or allow_email
        created: list[Notification] = await notification_service.notify(
            session,
            notification_type=NotificationType.REPORT_READY,
            message=f"The {report_type} report is ready: {title}.",
            link=f"/reports/{report_id}",
            user_ids=_recipient_user_ids(rule),
            roles=list(rule.recipient_roles or ()),
            allow_email=allow_email,
        )
        notified.update(row.user_id for row in created)

    logger.info(
        "report_distributed",
        extra={
            "report_type": report_type,
            "report_id": str(report_id),
            "rules_applied": len(rules),
            "recipient_count": len(notified),
            "email_permitted": email_permitted,
        },
    )
    return DistributionOutcome(
        rules_applied=len(rules),
        notified_user_ids=frozenset(notified),
        email_permitted=email_permitted,
    )

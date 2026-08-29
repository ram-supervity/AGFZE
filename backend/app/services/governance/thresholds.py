"""Governance thresholds, stored through the same mechanism the business rules use.

They live in `rule_configurations` beside the BR-01..BR-13 rows, because that table already is the
platform's configurable-value store and a second one would be a second place to look. They are
namespaced `GOV-` rather than `BR-` so nobody mistakes an approval-screen threshold for a business
rule: none of these is evaluated against a transaction, and none of them can fail.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.configuration import RuleConfiguration

SEED_CHANGE_REASON = "Platform default shipped with the exceptions and approvals module."


class GovernanceRule:
    """The `GOV-` namespace. Deliberately not part of the BR vocabulary."""

    APPROVALS = "GOV-01"
    EXCEPTIONS = "GOV-02"
    SHIPMENTS = "GOV-03"


class GovernanceKey:
    # Above this transaction value, an approval is only finalised after an explicit second
    # confirmation from the approver.
    APPROVAL_CONFIRMATION_VALUE = "approval_confirmation_value"
    # Ceiling on a transaction that may be approved as part of a batch rather than one at a time.
    BULK_APPROVAL_VALUE_CEILING = "bulk_approval_value_ceiling"
    # Hours a transaction may sit undecided before the queue calls it overdue and an
    # "approval not received" case is opened against it.
    APPROVAL_OVERDUE_HOURS = "approval_overdue_hours"
    # The second tier of the same clock. Past this, the case that was opened at the first
    # threshold is escalated in its own right, because an approver who has not acted on a
    # reminder is not going to be reached by repeating it. The discovery material asks for a TAT
    # per approval level rather than a single deadline; this is the second level's.
    APPROVAL_ESCALATION_HOURS = "approval_escalation_hours"
    # Hours an exception may sit open before the queue shows it as breaching its ageing threshold.
    EXCEPTION_AGEING_HOURS = "exception_ageing_hours"
    # Hours a shipment may go without anybody establishing where it is - by adapter or by hand -
    # before an owned exception is opened against it.
    SHIPMENT_STALE_HOURS = "shipment_stale_hours"
    # Consecutive failed tracking attempts that count as silence in their own right, without
    # waiting for the staleness clock.
    SHIPMENT_FAILURE_LIMIT = "shipment_failure_limit"
    # Days an ETA may move *earlier* before the change is treated as implausible and flagged for
    # a person to look at. Cargo does arrive ahead of schedule; it does not arrive a fortnight
    # ahead of schedule, and a jump like that is far more likely to be a misread than a miracle.
    SHIPMENT_ETA_REGRESSION_DAYS = "shipment_eta_regression_days"


# Read whenever the configured row is missing or has been deactivated. Every one of these is a
# deliberately cautious value: the confirmation dialog appears more often, the bulk action offers
# fewer rows, and a case is called overdue sooner than a missing configuration would otherwise
# allow. A misconfiguration must never quietly widen what may be approved without a second look.
FALLBACKS: dict[str, Decimal] = {
    GovernanceKey.APPROVAL_CONFIRMATION_VALUE: Decimal("0"),
    GovernanceKey.BULK_APPROVAL_VALUE_CEILING: Decimal("0"),
    GovernanceKey.APPROVAL_OVERDUE_HOURS: Decimal("24"),
    GovernanceKey.APPROVAL_ESCALATION_HOURS: Decimal("48"),
    GovernanceKey.EXCEPTION_AGEING_HOURS: Decimal("24"),
    GovernanceKey.SHIPMENT_STALE_HOURS: Decimal("24"),
    GovernanceKey.SHIPMENT_FAILURE_LIMIT: Decimal("2"),
    GovernanceKey.SHIPMENT_ETA_REGRESSION_DAYS: Decimal("3"),
}

_RULE_FOR_KEY: dict[str, str] = {
    GovernanceKey.APPROVAL_CONFIRMATION_VALUE: GovernanceRule.APPROVALS,
    GovernanceKey.BULK_APPROVAL_VALUE_CEILING: GovernanceRule.APPROVALS,
    GovernanceKey.APPROVAL_OVERDUE_HOURS: GovernanceRule.APPROVALS,
    GovernanceKey.APPROVAL_ESCALATION_HOURS: GovernanceRule.APPROVALS,
    GovernanceKey.EXCEPTION_AGEING_HOURS: GovernanceRule.EXCEPTIONS,
    GovernanceKey.SHIPMENT_STALE_HOURS: GovernanceRule.SHIPMENTS,
    GovernanceKey.SHIPMENT_FAILURE_LIMIT: GovernanceRule.SHIPMENTS,
    GovernanceKey.SHIPMENT_ETA_REGRESSION_DAYS: GovernanceRule.SHIPMENTS,
}


async def resolve(session: AsyncSession, key: str) -> Decimal:
    """The configured value for one governance key, or its cautious fallback."""
    row = await session.scalar(
        select(RuleConfiguration).where(
            RuleConfiguration.rule_id == _RULE_FOR_KEY.get(key, GovernanceRule.APPROVALS),
            RuleConfiguration.check_key == key,
            RuleConfiguration.is_active.is_(True),
        )
    )
    if row is None:
        return FALLBACKS[key]
    return Decimal(row.threshold_value)


async def resolve_many(session: AsyncSession, *keys: str) -> dict[str, Decimal]:
    return {key: await resolve(session, key) for key in keys}


def _row(rule_id: str, check_key: str, value: str, unit: str, description: str) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "check_key": check_key,
        "scope_commodity_code": None,
        "scope_transaction_type": None,
        "scope_stream": None,
        "threshold_value": Decimal(value),
        "threshold_unit": unit,
        "description": description,
        "is_active": True,
        "change_reason": SEED_CHANGE_REASON,
    }


def default_governance_configurations() -> list[dict[str, Any]]:
    """The shipped defaults. Every one is a row somebody can change without a release.

    The two hour-based rows carry the `count` unit because that is what the existing check
    constraint permits; their description states the unit they are actually counted in, and
    nothing reads the unit column to decide behaviour.
    """
    return [
        _row(
            GovernanceRule.APPROVALS,
            GovernanceKey.APPROVAL_CONFIRMATION_VALUE,
            "250000.00",
            "currency",
            "Transaction value above which an approval is only finalised after the approver "
            "confirms a second time. Not a business rule: it gates a screen, not a transaction.",
        ),
        _row(
            GovernanceRule.APPROVALS,
            GovernanceKey.BULK_APPROVAL_VALUE_CEILING,
            "50000.00",
            "currency",
            "Ceiling on a transaction eligible for the bulk approve action. Above it, and for "
            "anything carrying an acknowledged tolerance or a past exception, the approver "
            "decides one transaction at a time.",
        ),
        _row(
            GovernanceRule.APPROVALS,
            GovernanceKey.APPROVAL_OVERDUE_HOURS,
            "72",
            "count",
            "Hours a transaction may wait on a decision before the queue treats it as overdue "
            "and opens an 'approval not received' exception against it.",
        ),
        _row(
            GovernanceRule.APPROVALS,
            GovernanceKey.APPROVAL_ESCALATION_HOURS,
            "96",
            "count",
            "Hours a transaction may wait on a decision before the 'approval not received' case "
            "already open against it is escalated. The second tier of the same clock: the first "
            "tells the approving desk, this one says the desk has not acted on being told.",
        ),
        _row(
            GovernanceRule.EXCEPTIONS,
            GovernanceKey.EXCEPTION_AGEING_HOURS,
            "48",
            "count",
            "Hours an exception may stay open before the queue shows it as past its ageing "
            "threshold. Computed live from opened_at on every read, never stored.",
        ),
    ]


SHIPMENT_SEED_CHANGE_REASON = "Platform default shipped with the shipment tracking module."


def shipment_governance_configurations() -> list[dict[str, Any]]:
    """The shipment module's own thresholds, in the same table and the same namespace.

    Kept apart from `default_governance_configurations` for the reason every step's seed list is
    kept apart from the ones before it: that function is what the Step 4 migration writes, and it
    has to keep writing exactly what it wrote.
    """
    return [
        _row(
            GovernanceRule.SHIPMENTS,
            GovernanceKey.SHIPMENT_STALE_HOURS,
            "48",
            "count",
            "Hours a shipment may go without anybody establishing where it is before a "
            "Logistics-owned exception is opened against it. Counted in hours; the unit column "
            "reads 'count' because that is what the existing check constraint permits, and "
            "nothing reads the unit to decide behaviour.",
        ),
        _row(
            GovernanceRule.SHIPMENTS,
            GovernanceKey.SHIPMENT_FAILURE_LIMIT,
            "3",
            "count",
            "Consecutive failed tracking attempts after which a shipment is treated as silent "
            "in its own right, without waiting out the staleness clock. A carrier that has "
            "refused three times running is not about to answer the fourth.",
        ),
        _row(
            GovernanceRule.SHIPMENTS,
            GovernanceKey.SHIPMENT_ETA_REGRESSION_DAYS,
            "5",
            "count",
            "Days an ETA may move earlier in one update before the change is flagged as "
            "implausible for a person to confirm. Never a block: the change is saved either way, "
            "because a heuristic that refused a genuine correction would be worse than one that "
            "asks somebody to glance at it.",
        ),
    ]

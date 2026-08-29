"""Keeping shipments current, by whatever means is actually available.

The orchestration here is completely real and completely deterministic. What it orchestrates may
be nothing at all: on every deployment that ships today the adapter registry is empty, because no
carrier's tracking API is specified anywhere in this platform's material and none has been
fabricated. A shipment with no adapter is not an error and is not handled specially - it simply
falls through to the state it was already in, waiting for a person, on the same row and the same
screen an automatically tracked one would use.

Three things happen here and they are worth separating:

* **attempting a pull** - walk whichever adapters admit to handling this shipment, take the first
  that answers, and record honestly what happened either way;
* **applying an update** - the single function through which a status, milestone or ETA changes,
  whether an adapter or a person supplied it, so the plausibility check, the audit entry and the
  bookkeeping cannot be bypassed by one path and not the other;
* **the sweep** - a scheduled pass that attempts every active shipment and opens a real, owned
  exception against any that nobody has established anything about for too long.

Only one thing in this module is not deterministic, and it is deliberately the smallest part: an
adapter that returns prose rather than a structured milestone has that prose mapped onto the
platform's fixed vocabulary, by a keyword table first and by the existing Gemini service only if
the table cannot do it. Nothing about *when* to call, *whom* to call or *what to conclude* is an
AI decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.roles import PlatformRole
from app.db.base import utcnow
from app.models.enums import (
    SHIPMENT_MILESTONES,
    SHIPMENT_STATUSES,
    ExceptionCategory,
    ExceptionPriority,
    ShipmentMilestone,
    ShipmentStatus,
)
from app.models.governance import ExceptionCase
from app.models.identity import User
from app.models.logistics import Shipment
from app.models.transactions import TradeTransaction
from app.services.audit_service import ActorType, record_audit_event
from app.services.gemini_service import AIServiceError, parse_shipment_milestone
from app.services.governance import hooks as governance_hooks
from app.services.governance import thresholds
from app.services.logistics import shipment_service
from app.services.logistics.adapters import (
    TrackingQuery,
    TrackingResult,
    adapters_for,
    registered_adapters,
)
from app.services.logistics.shipment_service import MANUAL_SOURCE, AuditEvent

logger = get_logger(__name__)

# The deterministic first pass at a carrier's wording. Ordered longest-phrase-first within each
# milestone so "gate out" is not swallowed by "gate in"'s prefix, and checked before any model is
# consulted: most carriers write in a handful of stock phrases, and reading those with a keyword
# table is both free and reproducible.
MILESTONE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (ShipmentMilestone.DELIVERED.value, ("delivered", "delivery complete", "empty returned")),
    (ShipmentMilestone.GATE_OUT.value, ("gate out", "gated out", "picked up from terminal")),
    (ShipmentMilestone.DISCHARGED.value, ("discharged", "unloaded from vessel", "discharge")),
    (ShipmentMilestone.ARRIVED.value, ("arrived", "vessel arrival", "berthed")),
    (ShipmentMilestone.TRANSHIPPED.value, ("transhipment", "transshipment", "transhipped")),
    (ShipmentMilestone.IN_TRANSIT.value, ("in transit", "on water", "sailing")),
    (ShipmentMilestone.DEPARTED.value, ("departed", "vessel departure", "sailed")),
    (ShipmentMilestone.LOADED.value, ("loaded on board", "loaded", "shipped on board")),
    (ShipmentMilestone.GATE_IN.value, ("gate in", "gated in", "received at terminal")),
    (ShipmentMilestone.BOOKED.value, ("booking confirmed", "booked", "booking")),
)

# Words a carrier uses when it is telling you the shipment is late. Kept separate from the
# milestone table because "delayed at Colombo" is a status and a milestone at once.
DELAY_KEYWORDS: tuple[str, ...] = ("delay", "delayed", "rolled", "held", "detained", "late")


def keyword_milestone(description: str) -> str | None:
    """Read a milestone straight off the carrier's wording, or None if it cannot be read."""
    text = " ".join((description or "").lower().split())
    if not text:
        return None
    for milestone, keywords in MILESTONE_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            return milestone
    return None


def keyword_status(description: str) -> str | None:
    text = " ".join((description or "").lower().split())
    if any(keyword in text for keyword in DELAY_KEYWORDS):
        return ShipmentStatus.DELAYED.value
    return None


async def read_milestone(description: str | None) -> tuple[str | None, str | None, str]:
    """Map a carrier's free text onto the fixed vocabulary. Returns (milestone, status, how).

    The keyword table first, because it is deterministic, reproducible and right for the phrases
    carriers actually use. The model only where the table found nothing, and only where it is
    configured; a failed or unconfigured model call leaves the milestone unread, which the caller
    treats as "leave the shipment where it was" rather than as a reason to guess.
    """
    if not (description or "").strip():
        return None, None, "none"

    milestone = keyword_milestone(description or "")
    if milestone is not None:
        return milestone, keyword_status(description or ""), "keyword"

    try:
        reading = await parse_shipment_milestone(
            description or "",
            milestones=SHIPMENT_MILESTONES,
            statuses=SHIPMENT_STATUSES,
        )
    except AIServiceError as exc:
        logger.info("shipment_milestone_unparsed", extra={"reason": exc.reason})
        return None, None, "unparsed"

    if reading.milestone not in SHIPMENT_MILESTONES:
        return None, None, "unparsed"
    if reading.milestone == ShipmentMilestone.UNKNOWN.value:
        return None, None, "unparsed"
    status = reading.status if reading.status in SHIPMENT_STATUSES else None
    return reading.milestone, status, "ai"


# --- the plausibility check ----------------------------------------------------------------------


@dataclass(frozen=True)
class Plausibility:
    """Whether a proposed change looks like something that could actually have happened."""

    plausible: bool
    reason: str | None = None

    @property
    def flagged(self) -> bool:
        return not self.plausible


# Milestones that mean the cargo has physically finished a stage it cannot un-finish. A shipment
# reported as back in transit after it discharged is not impossible - a correction of a wrong
# earlier reading looks exactly like this - but it is worth a person's glance.
TERMINAL_MILESTONES: tuple[str, ...] = (
    ShipmentMilestone.DISCHARGED.value,
    ShipmentMilestone.GATE_OUT.value,
    ShipmentMilestone.DELIVERED.value,
)


def check_plausibility(
    shipment: Shipment,
    *,
    eta: date | None,
    milestone: str | None,
    regression_days: Decimal,
) -> Plausibility:
    """Is this change believable? Advisory only - it flags, it never refuses.

    A heuristic that blocked a save would be worse than the problem it solves: the single most
    likely reason an ETA jumps is that the earlier one was wrong, and refusing the correction
    would leave the wrong date in place and the desk with no way to fix it. So the change is
    saved, the shipment is marked for review, and somebody is told why.
    """
    reasons: list[str] = []

    if eta is not None and shipment.eta is not None and eta < shipment.eta:
        moved = (shipment.eta - eta).days
        if moved > int(regression_days):
            reasons.append(
                f"the ETA moved {moved} days earlier, from {shipment.eta.isoformat()} to "
                f"{eta.isoformat()}, which is further forward than a schedule realistically "
                f"moves in one update (the configured margin is {int(regression_days)} days)"
            )

    if (
        milestone is not None
        and shipment.current_milestone in TERMINAL_MILESTONES
        and milestone not in TERMINAL_MILESTONES
    ):
        reasons.append(
            f"the milestone went backwards, from '{shipment.current_milestone}' to "
            f"'{milestone}', and cargo does not un-discharge"
        )

    if not reasons:
        return Plausibility(plausible=True)
    return Plausibility(plausible=False, reason="; ".join(reasons))


# --- applying an update --------------------------------------------------------------------------


@dataclass
class ShipmentUpdate:
    """What is being changed. Every field optional; an omitted field is left alone."""

    status: str | None = None
    milestone: str | None = None
    eta: date | None = None
    etd: date | None = None
    carrier: str | None = None
    vessel: str | None = None
    port_of_loading: str | None = None
    port_of_discharge: str | None = None
    bl_number: str | None = None
    container_id: UUID | None = None
    # What the carrier actually said, where an adapter supplied prose. Kept on the audit entry
    # verbatim so a milestone that could not be parsed is still recoverable by a person.
    carrier_description: str | None = None
    note: str | None = None


@dataclass
class UpdateOutcome:
    shipment: Shipment
    changed: dict[str, tuple[str | None, str | None]] = field(default_factory=dict)
    plausibility: Plausibility = field(default_factory=lambda: Plausibility(True))

    @property
    def any_change(self) -> bool:
        return bool(self.changed)


def _rendered(value: object | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


async def apply_update(
    session: AsyncSession,
    shipment: Shipment,
    update: ShipmentUpdate,
    *,
    source: str,
    actor_id: UUID | None,
    mark_checked: bool = True,
) -> UpdateOutcome:
    """The one path a shipment changes through, automated or manual.

    Both callers come here - the adapter pull and the logistics desk's form - and that is the
    point. The plausibility check, the audit entry, the failure counter and `last_checked_at` are
    applied to a hand-typed change exactly as they are to a carrier's, because a manual update is
    not a lesser-scrutiny update just because no external system was involved in it.
    """
    regression_days = await thresholds.resolve(
        session, thresholds.GovernanceKey.SHIPMENT_ETA_REGRESSION_DAYS
    )
    plausibility = check_plausibility(
        shipment,
        eta=update.eta,
        milestone=update.milestone,
        regression_days=regression_days,
    )

    columns = {
        "status": update.status,
        "current_milestone": update.milestone,
        "eta": update.eta,
        "etd": update.etd,
        "carrier": update.carrier,
        "vessel": update.vessel,
        "port_of_loading": update.port_of_loading,
        "port_of_discharge": update.port_of_discharge,
        "bl_number": update.bl_number,
        "container_id": update.container_id,
    }

    changed: dict[str, tuple[str | None, str | None]] = {}
    for attribute, value in columns.items():
        if value is None:
            continue
        previous = getattr(shipment, attribute)
        if previous == value:
            continue
        setattr(shipment, attribute, value)
        changed[attribute] = (_rendered(previous), _rendered(value))

    if plausibility.flagged:
        shipment.review_flagged = True
        shipment.review_reason = plausibility.reason
        shipment.review_flagged_at = utcnow()
    elif changed and shipment.review_flagged and update.milestone is not None:
        # A subsequent, believable update from a person or a carrier clears the flag: the point of
        # the flag is that somebody should look, and a fresh believable reading is somebody
        # looking.
        shipment.review_flagged = False
        shipment.review_reason = None
        shipment.review_flagged_at = None

    if mark_checked:
        shipment.last_checked_at = utcnow()
        shipment.last_checked_source = source
        shipment.consecutive_failures = 0
        shipment.last_error = None
    shipment.updated_at = utcnow()
    await session.flush()

    await record_audit_event(
        session,
        event_type=AuditEvent.SHIPMENT_STATUS_UPDATED,
        entity_type="shipment",
        entity_id=shipment.id,
        actor_id=actor_id,
        actor_type=ActorType.USER if actor_id else ActorType.AGENT,
        metadata={
            "transaction_id": str(shipment.transaction_id),
            "source": source,
            "status": shipment.status,
            "milestone": shipment.current_milestone,
            "changes": {name: {"from": old, "to": new} for name, (old, new) in changed.items()},
            # Recorded on every update, not only the flagged ones, so the absence of a flag is
            # itself on the record rather than being inferred from a missing key.
            "plausibility_flagged": plausibility.flagged,
            "plausibility_reason": plausibility.reason,
            "carrier_description": update.carrier_description,
            "note": update.note,
        },
    )

    if plausibility.flagged:
        await record_audit_event(
            session,
            event_type=AuditEvent.SHIPMENT_REVIEW_FLAGGED,
            entity_type="shipment",
            entity_id=shipment.id,
            actor_id=actor_id,
            actor_type=ActorType.USER if actor_id else ActorType.AGENT,
            metadata={
                "transaction_id": str(shipment.transaction_id),
                "source": source,
                "reason": plausibility.reason,
                "status": shipment.status,
                "milestone": shipment.current_milestone,
                "blocked": False,
            },
        )

    return UpdateOutcome(shipment=shipment, changed=changed, plausibility=plausibility)


# --- attempting a pull ---------------------------------------------------------------------------


@dataclass
class RefreshOutcome:
    """What one refresh attempt actually achieved, said plainly.

    `attempted` is False when no adapter admitted to handling the shipment. That is the ordinary
    case today and the message says so without apology: the shipment is open for manual entry,
    which is a working path rather than a failure state.
    """

    shipment: Shipment
    attempted: bool
    updated: bool
    adapter: str | None
    message: str
    plausibility_flagged: bool = False


def query_for(shipment: Shipment) -> TrackingQuery:
    return TrackingQuery(
        container_number=(
            shipment.container.container_number if shipment.container is not None else None
        ),
        bl_number=shipment.bl_number,
        carrier=shipment.carrier,
    )


async def _record_failure(
    session: AsyncSession,
    shipment: Shipment,
    *,
    reason: str,
    adapter: str | None,
    actor_id: UUID | None,
) -> None:
    """A failed attempt is a real event with a real consequence: the counter moves.

    `last_checked_at` deliberately does not. A refusal is not a check, and letting a failing
    adapter keep the staleness clock at zero would mean a shipment nobody knows anything about
    never ageing into the queue.
    """
    shipment.consecutive_failures = int(shipment.consecutive_failures or 0) + 1
    shipment.last_error = reason
    shipment.updated_at = utcnow()
    await session.flush()
    await record_audit_event(
        session,
        event_type=AuditEvent.SHIPMENT_TRACKING_UNAVAILABLE,
        entity_type="shipment",
        entity_id=shipment.id,
        actor_id=actor_id,
        actor_type=ActorType.USER if actor_id else ActorType.SYSTEM,
        metadata={
            "transaction_id": str(shipment.transaction_id),
            "adapter": adapter,
            "unavailable_reason": reason,
            "consecutive_failures": shipment.consecutive_failures,
            "status": shipment.status,
            "milestone": shipment.current_milestone,
        },
    )


async def refresh_shipment(
    session: AsyncSession,
    shipment: Shipment,
    *,
    actor_id: UUID | None = None,
) -> RefreshOutcome:
    """Try every adapter that handles this shipment, and be honest when there are none.

    The on-demand refresh button and the scheduled sweep both call this, so what a person gets
    when they press refresh is exactly what the job does at three in the morning.
    """
    query = query_for(shipment)
    candidates = adapters_for(query)

    await record_audit_event(
        session,
        event_type=AuditEvent.SHIPMENT_TRACKING_ATTEMPTED,
        entity_type="shipment",
        entity_id=shipment.id,
        actor_id=actor_id,
        actor_type=ActorType.USER if actor_id else ActorType.SYSTEM,
        metadata={
            "transaction_id": str(shipment.transaction_id),
            "adapters_registered": len(registered_adapters()),
            "adapters_matching": [adapter.name for adapter in candidates],
        },
    )

    if not candidates:
        # Not an error, and not written as one. Almost every shipment on this platform is here.
        return RefreshOutcome(
            shipment=shipment,
            attempted=False,
            updated=False,
            adapter=None,
            message=(
                "No carrier tracking source is available for this shipment, so its status is "
                "kept up to date by hand. Enter what the carrier told you below - it is recorded, "
                "audited and displayed exactly as an automatic reading would be."
            ),
        )

    last_reason = "The carrier tracking source returned nothing."
    for adapter in candidates:
        try:
            result = await adapter.fetch(query)
        except Exception as exc:
            # An adapter that raises is a failing integration, never a failing request. The
            # provider's own message stays server-side.
            logger.warning(
                "carrier_adapter_failed",
                extra={"adapter": adapter.name, "reason": type(exc).__name__},
            )
            last_reason = f"{adapter.name} could not be reached."
            continue

        if not isinstance(result, TrackingResult) or not result.available:
            last_reason = (
                getattr(result, "unavailable_reason", None)
                or f"{adapter.name} has no tracking data for this shipment."
            )
            continue

        milestone = result.milestone if result.milestone in SHIPMENT_MILESTONES else None
        status = result.status if result.status in SHIPMENT_STATUSES else None
        if milestone is None:
            milestone, parsed_status, _how = await read_milestone(result.milestone_description)
            status = status or parsed_status

        outcome = await apply_update(
            session,
            shipment,
            ShipmentUpdate(
                status=status,
                milestone=milestone,
                eta=result.eta,
                etd=result.etd,
                carrier=result.carrier,
                vessel=result.vessel,
                port_of_discharge=result.port_of_discharge,
                carrier_description=result.milestone_description,
            ),
            source=adapter.name,
            actor_id=actor_id,
        )
        return RefreshOutcome(
            shipment=shipment,
            attempted=True,
            updated=outcome.any_change,
            adapter=adapter.name,
            message=(
                f"{adapter.name} reported this shipment as {shipment.milestone.replace('_', ' ')}."
                if outcome.any_change
                else f"{adapter.name} answered, and nothing has changed since the last check."
            ),
            plausibility_flagged=outcome.plausibility.flagged,
        )

    await _record_failure(
        session, shipment, reason=last_reason, adapter=candidates[0].name, actor_id=actor_id
    )
    return RefreshOutcome(
        shipment=shipment,
        attempted=True,
        updated=False,
        adapter=candidates[0].name,
        message=(
            f"{last_reason} The shipment is unchanged and open for manual entry; the failed "
            "attempt is recorded against it."
        ),
    )


async def apply_manual_update(
    session: AsyncSession,
    shipment: Shipment,
    update: ShipmentUpdate,
    *,
    user: User,
) -> UpdateOutcome:
    """A person establishing where the cargo is. The same write, held to the same standard.

    Identical to what an adapter's result goes through: same function, same plausibility check,
    same audit entry, same `last_checked_at`. The only difference recorded anywhere is the source
    on the audit trail, which is where a question about provenance belongs.
    """
    return await apply_update(session, shipment, update, source=MANUAL_SOURCE, actor_id=user.id)


# --- staleness, into the exception queue the rest of the platform already uses -------------------


async def open_stale_case(
    session: AsyncSession,
    shipment: Shipment,
    *,
    stale_hours: float,
    failure_limit: int,
) -> ExceptionCase | None:
    """Open a Logistics-owned exception against a shipment nobody knows anything about.

    Note what this does *not* do. It does not synthesise a rule evaluation, it does not invent a
    rule identifier, and it does not route through the rule-to-category mapping table. Shipment
    staleness is not a check on extracted data, and dressing it up as one to reuse the hard-fail
    hook would put a fabricated evaluation in a table auditors read as a record of real checks.

    It calls the standalone case-creation function directly instead - the same function, the same
    table, the same ten categories and the same queue every other exception uses - which is
    exactly what that function was built to be reachable as.
    """
    waited = int(shipment_service.hours_since_check(shipment))
    failures = int(shipment.consecutive_failures or 0)
    transaction = await session.get(TradeTransaction, shipment.transaction_id)
    if transaction is None:
        return None

    if failures >= failure_limit:
        detail = f"{failures} consecutive tracking attempts have failed" + (
            f" ({shipment.last_error})" if shipment.last_error else ""
        )
    else:
        detail = f"nobody has established where it is for {waited} hours"

    case = await governance_hooks.open_case(
        session,
        category=ExceptionCategory.SHIPMENT_STATUS_UNAVAILABLE.value,
        owner_role=PlatformRole.LOGISTICS_USER.value,
        priority=ExceptionPriority.MEDIUM.value,
        summary=(
            "Shipment "
            + (f"{shipment.bl_number} " if shipment.bl_number else "")
            + f"on batch {transaction.batch_number}: {detail}, past the configured "
            f"{int(stale_hours)}-hour threshold. Where no carrier tracking source is available - "
            "which is most shipments - keeping this current is a person's job, and this case is "
            "the reminder that nobody has."
        ),
        transaction_id=transaction.id,
        request_id=transaction.request_id,
        field_name="last_checked_at",
        expected_value=f"checked within {int(stale_hours)} hours",
        actual_value=(
            f"{waited} hours since the last check"
            + (f", {failures} failed attempts" if failures else "")
        ),
    )
    if case is None:
        return None

    await record_audit_event(
        session,
        event_type=AuditEvent.SHIPMENT_STALE,
        entity_type="shipment",
        entity_id=shipment.id,
        actor_type=ActorType.SYSTEM,
        metadata={
            "transaction_id": str(shipment.transaction_id),
            "exception_case_id": str(case.id),
            "hours_since_check": waited,
            "consecutive_failures": failures,
            "threshold_hours": int(stale_hours),
            "status": shipment.status,
            "milestone": shipment.current_milestone,
        },
    )
    return case


@dataclass
class SweepResult:
    considered: int = 0
    attempted: int = 0
    updated: int = 0
    left_for_manual: int = 0
    flagged: int = 0
    exceptions_opened: int = 0


async def active_shipments(session: AsyncSession, *, limit: int) -> list[Shipment]:
    """Every shipment tracking still has something to find out about, oldest check first."""
    rows = (
        await session.scalars(
            select(Shipment)
            .where(Shipment.status != ShipmentStatus.ARRIVED.value)
            .order_by(Shipment.last_checked_at.is_(None).desc(), Shipment.last_checked_at)
            .limit(limit)
        )
    ).all()
    return [row for row in rows if shipment_service.is_active(row)]


async def run_sweep(session: AsyncSession, *, limit: int = 100) -> SweepResult:
    """One scheduled pass: attempt every active shipment, then age the silent ones into the queue.

    Every shipment is attempted, including the ones that will find no adapter. That is not a
    wasted call - it is what records, on the audit trail, that the platform looked and there was
    nothing to look at, which is the honest history of a shipment nobody can track automatically.
    """
    stale_hours = float(
        await thresholds.resolve(session, thresholds.GovernanceKey.SHIPMENT_STALE_HOURS)
    )
    failure_limit = int(
        await thresholds.resolve(session, thresholds.GovernanceKey.SHIPMENT_FAILURE_LIMIT)
    )

    result = SweepResult()
    for shipment in await active_shipments(session, limit=limit):
        result.considered += 1
        outcome = await refresh_shipment(session, shipment)
        if outcome.attempted:
            result.attempted += 1
        else:
            result.left_for_manual += 1
        if outcome.updated:
            result.updated += 1
        if outcome.plausibility_flagged:
            result.flagged += 1

        overdue = shipment_service.hours_since_check(shipment) >= stale_hours
        failing = int(shipment.consecutive_failures or 0) >= failure_limit
        if overdue or failing:
            case = await open_stale_case(
                session, shipment, stale_hours=stale_hours, failure_limit=failure_limit
            )
            if case is not None:
                result.exceptions_opened += 1

    await session.flush()
    return result

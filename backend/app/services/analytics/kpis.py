"""Every figure this step displays, computed here and nowhere else.

Read the definitions in :data:`KPI_DEFINITIONS` before the code. Several of the KPIs this platform
is asked for are named descriptively rather than defined, and where that is so the definition
used is written out in full, in the same words the screen shows the reader. Two of them involve a
judgement and both say so out loud:

**Extraction accuracy is a non-override rate.** It is the percentage of extracted fields a person
did not correct. Nothing anywhere in this platform holds a ground truth for what a document
actually said, so no verified-correctness measure is computable, and presenting this one as if it
were would be a claim the data cannot support. Every label the API returns says "not overridden";
none says "accurate".

**Automation percentage counts transactions that never had an exception opened against them.** It
is a measure of how much of the pipeline ran without a person having to intervene formally - not
of how much of it was untouched by human hands, which would be a different and much harder
question.

Two rules hold everywhere in this module. Every figure is a grouped count or a duration over the
governed tables directly; there is no rollup table, no stored total and no snapshot. And every
scope constraint is applied as a `WHERE` clause before the `GROUP BY`, so a figure that a role may
not see was never counted rather than counted and then hidden.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import Select, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.base import utcnow
from app.models.enums import (
    APPROVAL_DECISIONS,
    EXCEPTION_CATEGORIES,
    INTEGRATION_JOB_STATUSES,
    SHIPMENT_STATUSES,
    ApprovalDecision,
    IntegrationJobStatus,
    TransactionStatus,
)
from app.models.governance import ApprovalTask, ExceptionCase
from app.models.intake import Document, ExtractedField, Request
from app.models.integration import IntegrationJob
from app.models.logistics import Shipment
from app.models.transactions import TradeTransaction
from app.services.analytics.scope import DashboardScope
from app.services.governance import thresholds

# The statuses a transaction can genuinely be in. `closed` is declared in the vocabulary and no
# code path reaches it, so a tile for it would be a permanent, meaningless zero rather than an
# informative one.
REPORTABLE_TRANSACTION_STATUSES: tuple[str, ...] = tuple(
    status.value for status in TransactionStatus if status is not TransactionStatus.CLOSED
)

# Approved or later: what "the automation got it through" means in this lifecycle's own words.
APPROVED_OR_LATER: tuple[str, ...] = (
    TransactionStatus.APPROVED.value,
    TransactionStatus.INTEGRATION_PENDING.value,
    TransactionStatus.COMMITTED.value,
)

# The ageing bands the exception queue is read in. Hours, matching how the queue itself ages a
# case: computed from `opened_at` against the clock at query time, never from a stored value.
AGE_BANDS: tuple[tuple[str, str, int, int | None], ...] = (
    ("under_24h", "Under 24 hours", 0, 24),
    ("24_to_72h", "24 to 72 hours", 24, 72),
    ("over_72h", "Over 72 hours", 72, None),
)

KPI_DEFINITIONS: dict[str, str] = {
    "transactions_by_status": (
        "A grouped count of transactions by their current status, from `trade_transactions` "
        "directly."
    ),
    "open_exceptions": (
        "Unresolved exception cases grouped by category, with each case's age computed from "
        "`opened_at` against the clock at the moment of the query. No age is ever stored."
    ),
    "approval_queue_depth": "Approval tasks whose decision is still `pending`.",
    "extraction_non_override_rate": (
        "The percentage of extracted fields in the period that a person did NOT override. A "
        "stated proxy for extraction quality, not a verified-correctness measurement: this "
        "platform holds no ground truth for what a document said, so no such measurement exists."
    ),
    "processing_turnaround": (
        "Mean and median hours from a request's `created_at` to the `decided_at` of the approved "
        "decision on the transaction it produced."
    ),
    "automation_rate": (
        "The percentage of transactions approved in the period against which no exception case "
        "was ever opened."
    ),
    "integration_failures": (
        "Integration jobs in `failed`. Counted separately from jobs awaiting a person, always."
    ),
    "integration_awaiting_manual": (
        "Integration jobs in `awaiting_manual_action`. Neither a success nor a failure, and "
        "never merged into the failure count."
    ),
    "shipments_by_status": (
        "A grouped count of shipments by status, with a separate count of those nobody has "
        "established a position for within the configured staleness threshold."
    ),
}


@dataclass(frozen=True)
class Period:
    """A half-open window, `[start, end)`, always in UTC."""

    start: datetime
    end: datetime

    @property
    def days(self) -> int:
        return max(1, (self.end - self.start).days)

    def as_params(self) -> dict[str, str]:
        return {"date_from": self.start.isoformat(), "date_to": self.end.isoformat()}


def default_period(days: int = 30, *, now: datetime | None = None) -> Period:
    end = now or utcnow()
    return Period(start=end - timedelta(days=days), end=end)


def day_period(day: datetime) -> Period:
    """The whole UTC day containing `day`."""
    start = day.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return Period(start=start, end=start + timedelta(days=1))


def month_period(moment: datetime) -> Period:
    """The whole calendar month containing `moment`, in UTC."""
    start = moment.astimezone(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    end = (start + timedelta(days=32)).replace(day=1)
    return Period(start=start, end=end)


def previous_month_period(moment: datetime) -> Period:
    current = month_period(moment)
    return month_period(current.start - timedelta(days=1))


@dataclass
class Figure:
    """One number, what it means, and the query that reproduces it.

    `drill_through` is not decoration. Every figure this platform shows has to be openable, and a
    figure carrying no route back to its rows is exactly the dead end this step exists to remove.
    """

    key: str
    label: str
    # None where there is genuinely nothing to measure. A zero would be a claim, not a gap.
    value: float | int | None
    unit: str = "count"
    target: str | None = None
    filters: dict[str, Any] = field(default_factory=dict)
    note: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "value": self.value,
            "unit": self.unit,
            "target": self.target,
            "filters": {k: v for k, v in self.filters.items() if v is not None},
            "note": self.note,
        }


# --- scope application ------------------------------------------------------------------------
#
# One helper per governed table, so "which rows may this account count" is answered in exactly one
# place per table and every caller below is structurally unable to forget it.


def _scope_transactions(statement: Select, scope: DashboardScope) -> Select:
    if scope.empty:
        return statement.where(TradeTransaction.id.is_(None))
    return statement.where(TradeTransaction.stream.in_(scope.sorted_streams))


def _scope_exceptions(statement: Select, scope: DashboardScope) -> Select:
    """Category first, then stream through the transaction the case is attached to.

    A case with no transaction - a low-confidence extraction on a document nobody has matched yet
    - has no stream to be in. It is counted in an unfiltered view, because it is real work that
    somebody owns, and left out of a view narrowed to one business line, because claiming it for
    that line would be an invention.
    """
    if scope.empty or not scope.exception_categories:
        return statement.where(ExceptionCase.id.is_(None))
    statement = statement.where(
        ExceptionCase.exception_type.in_(scope.sorted_categories)
    ).outerjoin(TradeTransaction, TradeTransaction.id == ExceptionCase.transaction_id)
    if scope.stream_explicit:
        return statement.where(TradeTransaction.stream.in_(scope.sorted_streams))
    return statement.where(
        or_(
            ExceptionCase.transaction_id.is_(None),
            TradeTransaction.stream.in_(scope.sorted_streams),
        )
    )


def _scope_documents(statement: Select, scope: DashboardScope) -> Select:
    """Through the request the document arrived on, which is where its stream is recorded."""
    if scope.empty:
        return statement.where(Document.id.is_(None))
    statement = statement.outerjoin(Request, Request.id == Document.request_id)
    if scope.stream_explicit:
        return statement.where(Request.stream.in_(scope.sorted_streams))
    return statement.where(or_(Request.stream.is_(None), Request.stream.in_(scope.sorted_streams)))


# --- 9.4: transaction counts by status ----------------------------------------------------------


async def transaction_status_counts(
    session: AsyncSession,
    scope: DashboardScope,
    *,
    period: Period | None = None,
) -> list[Figure]:
    statement = _scope_transactions(
        select(TradeTransaction.status, func.count(TradeTransaction.id)), scope
    )
    if period is not None:
        statement = statement.where(
            TradeTransaction.created_at >= period.start,
            TradeTransaction.created_at < period.end,
        )
    rows = dict((await session.execute(statement.group_by(TradeTransaction.status))).all())

    # Every status, including the ones sitting at zero. A tile that vanishes when its count is
    # zero makes an empty queue indistinguishable from a queue nobody built a tile for.
    return [
        Figure(
            key=f"transactions.{status}",
            label=status.replace("_", " ").capitalize(),
            value=int(rows.get(status, 0)),
            target="transactions",
            filters={"status": status, **(period.as_params() if period else {})},
        )
        for status in REPORTABLE_TRANSACTION_STATUSES
    ]


# --- 9.4: exception counts by category, with live ageing ----------------------------------------


async def exception_counts(
    session: AsyncSession,
    scope: DashboardScope,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    moment = now or utcnow()
    cut_24 = moment - timedelta(hours=24)
    cut_72 = moment - timedelta(hours=72)

    statement = _scope_exceptions(
        select(
            ExceptionCase.exception_type,
            func.count(ExceptionCase.id),
            # Ageing bands, computed against the clock at query time from `opened_at`. There is no
            # stored age column anywhere in this platform and this is why: a stored one would be
            # exactly as fresh as whatever last wrote it.
            func.sum(case((ExceptionCase.opened_at >= cut_24, 1), else_=0)),
            func.sum(
                case(
                    (
                        (ExceptionCase.opened_at < cut_24) & (ExceptionCase.opened_at >= cut_72),
                        1,
                    ),
                    else_=0,
                )
            ),
            func.sum(case((ExceptionCase.opened_at < cut_72, 1), else_=0)),
            func.min(ExceptionCase.opened_at),
            func.sum(case((ExceptionCase.escalated.is_(True), 1), else_=0)),
        ).where(ExceptionCase.resolved_at.is_(None)),
        scope,
    ).group_by(ExceptionCase.exception_type)

    rows = {row[0]: row for row in (await session.execute(statement)).all()}

    categories: list[dict[str, Any]] = []
    for category in EXCEPTION_CATEGORIES:
        if category not in scope.exception_categories:
            # Not a zero and not hidden: a category this account's roles cannot work is simply not
            # part of its queue, and the query above never counted it.
            continue
        row = rows.get(category)
        oldest = row[5] if row else None
        categories.append(
            {
                "category": category,
                "label": category.replace("_", " ").capitalize(),
                "open_count": int(row[1]) if row else 0,
                "escalated_count": int(row[6] or 0) if row else 0,
                "ageing": {
                    "under_24h": int(row[2] or 0) if row else 0,
                    "24_to_72h": int(row[3] or 0) if row else 0,
                    "over_72h": int(row[4] or 0) if row else 0,
                },
                "oldest_age_hours": _age_hours(oldest, moment),
                "target": "exceptions",
                "filters": {"exception_type": category, "status": "open"},
            }
        )

    total = sum(row["open_count"] for row in categories)
    over_72 = sum(row["ageing"]["over_72h"] for row in categories)
    return {
        "categories": categories,
        "total_open": total,
        "over_72h": over_72,
        "bands": [
            {"key": key, "label": label, "from_hours": low, "to_hours": high}
            for key, label, low, high in AGE_BANDS
        ],
        "computed_at": moment.isoformat(),
    }


def _age_hours(opened_at: datetime | None, now: datetime) -> float | None:
    if opened_at is None:
        return None
    if opened_at.tzinfo is None:
        opened_at = opened_at.replace(tzinfo=timezone.utc)
    return round(max(0.0, (now - opened_at).total_seconds() / 3600.0), 2)


# --- 9.4: approval-queue depth --------------------------------------------------------------------


async def approval_queue_depth(
    session: AsyncSession,
    scope: DashboardScope,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    moment = now or utcnow()
    statement = _scope_transactions(
        select(func.count(ApprovalTask.id), func.min(ApprovalTask.requested_at))
        .join(TradeTransaction, TradeTransaction.id == ApprovalTask.transaction_id)
        .where(ApprovalTask.decision == ApprovalDecision.PENDING.value),
        scope,
    )
    count, oldest = (await session.execute(statement)).one()
    return {
        "pending": int(count or 0),
        "oldest_waiting_hours": _age_hours(oldest, moment),
        "target": "approvals",
        "filters": {"decision": ApprovalDecision.PENDING.value},
    }


async def approval_decision_counts(
    session: AsyncSession, scope: DashboardScope, period: Period
) -> dict[str, int]:
    statement = _scope_transactions(
        select(ApprovalTask.decision, func.count(ApprovalTask.id))
        .join(TradeTransaction, TradeTransaction.id == ApprovalTask.transaction_id)
        .where(
            ApprovalTask.decided_at.is_not(None),
            ApprovalTask.decided_at >= period.start,
            ApprovalTask.decided_at < period.end,
        ),
        scope,
    ).group_by(ApprovalTask.decision)
    rows = dict((await session.execute(statement)).all())
    return {decision: int(rows.get(decision, 0)) for decision in APPROVAL_DECISIONS}


# --- 9.4: extraction accuracy, honestly a non-override rate ---------------------------------------


async def extraction_non_override_rate(
    session: AsyncSession, scope: DashboardScope, period: Period
) -> dict[str, Any]:
    """The share of extracted fields nobody had to correct, overall and per document type.

    Labelled everywhere it appears as a non-override rate. It is a real, computable statement
    about how often the extraction was left alone; it is not, and is never presented as, a
    statement about how often it was right.
    """
    statement = _scope_documents(
        select(
            Document.document_type,
            func.count(ExtractedField.id),
            func.sum(case((ExtractedField.is_overridden.is_(True), 1), else_=0)),
        )
        .select_from(ExtractedField)
        .join(Document, Document.id == ExtractedField.document_id)
        .where(
            ExtractedField.created_at >= period.start,
            ExtractedField.created_at < period.end,
        ),
        scope,
    ).group_by(Document.document_type)

    by_type: list[dict[str, Any]] = []
    total = 0
    overridden_total = 0
    for document_type, count, overridden in (await session.execute(statement)).all():
        count = int(count or 0)
        overridden = int(overridden or 0)
        total += count
        overridden_total += overridden
        by_type.append(
            {
                "document_type": document_type or "unknown",
                "field_count": count,
                "overridden_count": overridden,
                "non_override_rate": _percentage(count - overridden, count),
                "target": "documents",
                "filters": {"document_type": document_type} if document_type else {},
            }
        )
    by_type.sort(key=lambda row: (-row["field_count"], row["document_type"]))

    return {
        "field_count": total,
        "overridden_count": overridden_total,
        "non_override_rate": _percentage(total - overridden_total, total),
        "by_document_type": by_type,
        "measure": "non_override_rate",
        "disclosure": (
            "The share of extracted fields a person did not override. A stated proxy for "
            "extraction quality, not a verified-correctness measurement."
        ),
    }


def _percentage(part: int, whole: int) -> float | None:
    """None, not zero, when there is nothing to divide: 0% and "no data" are different answers."""
    if whole <= 0:
        return None
    return round(part * 100.0 / whole, 2)


# --- 9.4: turnaround and automation, from one set of approved rows --------------------------------


@dataclass(frozen=True)
class ApprovedRow:
    transaction_id: Any
    requested_from: datetime
    decided_at: datetime
    had_exception: bool

    @property
    def hours(self) -> float:
        start = _aware(self.requested_from)
        end = _aware(self.decided_at)
        return max(0.0, (end - start).total_seconds() / 3600.0)


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


async def approved_rows(
    session: AsyncSession, scope: DashboardScope, period: Period
) -> list[ApprovedRow]:
    """Every transaction approved inside the period, with the two facts both KPIs need.

    One query for both, because turnaround and automation are two questions about the same set of
    approvals and running them apart invites the day when they disagree about which approvals
    they were talking about.

    The exception test is `EXISTS`, unfiltered by category on purpose: "was an exception ever
    opened against this transaction" is a property of the transaction, not exception detail being
    disclosed - no category, owner or summary crosses the boundary, only a boolean.
    """
    had_exception = (
        select(ExceptionCase.id).where(ExceptionCase.transaction_id == TradeTransaction.id).exists()
    )
    statement = _scope_transactions(
        select(
            TradeTransaction.id,
            Request.created_at,
            ApprovalTask.decided_at,
            had_exception,
        )
        .join(ApprovalTask, ApprovalTask.transaction_id == TradeTransaction.id)
        .join(Request, Request.id == TradeTransaction.request_id)
        .where(
            ApprovalTask.decision == ApprovalDecision.APPROVED.value,
            ApprovalTask.decided_at.is_not(None),
            ApprovalTask.decided_at >= period.start,
            ApprovalTask.decided_at < period.end,
        ),
        scope,
    )
    return [
        ApprovedRow(
            transaction_id=row[0],
            requested_from=row[1],
            decided_at=row[2],
            had_exception=bool(row[3]),
        )
        for row in (await session.execute(statement)).all()
        if row[1] is not None and row[2] is not None
    ]


def turnaround_from(rows: list[ApprovedRow]) -> dict[str, Any]:
    durations = sorted(row.hours for row in rows)
    return {
        "sample_size": len(durations),
        "mean_hours": round(statistics.fmean(durations), 2) if durations else None,
        "median_hours": round(statistics.median(durations), 2) if durations else None,
        "fastest_hours": round(durations[0], 2) if durations else None,
        "slowest_hours": round(durations[-1], 2) if durations else None,
        "definition": KPI_DEFINITIONS["processing_turnaround"],
    }


def automation_from(rows: list[ApprovedRow]) -> dict[str, Any]:
    total = len(rows)
    automated = sum(1 for row in rows if not row.had_exception)
    return {
        "approved_count": total,
        "exception_free_count": automated,
        "intervened_count": total - automated,
        "automation_rate": _percentage(automated, total),
        "definition": KPI_DEFINITIONS["automation_rate"],
    }


def bucket_series(rows: list[ApprovedRow], period: Period, *, interval: str) -> list[dict]:
    """Turnaround and automation per bucket, from the rows already fetched.

    Bucketed in Python rather than with a database date function on purpose: the two dialects this
    platform runs on truncate a timestamp differently, and a KPI that reads differently on the
    test database than on the production one is worse than no KPI.
    """
    step = timedelta(days=7 if interval == "week" else 1)
    buckets: list[dict[str, Any]] = []
    cursor = _floor(period.start, interval)
    while cursor < period.end:
        window_end = cursor + step
        inside = [row for row in rows if cursor <= _aware(row.decided_at) < window_end]
        durations = sorted(row.hours for row in inside)
        automated = sum(1 for row in inside if not row.had_exception)
        buckets.append(
            {
                "bucket_start": cursor.isoformat(),
                "bucket_end": window_end.isoformat(),
                "approved_count": len(inside),
                "mean_hours": round(statistics.fmean(durations), 2) if durations else None,
                "median_hours": round(statistics.median(durations), 2) if durations else None,
                "exception_free_count": automated,
                "intervened_count": len(inside) - automated,
                "automation_rate": _percentage(automated, len(inside)),
            }
        )
        cursor = window_end
    return buckets


def _floor(moment: datetime, interval: str) -> datetime:
    start = _aware(moment).replace(hour=0, minute=0, second=0, microsecond=0)
    if interval == "week":
        start -= timedelta(days=start.weekday())
    return start


# --- 9.4: integration failures and awaiting-manual, always two figures ----------------------------


async def integration_counts(session: AsyncSession, scope: DashboardScope) -> dict[str, Any]:
    """Two separate figures, and this function will never return one that merges them.

    Step 7 was explicit that a job waiting on a person is neither a success nor a failure. A
    dashboard that added them together would undo, in one tile, the distinction that module was
    built to preserve.
    """
    statement = _scope_transactions(
        select(IntegrationJob.status, func.count(IntegrationJob.id)).join(
            TradeTransaction, TradeTransaction.id == IntegrationJob.transaction_id
        ),
        scope,
    ).group_by(IntegrationJob.status)
    rows = dict((await session.execute(statement)).all())

    manual_statement = _scope_transactions(
        select(func.count(IntegrationJob.id))
        .join(TradeTransaction, TradeTransaction.id == IntegrationJob.transaction_id)
        .where(IntegrationJob.completed_manually.is_(True)),
        scope,
    )
    completed_manually = int(await session.scalar(manual_statement) or 0)

    return {
        "by_status": {status: int(rows.get(status, 0)) for status in INTEGRATION_JOB_STATUSES},
        "failed": int(rows.get(IntegrationJobStatus.FAILED.value, 0)),
        "awaiting_manual_action": int(
            rows.get(IntegrationJobStatus.AWAITING_MANUAL_ACTION.value, 0)
        ),
        "succeeded": int(rows.get(IntegrationJobStatus.SUCCEEDED.value, 0)),
        "in_flight": int(rows.get(IntegrationJobStatus.QUEUED.value, 0))
        + int(rows.get(IntegrationJobStatus.PROCESSING.value, 0)),
        "completed_manually": completed_manually,
        "separation_note": (
            "A posting waiting on a person is not a failure. The two counts are reported apart "
            "here and everywhere else, and are never added together."
        ),
    }


# --- 9.4: shipment status summary -----------------------------------------------------------------


async def shipment_summary(
    session: AsyncSession,
    scope: DashboardScope,
    *,
    stale_hours: float,
    now: datetime | None = None,
) -> dict[str, Any]:
    moment = now or utcnow()
    cutoff = moment - timedelta(hours=stale_hours)

    statement = _scope_transactions(
        select(Shipment.status, func.count(Shipment.id)).join(
            TradeTransaction, TradeTransaction.id == Shipment.transaction_id
        ),
        scope,
    ).group_by(Shipment.status)
    rows = dict((await session.execute(statement)).all())

    stale_statement = _scope_transactions(
        select(func.count(Shipment.id))
        .join(TradeTransaction, TradeTransaction.id == Shipment.transaction_id)
        .where(
            or_(Shipment.last_checked_at.is_(None), Shipment.last_checked_at < cutoff),
        ),
        scope,
    )
    stale = int(await session.scalar(stale_statement) or 0)

    return {
        "by_status": [
            {
                "status": status,
                "label": status.replace("_", " ").capitalize(),
                "count": int(rows.get(status, 0)),
                "target": "shipments",
                "filters": {"status": status},
            }
            for status in SHIPMENT_STATUSES
        ],
        "total": sum(int(value) for value in rows.values()),
        "stale_count": stale,
        "stale_threshold_hours": stale_hours,
        "stale_target": "shipments",
        "stale_filters": {"stale_only": True},
    }


# --- the two assembled payloads the API serves ----------------------------------------------------


async def build_summary(
    session: AsyncSession,
    scope: DashboardScope,
    *,
    period: Period | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Everything the Dashboard's tiles and charts need, in one round of scoped queries."""
    moment = now or utcnow()
    window = period or default_period(30, now=moment)
    stale_hours = float(
        await thresholds.resolve(session, thresholds.GovernanceKey.SHIPMENT_STALE_HOURS)
    )

    statuses = await transaction_status_counts(session, scope)
    exceptions = await exception_counts(session, scope, now=moment)
    approvals = await approval_queue_depth(session, scope, now=moment)
    integrations = await integration_counts(session, scope)
    shipments = await shipment_summary(session, scope, stale_hours=stale_hours, now=moment)
    rows = await approved_rows(session, scope, window)
    extraction = await extraction_non_override_rate(session, scope, window)
    automation = automation_from(rows)
    non_override = extraction["non_override_rate"]

    open_transactions = sum(
        figure.value
        for figure in statuses
        if figure.key.rsplit(".", 1)[-1] not in APPROVED_OR_LATER
    )

    tiles = [
        Figure(
            key="tile.open_transactions",
            label="Transactions in flight",
            value=open_transactions,
            target="transactions",
            note="Everything not yet approved.",
        ),
        Figure(
            key="tile.open_exceptions",
            label="Open exceptions",
            value=exceptions["total_open"],
            target="exceptions",
            filters={"status": "open"},
            note=f"{exceptions['over_72h']} of them open for more than 72 hours.",
        ),
        Figure(
            key="tile.approval_queue",
            label="Waiting on a decision",
            value=approvals["pending"],
            target="approvals",
            filters={"decision": ApprovalDecision.PENDING.value},
            note=(
                f"Oldest has waited {approvals['oldest_waiting_hours']:.0f} hours."
                if approvals["oldest_waiting_hours"] is not None
                else "Nothing is waiting."
            ),
        ),
        Figure(
            key="tile.integration_failed",
            label="Integration failures",
            value=integrations["failed"],
            target="integrations",
            filters={"status": IntegrationJobStatus.FAILED.value},
            note="Postings that genuinely failed after every automatic attempt.",
        ),
        Figure(
            key="tile.integration_awaiting_manual",
            label="Postings awaiting a person",
            value=integrations["awaiting_manual_action"],
            target="integrations",
            filters={"status": IntegrationJobStatus.AWAITING_MANUAL_ACTION.value},
            note="Not a failure: the platform has done all it can and somebody has to finish it.",
        ),
        Figure(
            key="tile.stale_shipments",
            label="Shipments past their check window",
            value=shipments["stale_count"],
            target="shipments",
            filters={"stale_only": True},
            note=f"Nobody has established a position for {int(stale_hours)} hours or more.",
        ),
        Figure(
            key="tile.extraction_non_override",
            label="Fields not overridden",
            value=non_override if non_override is not None else 0,
            unit="percent",
            target="documents",
            note=extraction["disclosure"],
        ),
        Figure(
            key="tile.automation_rate",
            label="Approved without an exception",
            value=automation["automation_rate"] or 0,
            unit="percent",
            target="transactions",
            filters={"status": TransactionStatus.APPROVED.value},
            note=(
                f"{automation['exception_free_count']} of {automation['approved_count']} "
                "approvals in the last 30 days needed no formal intervention."
            ),
        ),
    ]

    return {
        "generated_at": moment.isoformat(),
        "period": {"start": window.start.isoformat(), "end": window.end.isoformat()},
        "emphasis": scope.emphasis,
        "streams": scope.sorted_streams,
        "scope_note": _scope_note(scope),
        "tiles": [figure.as_dict() for figure in tiles],
        "transactions_by_status": [figure.as_dict() for figure in statuses],
        "exceptions": exceptions,
        "approvals": approvals,
        "integrations": integrations,
        "shipments": shipments,
        "extraction": extraction,
        "turnaround": turnaround_from(rows),
        "automation": automation,
        "turnaround_trend": bucket_series(rows, window, interval="day"),
        "definitions": KPI_DEFINITIONS,
    }


async def build_kpis(
    session: AsyncSession,
    scope: DashboardScope,
    period: Period,
    *,
    interval: str = "day",
    now: datetime | None = None,
) -> dict[str, Any]:
    """The trend-oriented payload behind the Analytics page.

    The same queries the Dashboard uses, over a caller-chosen window and bucketed, so the two
    screens can never disagree about what a number means.
    """
    moment = now or utcnow()
    rows = await approved_rows(session, scope, period)
    extraction = await extraction_non_override_rate(session, scope, period)
    statuses = await transaction_status_counts(session, scope, period=period)
    decisions = await approval_decision_counts(session, scope, period)

    return {
        "generated_at": moment.isoformat(),
        "period": {"start": period.start.isoformat(), "end": period.end.isoformat()},
        "interval": interval,
        "streams": scope.sorted_streams,
        "scope_note": _scope_note(scope),
        "turnaround": turnaround_from(rows),
        "automation": automation_from(rows),
        "extraction": extraction,
        "series": bucket_series(rows, period, interval=interval),
        "transactions_by_status": [figure.as_dict() for figure in statuses],
        "approval_decisions": decisions,
        "definitions": KPI_DEFINITIONS,
    }


def _scope_note(scope: DashboardScope) -> str:
    if scope.empty:
        return (
            "Your account holds no platform role, so these figures are computed over nothing at "
            "all. Every number below is a real zero."
        )
    streams = ", ".join(scope.sorted_streams)
    if scope.cross_cutting:
        return f"Computed across every desk, {streams}."
    categories = len(scope.exception_categories)
    return (
        f"Computed over {streams} and the {categories} exception "
        f"{'category' if categories == 1 else 'categories'} your roles work."
    )


def max_detail_rows() -> int:
    return max(1, settings.REPORT_MAX_DETAIL_ROWS)

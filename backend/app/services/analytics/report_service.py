"""Generating a real report from the governed tables, and never from a copy of them.

The shape of this module follows the one rule the whole step turns on: a report's figures are
queried out of `trade_transactions`, `exception_cases`, `approval_tasks`, `extracted_fields`,
`integration_jobs` and `shipments` at the moment it is generated, assembled with pandas, and
written into a document. Nothing is read from a rollup, a cached total or a previous report.

Three things are worth reading before the code.

**Every figure carries the query that reproduces it.** A section's rows and a grid's figures each
carry the target screen and the filters that reproduce them, and the Report Viewer turns those
into links. A number on a report with no route back to its rows is the thing this step exists to
replace, so the route travels with the number rather than being reconstructed by the reader.

**The AI paragraph is optional in the strongest sense.** It is requested last, after every
deterministic figure has already been computed, inside its own try. A failure marks the section
unavailable and changes nothing else about the document.

**Nothing here sends anything anywhere.** There is no recipient, no channel and no code path,
dormant or otherwise, that transmits a generated report. Every rendered document says so on its
own face, because a stored PDF that did not say so could be assumed to have been circulated.
"""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import pandas as pd
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.errors import BadRequestError, NotFoundError
from app.core.logging import get_logger
from app.core.roles import PlatformRole
from app.db.base import utcnow
from app.db.session import AsyncSessionLocal
from app.models.enums import EXCEPTION_CATEGORIES, TRANSACTION_STATUSES, BusinessStream
from app.models.governance import ExceptionCase
from app.models.identity import User
from app.models.reporting import REPORT_FORMATS, REPORT_STREAMS, REPORT_TYPES, Report
from app.models.transactions import TradeTransaction
from app.services import job_service
from app.services.analytics import kpis
from app.services.analytics.kpis import Period
from app.services.analytics.report_render import (
    PDF_CONTENT_TYPE,
    XLSX_CONTENT_TYPE,
    render_pdf,
    render_xlsx,
)
from app.services.analytics.report_templates import (
    KIND_AI_SUMMARY,
    KIND_BREAKDOWN,
    KIND_KPI_GRID,
    SOURCE_APPROVALS,
    SOURCE_EXCEPTIONS_BY_CATEGORY,
    SOURCE_EXTRACTION_BY_TYPE,
    SOURCE_HEADLINE,
    SOURCE_INTEGRATIONS,
    SOURCE_SHIPMENTS,
    SOURCE_TRANSACTION_DETAIL,
    SOURCE_TRANSACTIONS_BY_STATUS,
    SOURCE_TURNAROUND_TREND,
    ReportTemplate,
    SectionSpec,
    template_for,
)
from app.services.analytics.scope import DashboardScope, scope_for
from app.services.audit_service import ActorType, record_audit_event
from app.services.gemini_service import AIServiceError, summarize_reporting_period
from app.services.governance import thresholds
from app.services.storage import get_storage_service

logger = get_logger(__name__)

JOB_TYPE_REPORT = "reporting.report.generate"

STREAM_BOTH = "both"


class AuditEvent:
    REPORT_GENERATED = "report.generated"
    REPORT_GENERATION_FAILED = "report.generation_failed"
    REPORT_DOWNLOADED = "report.downloaded"


# Who may ask for a report to be produced. Reading one is open to every signed-in account, on the
# same transparency principle the exception queue and the approval queue already follow.
GENERATE_ROLES: frozenset[str] = frozenset(
    {PlatformRole.ADMIN.value, PlatformRole.APPROVER_HOD.value}
)


@dataclass(frozen=True)
class ReportRequest:
    report_type: str
    output_format: str
    period: Period
    stream: str = STREAM_BOTH
    status_filter: str | None = None

    def as_parameters(self) -> dict[str, Any]:
        """Exactly what was asked for, in a form the reference resolves back to."""
        return {
            "report_type": self.report_type,
            "output_format": self.output_format,
            "period_start": self.period.start.isoformat(),
            "period_end": self.period.end.isoformat(),
            "stream": self.stream,
            "status_filter": self.status_filter,
        }


def validate_request(
    *,
    report_type: str,
    output_format: str,
    period: Period,
    stream: str,
    status_filter: str | None,
) -> ReportRequest:
    if report_type not in REPORT_TYPES:
        raise BadRequestError(f"'{report_type}' is not a report type this platform produces.")
    if output_format not in REPORT_FORMATS:
        raise BadRequestError(f"'{output_format}' is not a format this platform renders.")
    if stream not in REPORT_STREAMS:
        raise BadRequestError(f"'{stream}' is not a business stream.")
    if status_filter and status_filter not in TRANSACTION_STATUSES:
        raise BadRequestError(f"'{status_filter}' is not a transaction status.")
    if period.end <= period.start:
        raise BadRequestError("The report period must end after it starts.")
    return ReportRequest(
        report_type=report_type,
        output_format=output_format,
        period=period,
        stream=stream,
        status_filter=status_filter or None,
    )


def new_generation_reference(*, now: datetime | None = None) -> str:
    """`AGF-RPT-20260828-9F1C4B72`: readable off a printed page, unique in the table.

    Random rather than sequential on purpose. A sequential reference would tell any holder of one
    report how many others exist, and the uniqueness this needs is guaranteed by the index behind
    the column rather than by a counter.
    """
    stamp = (now or utcnow()).strftime("%Y%m%d")
    return f"AGF-RPT-{stamp}-{secrets.token_hex(4).upper()}"


def system_scope() -> DashboardScope:
    """The scope a scheduled generation runs under: every stream, every category.

    A scheduled report has no requesting account behind it, so there is no role to derive a scope
    from. It is produced across the whole platform, and the file it produces is then read under
    whatever rules the reader's own account carries.
    """
    return DashboardScope(
        streams=frozenset({BusinessStream.SCRAP.value, BusinessStream.FA.value}),
        exception_categories=frozenset(EXCEPTION_CATEGORIES),
        cross_cutting=True,
        emphasis="transactions",
        roles=frozenset({PlatformRole.ADMIN.value}),
    )


# --- assembling the result sets, with pandas ------------------------------------------------------


def _frame(rows: list[dict[str, Any]], columns: list[str]) -> pd.DataFrame:
    """A frame with its columns declared, so an empty result still has a shape."""
    return pd.DataFrame(rows, columns=columns) if rows else pd.DataFrame(columns=columns)


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Frame rows as plain dictionaries, with every absent value as None rather than NaN.

    pandas represents a missing number as NaN, which is not a value JSON can hold and not a value
    a reader should see. A transaction with no invoiced amount has no amount - it does not have an
    amount of "NaN" and it certainly does not have one of zero - so the gap is carried through as
    a null and rendered as a dash.
    """
    return [
        {key: (None if pd.isna(value) else value) for key, value in record.items()}
        for record in frame.to_dict("records")
    ]


def _detail_query(scope: DashboardScope, request: ReportRequest) -> Select:
    statement = select(TradeTransaction).where(
        TradeTransaction.created_at >= request.period.start,
        TradeTransaction.created_at < request.period.end,
    )
    if request.status_filter:
        statement = statement.where(TradeTransaction.status == request.status_filter)
    if scope.empty:
        return statement.where(TradeTransaction.id.is_(None))
    return statement.where(TradeTransaction.stream.in_(scope.sorted_streams))


async def _transaction_detail(
    session: AsyncSession, scope: DashboardScope, request: ReportRequest
) -> tuple[pd.DataFrame, int]:
    """The transactions themselves, not only their counts.

    Capped at a configured number of rows so a report over a year of trading is still a document
    somebody can open. The cap is reported in the section rather than applied silently.
    """
    statement = _detail_query(scope, request)
    total = int(await session.scalar(select(func.count()).select_from(statement.subquery())) or 0)

    rows = list(
        (
            await session.scalars(
                statement.options(
                    selectinload(TradeTransaction.purchase_leg),
                    selectinload(TradeTransaction.sales_leg),
                    selectinload(TradeTransaction.fa_leg),
                )
                .order_by(TradeTransaction.created_at.desc())
                .limit(kpis.max_detail_rows())
            )
        ).all()
    )

    ids = [row.id for row in rows] or [None]
    exception_counts = dict(
        (
            await session.execute(
                select(ExceptionCase.transaction_id, func.count(ExceptionCase.id))
                .where(ExceptionCase.transaction_id.in_(ids))
                .group_by(ExceptionCase.transaction_id)
            )
        ).all()
    )

    records = [
        {
            "batch_number": row.batch_number,
            "stream": row.stream,
            # Rendered the way the screens render it. A spreadsheet somebody reads should not make
            # them translate `validation_pending` in their head.
            "status": row.status.replace("_", " ").capitalize(),
            "commodity": row.commodity_code or row.extracted_commodity_value or None,
            "quantity_mt": float(row.quantity_mt) if row.quantity_mt is not None else None,
            "counterparty": _counterparty(row),
            "value": _value(row),
            "currency": row.currency,
            "opened_at": row.created_at.strftime("%Y-%m-%d"),
            "exceptions": int(exception_counts.get(row.id, 0)),
            "transaction_id": str(row.id),
        }
        for row in rows
    ]
    frame = _frame(
        records,
        [
            "batch_number",
            "stream",
            "status",
            "commodity",
            "quantity_mt",
            "counterparty",
            "value",
            "currency",
            "opened_at",
            "exceptions",
            "transaction_id",
        ],
    )
    return frame, total


def _counterparty(row: TradeTransaction) -> str | None:
    purchase = row.purchase_leg
    if purchase is not None and purchase.supplier_name:
        return purchase.supplier_name
    if row.sales_leg is not None and row.sales_leg.customer_name:
        return row.sales_leg.customer_name
    if row.fa_leg is not None and row.fa_leg.counterparty_name:
        return row.fa_leg.counterparty_name
    return None


def _value(row: TradeTransaction) -> float | None:
    leg = row.purchase_leg
    return float(leg.amount) if leg is not None and leg.amount is not None else None


# Weights are proportions of the printed page width, not pixels. The batch number and the date
# carry more than they need because they are the two columns a reader looks something up by, and a
# truncated identifier is worse than a narrow one.
# `weight` is this column's share of the printed page width; `width` is its character width in
# the spreadsheet. The two identifying columns - the batch number and the date it opened - are
# given enough room to print in full, because a truncated identifier is not an identifier.
DETAIL_COLUMNS: list[dict[str, Any]] = [
    {"key": "batch_number", "label": "Batch", "weight": 1.62, "width": 20},
    {"key": "stream", "label": "Stream", "weight": 0.68, "width": 10},
    {"key": "status", "label": "Status", "weight": 1.60, "width": 22},
    {"key": "commodity", "label": "Grade", "weight": 0.64, "width": 14},
    {"key": "quantity_mt", "label": "Qty MT", "weight": 0.76, "width": 12},
    {"key": "counterparty", "label": "Counterparty", "weight": 1.50, "width": 34},
    {"key": "value", "label": "Value", "weight": 1.10, "width": 16},
    {"key": "currency", "label": "Ccy", "weight": 0.52, "width": 8},
    {"key": "opened_at", "label": "Opened", "weight": 1.04, "width": 14},
    {"key": "exceptions", "label": "Exc", "weight": 0.52, "width": 8},
]


async def assemble(
    session: AsyncSession,
    scope: DashboardScope,
    request: ReportRequest,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Every result set the templates can draw on, computed once from the governed tables."""
    moment = now or utcnow()
    period = request.period
    stale_hours = float(
        await thresholds.resolve(session, thresholds.GovernanceKey.SHIPMENT_STALE_HOURS)
    )

    status_figures = await kpis.transaction_status_counts(session, scope, period=period)
    exceptions = await kpis.exception_counts(session, scope, now=moment)
    approvals = await kpis.approval_queue_depth(session, scope, now=moment)
    decisions = await kpis.approval_decision_counts(session, scope, period)
    integrations = await kpis.integration_counts(session, scope)
    shipments = await kpis.shipment_summary(session, scope, stale_hours=stale_hours, now=moment)
    extraction = await kpis.extraction_non_override_rate(session, scope, period)
    approved = await kpis.approved_rows(session, scope, period)
    turnaround = kpis.turnaround_from(approved)
    automation = kpis.automation_from(approved)
    trend = kpis.bucket_series(approved, period, interval="day")
    detail, detail_total = await _transaction_detail(session, scope, request)

    opened = int(sum(figure.value for figure in status_figures))
    period_params = period.as_params()

    headline: dict[str, dict[str, Any]] = {
        "transactions_opened": _figure(
            "transactions_opened",
            "Transactions opened",
            opened,
            target="transactions",
            filters=period_params,
        ),
        "open_transactions": _figure(
            "open_transactions",
            "Transactions in flight",
            int(
                sum(
                    figure.value
                    for figure in status_figures
                    if figure.key.rsplit(".", 1)[-1] not in kpis.APPROVED_OR_LATER
                )
            ),
            target="transactions",
            note="Everything opened in the period that is not yet approved.",
        ),
        "open_exceptions": _figure(
            "open_exceptions",
            "Open exceptions",
            exceptions["total_open"],
            target="exceptions",
            filters={"status": "open"},
            note=f"{exceptions['over_72h']} open for more than 72 hours.",
        ),
        "approval_queue": _figure(
            "approval_queue",
            "Waiting on a decision",
            approvals["pending"],
            target="approvals",
            filters={"decision": "pending"},
        ),
        "approvals_decided": _figure(
            "approvals_decided",
            "Decisions made",
            int(sum(decisions.values())),
            target="approvals",
            filters={"decision": "all"},
        ),
        "integration_failed": _figure(
            "integration_failed",
            "Integration failures",
            integrations["failed"],
            target="integrations",
            filters={"status": "failed"},
        ),
        "integration_awaiting_manual": _figure(
            "integration_awaiting_manual",
            "Postings awaiting a person",
            integrations["awaiting_manual_action"],
            target="integrations",
            filters={"status": "awaiting_manual_action"},
            note="Neither a success nor a failure, and never counted as one.",
        ),
        "stale_shipments": _figure(
            "stale_shipments",
            "Shipments past their check window",
            shipments["stale_count"],
            target="shipments",
            filters={"stale_only": True},
        ),
        "automation_rate": _figure(
            "automation_rate",
            "Approved without an exception",
            automation["automation_rate"],
            unit="percent",
            target="transactions",
            note=(
                f"{automation['exception_free_count']} of {automation['approved_count']} "
                "approvals in the period had no exception case opened against them."
            ),
        ),
        "turnaround_mean": _figure(
            "turnaround_mean",
            "Mean turnaround",
            turnaround["mean_hours"],
            unit="hours",
            note="Request received to approval decided.",
        ),
        "turnaround_median": _figure(
            "turnaround_median",
            "Median turnaround",
            turnaround["median_hours"],
            unit="hours",
        ),
        "extraction_non_override": _figure(
            "extraction_non_override",
            "Fields not overridden",
            extraction["non_override_rate"],
            unit="percent",
            target="documents",
            note=extraction["disclosure"],
        ),
    }

    return {
        "computed_at": moment.isoformat(),
        "stale_hours": stale_hours,
        SOURCE_HEADLINE: headline,
        SOURCE_TRANSACTIONS_BY_STATUS: _status_rows(status_figures),
        SOURCE_EXCEPTIONS_BY_CATEGORY: _exception_rows(exceptions),
        SOURCE_APPROVALS: _approval_figures(approvals, decisions),
        SOURCE_INTEGRATIONS: _integration_rows(integrations),
        SOURCE_SHIPMENTS: _shipment_rows(shipments),
        SOURCE_EXTRACTION_BY_TYPE: _extraction_rows(extraction),
        SOURCE_TURNAROUND_TREND: _trend_rows(trend),
        SOURCE_TRANSACTION_DETAIL: {
            "columns": DETAIL_COLUMNS,
            "rows": _records(detail),
            "row_count": len(detail.index),
            "total_matching": detail_total,
            "truncated": detail_total > len(detail.index),
            "target": "transactions",
            "filters": {
                **period_params,
                "status": request.status_filter,
                "stream": None if request.stream == STREAM_BOTH else request.stream,
            },
        },
        # Kept for the AI paragraph and for the viewer's own header. Never rendered as a figure.
        "raw": {
            "turnaround": turnaround,
            "automation": automation,
            "extraction": extraction,
            "integrations": integrations,
            "exceptions": exceptions,
            "shipments": shipments,
            "approvals": approvals,
            "decisions": decisions,
        },
    }


def _figure(
    key: str,
    label: str,
    value: Any,
    *,
    unit: str = "count",
    target: str | None = None,
    filters: dict[str, Any] | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    # A figure with nothing behind it stays None rather than becoming a zero. "No approvals
    # were decided, so there is no turnaround to report" and "turnaround was zero hours" are
    # different statements, and only one of them is true.
    return kpis.Figure(
        key=key,
        label=label,
        value=value,
        unit=unit,
        target=target,
        filters=filters or {},
        note=note,
    ).as_dict()


def _status_rows(figures: list[kpis.Figure]) -> dict[str, Any]:
    frame = _frame(
        [
            {
                "status": figure.key.rsplit(".", 1)[-1],
                "label": figure.label,
                "count": figure.value,
            }
            for figure in figures
        ],
        ["status", "label", "count"],
    )
    records = _records(frame)
    for record, figure in zip(records, figures, strict=True):
        record["target"] = "transactions"
        record["filters"] = figure.filters
    return {
        "columns": [
            {"key": "label", "label": "Status", "weight": 2, "width": 26},
            {"key": "count", "label": "Transactions", "weight": 1, "width": 16},
        ],
        "rows": records,
        "total": int(frame["count"].sum()) if not frame.empty else 0,
    }


def _exception_rows(exceptions: dict[str, Any]) -> dict[str, Any]:
    records = [
        {
            "label": row["label"],
            "open_count": row["open_count"],
            "under_24h": row["ageing"]["under_24h"],
            "24_to_72h": row["ageing"]["24_to_72h"],
            "over_72h": row["ageing"]["over_72h"],
            "oldest_age_hours": row["oldest_age_hours"],
            "target": row["target"],
            "filters": row["filters"],
        }
        for row in exceptions["categories"]
    ]
    return {
        "columns": [
            {"key": "label", "label": "Category", "weight": 2.4, "width": 34},
            {"key": "open_count", "label": "Open", "weight": 0.7, "width": 10},
            {"key": "under_24h", "label": "< 24h", "weight": 0.7, "width": 10},
            {"key": "24_to_72h", "label": "24-72h", "weight": 0.7, "width": 10},
            {"key": "over_72h", "label": "> 72h", "weight": 0.7, "width": 10},
            {"key": "oldest_age_hours", "label": "Oldest (h)", "weight": 0.9, "width": 14},
        ],
        "rows": records,
        "total": exceptions["total_open"],
    }


def _approval_figures(approvals: dict[str, Any], decisions: dict[str, int]) -> dict[str, Any]:
    figures = [
        _figure(
            "pending",
            "Waiting on a decision",
            approvals["pending"],
            target="approvals",
            filters={"decision": "pending"},
        ),
        _figure(
            "approved",
            "Approved in the period",
            decisions.get("approved", 0),
            target="approvals",
            filters={"decision": "approved"},
        ),
        _figure(
            "rejected",
            "Rejected in the period",
            decisions.get("rejected", 0),
            target="approvals",
            filters={"decision": "rejected"},
        ),
        _figure(
            "changes_requested",
            "Returned for changes",
            decisions.get("changes_requested", 0),
            target="approvals",
            filters={"decision": "changes_requested"},
        ),
    ]
    if approvals["oldest_waiting_hours"] is not None:
        figures[0]["note"] = f"The oldest has waited {approvals['oldest_waiting_hours']:.0f} hours."
    return {"figures": figures}


def _integration_rows(integrations: dict[str, Any]) -> dict[str, Any]:
    records = [
        {
            "label": status.replace("_", " ").capitalize(),
            "count": count,
            "target": "integrations",
            "filters": {"status": status},
        }
        for status, count in integrations["by_status"].items()
    ]
    return {
        "columns": [
            {"key": "label", "label": "Posting state", "weight": 2, "width": 28},
            {"key": "count", "label": "Jobs", "weight": 1, "width": 12},
        ],
        "rows": records,
        "note": integrations["separation_note"],
    }


def _shipment_rows(shipments: dict[str, Any]) -> dict[str, Any]:
    records = [
        {
            "label": row["label"],
            "count": row["count"],
            "target": row["target"],
            "filters": row["filters"],
        }
        for row in shipments["by_status"]
    ]
    records.append(
        {
            "label": f"Past their {int(shipments['stale_threshold_hours'])}-hour check window",
            "count": shipments["stale_count"],
            "target": "shipments",
            "filters": {"stale_only": True},
        }
    )
    return {
        "columns": [
            {"key": "label", "label": "Cargo", "weight": 2, "width": 40},
            {"key": "count", "label": "Shipments", "weight": 1, "width": 14},
        ],
        "rows": records,
        "total": shipments["total"],
    }


def _extraction_rows(extraction: dict[str, Any]) -> dict[str, Any]:
    records = [
        {
            "document_type": (row["document_type"] or "unknown").replace("_", " ").capitalize(),
            "field_count": row["field_count"],
            "overridden_count": row["overridden_count"],
            "non_override_rate": row["non_override_rate"],
            "target": "documents",
            "filters": row["filters"],
        }
        for row in extraction["by_document_type"]
    ]
    return {
        "columns": [
            {"key": "document_type", "label": "Document type", "weight": 2, "width": 26},
            {"key": "field_count", "label": "Fields read", "weight": 1, "width": 14},
            {"key": "overridden_count", "label": "Overridden", "weight": 1, "width": 14},
            {"key": "non_override_rate", "label": "Not overridden %", "weight": 1.2, "width": 18},
        ],
        "rows": records,
        "note": extraction["disclosure"],
    }


def _trend_rows(trend: list[dict[str, Any]]) -> dict[str, Any]:
    frame = _frame(
        [
            {
                "day": row["bucket_start"][:10],
                "approved_count": row["approved_count"],
                "mean_hours": row["mean_hours"],
                "median_hours": row["median_hours"],
                "automation_rate": row["automation_rate"],
            }
            for row in trend
        ],
        ["day", "approved_count", "mean_hours", "median_hours", "automation_rate"],
    )
    return {
        "columns": [
            {"key": "day", "label": "Day", "weight": 1, "width": 14},
            {"key": "approved_count", "label": "Approved", "weight": 1, "width": 12},
            {"key": "mean_hours", "label": "Mean (h)", "weight": 1, "width": 12},
            {"key": "median_hours", "label": "Median (h)", "weight": 1, "width": 12},
            {"key": "automation_rate", "label": "Exception-free %", "weight": 1.2, "width": 18},
        ],
        # Days on which nothing was approved are dropped from the printed table and kept in the
        # chart series: a page of empty rows is noise, and a gap in a line is information.
        "rows": [row for row in _records(frame) if row["approved_count"]],
        "series": trend,
    }


# --- building the document content from the template ----------------------------------------------


def build_content(
    template: ReportTemplate,
    request: ReportRequest,
    data: dict[str, Any],
    *,
    reference: str,
    generated_by: str | None,
    generated_at: datetime,
    ai_summary: str | None = None,
    ai_summary_error: str | None = None,
) -> dict[str, Any]:
    sections = [
        _build_section(section, data, ai_summary=ai_summary, ai_summary_error=ai_summary_error)
        for section in template.sections
    ]
    return {
        "title": template.title,
        "description": template.description,
        "report_type": template.report_type,
        "template_key": template.key,
        "generation_reference": reference,
        "generated_at": generated_at.isoformat(),
        "generated_by": generated_by,
        "period": {
            "start": request.period.start.isoformat(),
            "end": request.period.end.isoformat(),
        },
        "stream": request.stream,
        "status_filter": request.status_filter,
        "sections": [section for section in sections if section is not None],
        "disclosures": list(template.disclosures),
        "definitions": kpis.KPI_DEFINITIONS,
    }


def _build_section(
    spec: SectionSpec,
    data: dict[str, Any],
    *,
    ai_summary: str | None,
    ai_summary_error: str | None,
) -> dict[str, Any] | None:
    source = data.get(spec.source)
    if source is None:
        raise KeyError(f"Report section '{spec.key}' names an unknown source '{spec.source}'.")

    section: dict[str, Any] = {
        "key": spec.key,
        "title": spec.title,
        "kind": spec.kind,
        "description": spec.description,
    }

    if spec.kind == KIND_AI_SUMMARY:
        section["text"] = ai_summary
        section["unavailable_reason"] = (
            None
            if ai_summary
            else (
                "The AI summary could not be produced for this report. Every figure below is "
                "computed by the platform and is unaffected."
            )
        )
        section["ai_generated"] = bool(ai_summary)
        section["ai_summary_error"] = ai_summary_error
        return section

    if spec.kind == KIND_KPI_GRID:
        available = source if isinstance(source, dict) else {}
        pool = available.get("figures") if "figures" in available else available
        if isinstance(pool, list):
            section["figures"] = pool
        else:
            keys = spec.figures or tuple(pool.keys())
            section["figures"] = [pool[key] for key in keys if key in pool]
        return section

    section["columns"] = source.get("columns", [])
    section["rows"] = source.get("rows", [])
    section["note"] = source.get("note")
    if spec.kind == KIND_BREAKDOWN:
        section["total"] = source.get("total")
    for extra in ("row_count", "total_matching", "truncated", "target", "filters", "series"):
        if extra in source:
            section[extra] = source[extra]
    return section


def summary_facts(request: ReportRequest, data: dict[str, Any]) -> dict[str, Any]:
    """The figures handed to the model, and the only thing it ever sees.

    Already computed, already rounded, already labelled. The model is asked to describe them; it
    has no route to a record and no field in its schema to return a number of its own.
    """
    raw = data["raw"]
    return {
        "period start": request.period.start.date().isoformat(),
        "period end": request.period.end.date().isoformat(),
        "business stream": "both streams" if request.stream == STREAM_BOTH else request.stream,
        "transactions opened in the period": data[SOURCE_TRANSACTIONS_BY_STATUS]["total"],
        "approvals decided in the period": sum(raw["decisions"].values()),
        "approvals approved": raw["decisions"].get("approved", 0),
        "approvals still waiting": raw["approvals"]["pending"],
        "percentage approved with no exception ever opened": raw["automation"]["automation_rate"],
        "mean hours from request received to approval decided": raw["turnaround"]["mean_hours"],
        "median hours from request received to approval decided": raw["turnaround"]["median_hours"],
        "extracted fields read": raw["extraction"]["field_count"],
        "percentage of extracted fields not overridden": raw["extraction"]["non_override_rate"],
        "open exception cases": raw["exceptions"]["total_open"],
        "open exception cases older than 72 hours": raw["exceptions"]["over_72h"],
        "integration postings that failed": raw["integrations"]["failed"],
        "integration postings awaiting a person": raw["integrations"]["awaiting_manual_action"],
        "shipments past their check window": raw["shipments"]["stale_count"],
    }


# --- generation -----------------------------------------------------------------------------------


async def generate(
    session: AsyncSession,
    request: ReportRequest,
    *,
    requested_by: User | None,
    scope: DashboardScope | None = None,
    now: datetime | None = None,
) -> Report:
    """Compute, render, store, audit, and write one new `Report` row. Never an update."""
    moment = now or utcnow()
    template = template_for(request.report_type)
    working_scope = scope or (scope_for(requested_by) if requested_by else system_scope())
    working_scope = working_scope.narrowed_to(
        None if request.stream == STREAM_BOTH else request.stream
    )

    data = await assemble(session, working_scope, request, now=moment)
    reference = new_generation_reference(now=moment)

    ai_summary: str | None = None
    ai_error: str | None = None
    if template.wants_ai_summary and settings.REPORT_AI_SUMMARY_ENABLED:
        ai_summary, ai_error = await _executive_summary(request, data)

    content = build_content(
        template,
        request,
        data,
        reference=reference,
        generated_by=requested_by.display_name if requested_by else None,
        generated_at=moment,
        ai_summary=ai_summary,
        ai_summary_error=ai_error,
    )

    rendered, content_type, extension = _render(content, request.output_format)
    storage_ref = f"{settings.REPORT_STORAGE_PREFIX}/{moment:%Y/%m}/{reference}.{extension}"
    await get_storage_service().upload(storage_ref, rendered, content_type)

    event = await record_audit_event(
        session,
        event_type=AuditEvent.REPORT_GENERATED,
        entity_type="report",
        entity_id=reference,
        actor_id=requested_by.id if requested_by else None,
        actor_type=ActorType.USER if requested_by else ActorType.SYSTEM,
        metadata={
            "generation_reference": reference,
            "template_key": template.key,
            **request.as_parameters(),
            "ai_summary": "generated" if ai_summary else (ai_error or "not_requested"),
            "byte_size": len(rendered),
            # Stated on the audit trail as plainly as it is stated on the document: nothing was
            # sent anywhere, because nothing can be.
            "distributed": False,
        },
    )

    report = Report(
        report_type=request.report_type,
        output_format=request.output_format,
        template_key=template.key,
        title=template.title,
        period_start=request.period.start,
        period_end=request.period.end,
        stream=request.stream,
        status_filter=request.status_filter,
        storage_ref=storage_ref,
        byte_size=len(rendered),
        generation_reference=reference,
        parameters=request.as_parameters(),
        content=content,
        generated_by_id=requested_by.id if requested_by else None,
        audit_event_id=event.id,
        ai_summary_error=ai_error,
        generated_at=moment,
    )
    session.add(report)
    await session.flush()
    return report


async def _executive_summary(
    request: ReportRequest, data: dict[str, Any]
) -> tuple[str | None, str | None]:
    """One model call, wrapped so that no outcome of it can affect anything else.

    Every deterministic figure in the report is already computed by the time this runs. A timeout,
    a quota refusal, a malformed reply or a missing credential all resolve to the same thing: no
    paragraph, a recorded reason, and a report that generates complete and correct without it.
    """
    try:
        summary = await summarize_reporting_period(summary_facts(request, data))
    except AIServiceError as exc:
        logger.info("report_summary_unavailable", extra={"reason": exc.reason})
        return None, exc.reason
    except Exception:
        logger.exception("report_summary_failed")
        return None, "unexpected_error"
    text = (summary.summary or "").strip()
    return (text or None), (None if text else "empty_response")


def _render(content: dict[str, Any], output_format: str) -> tuple[bytes, str, str]:
    if output_format == "pdf":
        return render_pdf(content), PDF_CONTENT_TYPE, "pdf"
    return render_xlsx(content), XLSX_CONTENT_TYPE, "xlsx"


# --- reading --------------------------------------------------------------------------------------


def list_query(
    *,
    report_type: str | None = None,
    output_format: str | None = None,
    stream: str | None = None,
) -> Select[tuple[Report]]:
    statement = select(Report)
    if report_type:
        statement = statement.where(Report.report_type == report_type)
    if output_format:
        statement = statement.where(Report.output_format == output_format)
    if stream:
        statement = statement.where(Report.stream == stream)
    return statement.order_by(Report.generated_at.desc())


async def get_report(session: AsyncSession, report_id: UUID) -> Report:
    report = await session.get(Report, report_id)
    if report is None:
        raise NotFoundError("Report not found.")
    return report


async def resolve_reference(session: AsyncSession, reference: str) -> Report | None:
    """What the reference printed on a page resolves to. One row, or nothing."""
    return await session.scalar(
        select(Report).where(Report.generation_reference == reference.strip().upper())
    )


async def download_url(report: Report) -> str:
    """A short-lived signed URL through the existing authenticated route. Never a stored path."""
    return await get_storage_service().get_signed_url(report.storage_ref)


def may_generate(user: User) -> bool:
    return bool(GENERATE_ROLES.intersection(user.roles or ()))


# --- the tracked background job -------------------------------------------------------------------

_BACKGROUND_TASKS: set[asyncio.Task] = set()


async def queue_generation(
    session: AsyncSession, request: ReportRequest, *, requested_by: User
) -> UUID:
    """Create the tracked job and start the work. Returns the job id the client polls.

    The same `job_service` and the same `GET /jobs/{job_id}/status` Step 1 established and every
    step since has reused. There is no second job mechanism here and no second polling endpoint.
    """
    template_for(request.report_type)
    job = await job_service.create_job(
        session, job_type=JOB_TYPE_REPORT, created_by_id=requested_by.id
    )
    await session.commit()

    task = asyncio.create_task(_run(job.id, request, requested_by.id))
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)
    return job.id


async def _run(job_id: UUID, request: ReportRequest, user_id: UUID) -> None:
    """Own session, own lifetime: the request that queued the work is long gone."""
    async with AsyncSessionLocal() as session:
        try:
            user = await session.get(User, user_id)
            if user is None:
                await job_service.fail_job(
                    session, job_id, error_message="The requesting account no longer exists."
                )
                await session.commit()
                return

            await job_service.update_job_progress(session, job_id, 25)
            await session.commit()

            report = await generate(session, request, requested_by=user)
            await job_service.complete_job(session, job_id, result_ref=f"report:{report.id}")
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("report_generation_failed", extra={"job_id": str(job_id)})
            await _record_failure(job_id, request, user_id)


async def _record_failure(job_id: UUID, request: ReportRequest, user_id: UUID) -> None:
    """Fail the job and audit it on a session of its own, so the rollback cannot swallow it."""
    async with AsyncSessionLocal() as session:
        try:
            await job_service.fail_job(
                session,
                job_id,
                error_message="The report could not be generated. Nothing was produced.",
            )
            await record_audit_event(
                session,
                event_type=AuditEvent.REPORT_GENERATION_FAILED,
                entity_type="report",
                actor_id=user_id,
                actor_type=ActorType.USER,
                metadata={"job_id": str(job_id), **request.as_parameters()},
            )
            await session.commit()
        except Exception:  # pragma: no cover - the failure path's own failure
            logger.exception("report_failure_not_recorded", extra={"job_id": str(job_id)})
            await session.rollback()

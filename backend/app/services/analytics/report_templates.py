"""Report structure as configuration, not as layout code.

This platform's governing material leaves the exact report templates and their distribution rules
to be confirmed with AGFZE, and asks that the report engine be built against configuration rather
than hard-coded layouts. That is what this module is: which sections a report carries, in what
order, and which figures go in each, declared as data that the renderer reads at generation time.

The structures below are the *shipped defaults*. They are seeded into
`report_template_configurations` by the migration that creates it, and from then on the row is
what a generation reads: `resolve()` hydrates one back into the same dataclasses the renderers
already take, so a template edited on the admin screen and a template as it shipped are the same
object by the time anything renders it. The PDF and XLSX renderers still never learn a section's
name and still have no branch anywhere that says "if this is the monthly report".

The defaults stay in code as well as in the table for one reason worth stating: they are the seed,
and they are what `resolve()` falls back to if a deployment somehow reaches a generation before
the row exists. A report that refused to generate because its structure row was missing would be a
worse failure than one generated to the structure it has always had - and the fallback is logged,
so it is never silent.

Three defaults ship, and every one of them is real:

* `daily_operations` - what happened yesterday and what is open this morning.
* `monthly_management` - the month that has just ended, with the automation and turnaround KPIs
  the HOD actually asks for, plus the AI-written paragraph.
* `adhoc_transactions` - whatever range, stream and status somebody asked the builder for.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.reporting import ReportTemplateConfiguration

logger = get_logger(__name__)

# What a section renders. The renderers switch on this and on nothing else, which is what keeps a
# new section a data change rather than a code change.
KIND_KPI_GRID = "kpi_grid"
KIND_BREAKDOWN = "breakdown"
KIND_TABLE = "table"
KIND_AI_SUMMARY = "ai_summary"
KIND_NOTE = "note"

# The named data blocks a section may draw from. Each maps to one assembled result set in
# `report_service`; a section naming a source that does not exist fails at build time rather than
# rendering an empty page.
SOURCE_HEADLINE = "headline"
SOURCE_TRANSACTIONS_BY_STATUS = "transactions_by_status"
SOURCE_EXCEPTIONS_BY_CATEGORY = "exceptions_by_category"
SOURCE_APPROVALS = "approvals"
SOURCE_INTEGRATIONS = "integrations"
SOURCE_SHIPMENTS = "shipments"
SOURCE_EXTRACTION_BY_TYPE = "extraction_by_document_type"
SOURCE_TURNAROUND_TREND = "turnaround_trend"
SOURCE_TRANSACTION_DETAIL = "transaction_detail"


@dataclass(frozen=True)
class SectionSpec:
    key: str
    title: str
    kind: str
    source: str
    description: str | None = None
    # Which figure keys from the source belong in this section, in this order. Empty means "every
    # figure the source produces", which is what a breakdown or a table normally wants.
    figures: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReportTemplate:
    key: str
    title: str
    report_type: str
    description: str
    sections: tuple[SectionSpec, ...]
    # Whether this template asks the model for its one-paragraph executive summary. Only the
    # monthly management report does, and the report generates completely without it.
    wants_ai_summary: bool = False
    default_period_days: int = 1
    include_detail_rows: bool = False
    disclosures: tuple[str, ...] = field(default_factory=tuple)


# The disclosure that travels with any report carrying the extraction figure, printed in the
# document itself rather than left to whoever reads it to remember.
NON_OVERRIDE_DISCLOSURE = (
    "Extraction figures are non-override rates: the share of extracted fields nobody corrected. "
    "They are a stated proxy for extraction quality, not a verified-correctness measurement."
)

INTEGRATION_DISCLOSURE = (
    "Failed postings and postings awaiting a person are counted separately and are never added "
    "together. A posting waiting on a person is not a failure."
)

# Printed on every generated report, in the document itself, so a page that has been forwarded by
# hand still says what it is. The wording is deliberately about *this file* rather than about the
# platform's capability: since 2 a scheduled report can be distributed, but what is
# distributed is a notification linking to the report in the platform, never the file itself. A
# document that has reached a reader some other way was put there by a person, not by the platform.
DISTRIBUTION_DISCLOSURE = (
    "This report was generated and stored in the AGFZE Command Centre. This file is never sent by "
    "the platform: where distribution is configured, recipients are notified with a link to the "
    "report in the platform and read it there."
)


DAILY_OPERATIONS = ReportTemplate(
    key="daily_operations",
    title="Daily operations summary",
    report_type="daily",
    description=(
        "What moved yesterday and what is open this morning: transactions by state, the exception "
        "queue by category and age, the approval queue, the postings still owed and the cargo "
        "nobody has established a position for."
    ),
    default_period_days=1,
    sections=(
        SectionSpec(
            key="headline",
            title="Where things stand",
            kind=KIND_KPI_GRID,
            source=SOURCE_HEADLINE,
            figures=(
                "open_transactions",
                "open_exceptions",
                "approval_queue",
                "integration_failed",
                "integration_awaiting_manual",
                "stale_shipments",
            ),
        ),
        SectionSpec(
            key="transactions",
            title="Transactions by status",
            kind=KIND_BREAKDOWN,
            source=SOURCE_TRANSACTIONS_BY_STATUS,
            description="Every transaction opened in the period, grouped by where it now stands.",
        ),
        SectionSpec(
            key="exceptions",
            title="Open exceptions by category and age",
            kind=KIND_BREAKDOWN,
            source=SOURCE_EXCEPTIONS_BY_CATEGORY,
            description=(
                "Unresolved cases only. Every age is computed from the case's own opened_at "
                "against the moment this report was generated."
            ),
        ),
        SectionSpec(
            key="approvals",
            title="Approval queue",
            kind=KIND_KPI_GRID,
            source=SOURCE_APPROVALS,
        ),
        SectionSpec(
            key="integrations",
            title="Downstream postings",
            kind=KIND_BREAKDOWN,
            source=SOURCE_INTEGRATIONS,
            description=INTEGRATION_DISCLOSURE,
        ),
        SectionSpec(
            key="shipments",
            title="Cargo",
            kind=KIND_BREAKDOWN,
            source=SOURCE_SHIPMENTS,
        ),
    ),
    disclosures=(INTEGRATION_DISCLOSURE, DISTRIBUTION_DISCLOSURE),
)


MONTHLY_MANAGEMENT = ReportTemplate(
    key="monthly_management",
    title="Monthly management report",
    report_type="monthly",
    description=(
        "The month that has just ended: throughput, how much of it ran without a formal "
        "intervention, how long a deal took from the email arriving to the decision being made, "
        "and where the extraction needed correcting."
    ),
    default_period_days=30,
    wants_ai_summary=True,
    include_detail_rows=True,
    sections=(
        SectionSpec(
            key="executive_summary",
            title="Executive summary",
            kind=KIND_AI_SUMMARY,
            source=SOURCE_HEADLINE,
            description=(
                "Written by the AI assistant from the figures in this report. Every figure below "
                "it is computed by the platform and is not the model's work."
            ),
        ),
        SectionSpec(
            key="headline",
            title="The month in figures",
            kind=KIND_KPI_GRID,
            source=SOURCE_HEADLINE,
            figures=(
                "transactions_opened",
                "approvals_decided",
                "automation_rate",
                "turnaround_mean",
                "turnaround_median",
                "extraction_non_override",
            ),
        ),
        SectionSpec(
            key="transactions",
            title="Transactions by status",
            kind=KIND_BREAKDOWN,
            source=SOURCE_TRANSACTIONS_BY_STATUS,
        ),
        SectionSpec(
            key="exceptions",
            title="Exceptions by category",
            kind=KIND_BREAKDOWN,
            source=SOURCE_EXCEPTIONS_BY_CATEGORY,
        ),
        SectionSpec(
            key="extraction",
            title="Extraction non-override rate by document type",
            kind=KIND_BREAKDOWN,
            source=SOURCE_EXTRACTION_BY_TYPE,
            description=NON_OVERRIDE_DISCLOSURE,
        ),
        SectionSpec(
            key="turnaround",
            title="Turnaround and automation by day",
            kind=KIND_TABLE,
            source=SOURCE_TURNAROUND_TREND,
        ),
        SectionSpec(
            key="integrations",
            title="Downstream postings",
            kind=KIND_BREAKDOWN,
            source=SOURCE_INTEGRATIONS,
            description=INTEGRATION_DISCLOSURE,
        ),
        SectionSpec(
            key="detail",
            title="Transactions in the period",
            kind=KIND_TABLE,
            source=SOURCE_TRANSACTION_DETAIL,
        ),
    ),
    disclosures=(NON_OVERRIDE_DISCLOSURE, INTEGRATION_DISCLOSURE, DISTRIBUTION_DISCLOSURE),
)


ADHOC_TRANSACTIONS = ReportTemplate(
    key="adhoc_transactions",
    title="Transaction report",
    report_type="adhoc",
    description=(
        "The date range, business stream and status somebody asked for, with the transactions "
        "themselves listed under the summary rather than only counted."
    ),
    default_period_days=30,
    include_detail_rows=True,
    sections=(
        SectionSpec(
            key="headline",
            title="Summary",
            kind=KIND_KPI_GRID,
            source=SOURCE_HEADLINE,
            figures=(
                "transactions_opened",
                "approvals_decided",
                "automation_rate",
                "turnaround_mean",
                "open_exceptions",
                "extraction_non_override",
            ),
        ),
        SectionSpec(
            key="transactions",
            title="Transactions by status",
            kind=KIND_BREAKDOWN,
            source=SOURCE_TRANSACTIONS_BY_STATUS,
        ),
        SectionSpec(
            key="exceptions",
            title="Open exceptions by category",
            kind=KIND_BREAKDOWN,
            source=SOURCE_EXCEPTIONS_BY_CATEGORY,
        ),
        SectionSpec(
            key="integrations",
            title="Downstream postings",
            kind=KIND_BREAKDOWN,
            source=SOURCE_INTEGRATIONS,
            description=INTEGRATION_DISCLOSURE,
        ),
        SectionSpec(
            key="detail",
            title="Transactions in the period",
            kind=KIND_TABLE,
            source=SOURCE_TRANSACTION_DETAIL,
        ),
    ),
    disclosures=(INTEGRATION_DISCLOSURE, DISTRIBUTION_DISCLOSURE),
)


TEMPLATES: tuple[ReportTemplate, ...] = (
    DAILY_OPERATIONS,
    MONTHLY_MANAGEMENT,
    ADHOC_TRANSACTIONS,
)

TEMPLATES_BY_KEY: dict[str, ReportTemplate] = {row.key: row for row in TEMPLATES}
TEMPLATE_BY_REPORT_TYPE: dict[str, ReportTemplate] = {row.report_type: row for row in TEMPLATES}


def template_for(report_type: str) -> ReportTemplate:
    template = TEMPLATE_BY_REPORT_TYPE.get(report_type)
    if template is None:
        raise KeyError(f"No report template is configured for '{report_type}'.")
    return template


# --- the configured structure, read at generation time -------------------------------------------

# Every section kind and every named source a stored template may reference. Validated on write by
# the admin schema and again here on read, because a row naming something the service does not
# produce would fail the build rather than render an empty page - correct, but far too late.
SECTION_KINDS: tuple[str, ...] = (
    KIND_KPI_GRID,
    KIND_BREAKDOWN,
    KIND_TABLE,
    KIND_AI_SUMMARY,
    KIND_NOTE,
)

SECTION_SOURCES: tuple[str, ...] = (
    SOURCE_HEADLINE,
    SOURCE_TRANSACTIONS_BY_STATUS,
    SOURCE_EXCEPTIONS_BY_CATEGORY,
    SOURCE_APPROVALS,
    SOURCE_INTEGRATIONS,
    SOURCE_SHIPMENTS,
    SOURCE_EXTRACTION_BY_TYPE,
    SOURCE_TURNAROUND_TREND,
    SOURCE_TRANSACTION_DETAIL,
)

# The figures the headline block produces, which is the one source a section may narrow to a
# chosen subset. Read by the admin screen so an editor picks from what exists rather than typing a
# key that would be silently dropped at render time.
HEADLINE_FIGURE_KEYS: tuple[str, ...] = (
    "transactions_opened",
    "open_transactions",
    "open_exceptions",
    "approval_queue",
    "approvals_decided",
    "integration_failed",
    "integration_awaiting_manual",
    "stale_shipments",
    "automation_rate",
    "turnaround_mean",
    "turnaround_median",
    "extraction_non_override",
)


def section_from_row(payload: dict[str, Any]) -> SectionSpec:
    """One stored section back into the spec the renderers already take."""
    figures = payload.get("figures") or []
    return SectionSpec(
        key=str(payload["key"]),
        title=str(payload["title"]),
        kind=str(payload["kind"]),
        source=str(payload["source"]),
        description=(str(payload["description"]) if payload.get("description") else None),
        figures=tuple(str(value) for value in figures),
    )


def template_from_row(row: ReportTemplateConfiguration) -> ReportTemplate:
    return ReportTemplate(
        key=row.template_key,
        title=row.title,
        report_type=row.report_type,
        description=row.description,
        sections=tuple(section_from_row(section) for section in (row.sections or [])),
        wants_ai_summary=bool(row.wants_ai_summary),
        default_period_days=int(row.default_period_days),
        include_detail_rows=bool(row.include_detail_rows),
        disclosures=tuple(str(value) for value in (row.disclosures or [])),
    )


def section_as_row(section: SectionSpec) -> dict[str, Any]:
    """The inverse, for seeding and for the admin screen's read model."""
    return {
        "key": section.key,
        "title": section.title,
        "kind": section.kind,
        "source": section.source,
        "description": section.description,
        "figures": list(section.figures),
    }


async def resolve(session: AsyncSession, report_type: str) -> ReportTemplate:
    """The structure this report type is configured to carry, right now.

    Falls back to the shipped default only where no row exists at all, and says so in the log. A
    deployment whose migrations have run never takes that path.
    """
    row = await session.scalar(
        select(ReportTemplateConfiguration).where(
            ReportTemplateConfiguration.report_type == report_type
        )
    )
    if row is None:
        # `template_for` raises for a report type that is not a report type at all, which is the
        # right failure and is not what this branch is about.
        shipped = template_for(report_type)
        logger.warning(
            "report_template_row_missing",
            extra={"report_type": report_type, "template_key": shipped.key},
        )
        return shipped
    return template_from_row(row)

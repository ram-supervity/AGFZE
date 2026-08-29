"""Report structure as configuration, not as layout code.

This platform's governing material leaves the exact report templates and their distribution rules
to be confirmed with AGFZE, and asks that the report engine be built against configuration rather
than hard-coded layouts. That is what this module is: which sections a report carries, in what
order, and which figures go in each, declared as data that the renderer reads at generation time.

There is no admin screen to edit any of this yet - that arrives with the rest of the configuration
screens - so for now a template change is a change to the defaults below, in exactly the same
discipline `RuleConfiguration` and `DocumentTypeSchema` already follow. What matters is that when
that screen does arrive, it edits these structures; the PDF and XLSX renderers never learn a
section's name and have no branch anywhere that says "if this is the monthly report".

Three defaults ship, and every one of them is real:

* `daily_operations` - what happened yesterday and what is open this morning.
* `monthly_management` - the month that has just ended, with the automation and turnaround KPIs
  the HOD actually asks for, plus the AI-written paragraph.
* `adhoc_transactions` - whatever range, stream and status somebody asked the builder for.
"""

from __future__ import annotations

from dataclasses import dataclass, field

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
# platform's capability: since Step 12 a scheduled report can be distributed, but what is
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

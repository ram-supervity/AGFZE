"""Response shapes for the dashboard, the analytics page and the report screens.

The aggregate payloads are declared loosely on purpose. Which figures a dashboard carries is
decided by the KPI definitions and, for a report, by the template configuration; pinning every
one of them into a pydantic field here would mean a template change - which is meant to be a
configuration change - could not be made without editing a schema. What is pinned is the envelope
around them, and the metadata a reader needs to trust a figure: when it was computed, over what
period, under whose scope, and how to get back to the rows behind it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.intake import Page


class FigureRead(BaseModel):
    """One number, and the query that reproduces it."""

    key: str
    label: str
    value: float | int | None
    unit: str = "count"
    # Which screen the drill-through opens, and with what filters. Null target means the figure
    # is descriptive rather than navigable - a mean duration, for instance.
    target: str | None = None
    filters: dict[str, Any] = Field(default_factory=dict)
    note: str | None = None


class DashboardSummary(BaseModel):
    generated_at: datetime
    period: dict[str, str]
    # Which panel this account's dashboard leads with. Ordering only: nothing is hidden by it, and
    # what each panel may contain was decided by the query that filled it.
    emphasis: str
    streams: list[str]
    scope_note: str
    tiles: list[FigureRead]
    transactions_by_status: list[FigureRead]
    exceptions: dict[str, Any]
    approvals: dict[str, Any]
    integrations: dict[str, Any]
    shipments: dict[str, Any]
    extraction: dict[str, Any]
    turnaround: dict[str, Any]
    automation: dict[str, Any]
    turnaround_trend: list[dict[str, Any]]
    definitions: dict[str, str]
    # How old the served figures are. Zero on a freshly computed response, up to the configured
    # TTL on a cached one - stated rather than hidden, so a reader can tell.
    cache_age_seconds: float = 0.0
    cache_ttl_seconds: int = 0


class KpiTrends(BaseModel):
    generated_at: datetime
    period: dict[str, str]
    interval: str
    streams: list[str]
    scope_note: str
    turnaround: dict[str, Any]
    automation: dict[str, Any]
    extraction: dict[str, Any]
    series: list[dict[str, Any]]
    transactions_by_status: list[FigureRead]
    approval_decisions: dict[str, int]
    definitions: dict[str, str]
    cache_age_seconds: float = 0.0
    cache_ttl_seconds: int = 0


class ReportListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    report_type: str
    output_format: str
    template_key: str
    title: str
    period_start: datetime
    period_end: datetime
    stream: str
    status_filter: str | None
    generation_reference: str
    byte_size: int | None
    generated_at: datetime
    generated_by_name: str | None = None
    # True where nobody asked for it: the scheduler produced it. Rendered as such rather than
    # attributed to an invented service account.
    scheduled: bool = False
    ai_summary_error: str | None = None


class ReportList(BaseModel):
    items: list[ReportListItem]
    page: Page
    # Whether the calling account may ask for a new one. The API enforces it regardless; this is
    # so the builder link is not offered to somebody who would be refused at it.
    can_generate: bool = False


class ReportDetail(ReportListItem):
    parameters: dict[str, Any]
    content: dict[str, Any]
    # Short-lived and signed, minted per request through the existing authenticated file route.
    # There is no permanent path to a stored report.
    download_url: str | None = None
    audit_event_id: UUID | None = None
    distribution_note: str = (
        "This report was generated and stored in the platform. It has not been sent to any "
        "recipient or channel - outbound distribution does not exist on this platform yet."
    )


class ReportCreate(BaseModel):
    report_type: str = "adhoc"
    output_format: str = "pdf"
    date_from: datetime
    date_to: datetime
    stream: str = "both"
    status: str | None = None


class ReportGenerationAccepted(BaseModel):
    job_id: UUID
    # Polled through `GET /jobs/{job_id}/status`, the same endpoint every other background job in
    # this platform is polled through.
    poll_url: str
    message: str

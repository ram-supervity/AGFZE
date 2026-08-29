"""Wire models for the integration monitor and the two actions on it.

`completed_manually` is on the list item, not tucked away in a detail view, because the monitor
and the transaction workspaces both have to be able to say - at a glance, on the row - that this
posting was made by a person rather than by the platform.

Nothing here can carry a credential. The prepared payload is business data assembled from the
transaction, and no adapter puts an endpoint, a key or an authorization header into it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.config import settings
from app.models.integration import IntegrationJob
from app.models.transactions import TradeTransaction
from app.schemas.intake import Page


class IntegrationJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    transaction_id: UUID
    target_system: str
    target_label: str | None = None
    status: str
    external_reference: str | None = None
    failure_reason: str | None = None
    attempt_count: int
    max_attempts: int = 0
    # Always sent, always true or false, never omitted. A screen that cannot tell an automated
    # posting from a confirmed manual one is the thing this field exists to prevent.
    completed_manually: bool = False
    completed_manually_by_name: str | None = None
    completed_manually_at: datetime | None = None
    manual_note: str | None = None
    manual_instruction: str | None = None
    last_attempted_at: datetime | None = None
    # When the sweep will next attempt this job, computed from the last attempt and the backoff.
    # Null for anything that is not waiting on the clock - including every job awaiting a person,
    # which is never retried at all.
    next_attempt_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class IntegrationJobDetail(IntegrationJobRead):
    batch_number: str | None = None
    counterparty: str | None = None
    transaction_status: str | None = None
    # What a person needs in front of them to finish the posting themselves.
    prepared_payload: dict[str, Any] | None = None
    # Whether this deployment can post to this target automatically at all. Stated on the row so
    # "awaiting manual action" never looks like a fault.
    target_configured: bool = False


class IntegrationJobQueue(BaseModel):
    items: list[IntegrationJobDetail]
    page: Page
    # Per-target and per-status counts across everything, so the tabs can show where the work is.
    counts_by_target: dict[str, int] = Field(default_factory=dict)
    counts_by_status: dict[str, int] = Field(default_factory=dict)
    configured_targets: dict[str, bool] = Field(default_factory=dict)
    max_attempts: int = 0


class ManualCompletionRequest(BaseModel):
    """Both fields are required, and neither has a default.

    A manual completion is the one place a `succeeded` job appears without an adapter having
    succeeded. It is allowed only with a reference to point at and a reason on the record.
    """

    external_reference: str = Field(min_length=1, max_length=255)
    note: str = Field(min_length=10, max_length=2000)

    @field_validator("external_reference", "note")
    @classmethod
    def _meaningful(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("This is the only record of a posting the platform did not make.")
        return cleaned


def job_read(job: IntegrationJob) -> IntegrationJobRead:
    """One job as every screen sees it, with the computed fields filled in.

    Lives here rather than in either router, because the integration monitor and the three
    transaction workspaces have to read a job identically - including, always, whether its
    success was a person's doing rather than a call's.
    """
    from app.services.integration import integration_service

    read = IntegrationJobRead.model_validate(job)
    read.target_label = integration_service.TARGET_LABELS.get(job.target_system)
    read.max_attempts = settings.INTEGRATION_MAX_ATTEMPTS
    read.next_attempt_at = integration_service.next_attempt_at(job)
    read.completed_manually_by_name = (
        job.completed_manually_by.display_name if job.completed_manually_by else None
    )
    return read


def job_detail(job: IntegrationJob, transaction: TradeTransaction | None) -> IntegrationJobDetail:
    from app.services.integration import integration_service

    detail = IntegrationJobDetail(**job_read(job).model_dump())
    detail.prepared_payload = job.prepared_payload
    detail.target_configured = integration_service.adapter_for(job.target_system).configured
    if transaction is not None:
        detail.batch_number = transaction.batch_number
        detail.transaction_status = transaction.status
        purchase = transaction.purchase_leg
        sales = transaction.sales_leg
        fa = getattr(transaction, "fa_leg", None)
        detail.counterparty = (
            (purchase.supplier_name if purchase else None)
            or (sales.customer_name if sales else None)
            or (fa.counterparty_name if fa else None)
        )
    return detail

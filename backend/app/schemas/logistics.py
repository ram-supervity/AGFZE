"""Wire models for the shipment dashboard, the shipment detail screen and the actions on them.

One shape for a shipment, not two. Nothing on these models says whether a carrier or a person
established the values, because the screen does not branch on it and must not learn to: the only
place that distinction lives is `last_checked_source` and the audit trail behind it.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import (
    BILL_OF_LADING_TYPES,
    SHIPMENT_ISSUE_TYPES,
    SHIPMENT_MILESTONES,
    SHIPMENT_STATUSES,
)
from app.schemas.intake import Page


class ContainerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    container_number: str
    seal_number: str | None
    quantity_mt: Decimal | None
    created_at: datetime


class BillOfLadingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    bl_type: str
    bl_number: str | None
    # The field BR-07's submission check now actually reads.
    is_original_received: bool
    document_id: UUID | None
    received_at: datetime | None
    created_at: datetime


class ShipmentIssueRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    issue_type: str
    description: str
    document_id: UUID | None
    logged_by_name: str | None = None
    logged_at: datetime
    resolved_at: datetime | None


class ShipmentListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    transaction_id: UUID
    batch_number: str | None = None
    container_number: str | None = None
    bl_number: str | None
    carrier: str | None
    vessel: str | None
    port_of_loading: str | None
    port_of_discharge: str | None
    etd: date | None
    eta: date | None
    current_milestone: str | None
    status: str
    last_checked_at: datetime | None
    # Provenance, shown as a quiet caption rather than as a mode. `manual` here changes nothing
    # about how the row is rendered.
    last_checked_source: str | None
    # Computed on every read from `last_checked_at`, never stored - the same discipline the
    # exception queue's ageing follows, and for the same reason.
    hours_since_check: float = 0.0
    # True once that figure passes the configured threshold. The dashboard's indicator is always
    # visible and is deliberately simpler than, and separate from, the formal exception it may
    # eventually trigger.
    is_stale: bool = False
    stale_threshold_hours: int = 48
    consecutive_failures: int = 0
    last_error: str | None = None
    review_flagged: bool = False
    review_reason: str | None = None
    counterparty: str | None = None


class ShipmentList(BaseModel):
    items: list[ShipmentListItem]
    page: Page
    # The values actually present on the board, so the filters offer real choices.
    carriers: list[str] = Field(default_factory=list)
    ports_of_discharge: list[str] = Field(default_factory=list)
    stale_threshold_hours: int = 48
    # Whether any carrier adapter is registered at all. The dashboard says so plainly rather than
    # letting a user wonder why refresh never changes anything.
    carrier_adapters_available: int = 0
    can_manage: bool = False


class ShipmentTimelineEntry(BaseModel):
    """One line of the milestone timeline, derived from `audit_events` and stored nowhere."""

    occurred_at: datetime
    event_type: str
    summary: str
    milestone: str | None = None
    status: str | None = None
    source: str | None = None
    actor_name: str | None = None
    detail: str | None = None


class LinkedTransactionRead(BaseModel):
    """Enough of the transaction for the detail screen's card, and a link to the rest."""

    id: UUID
    batch_number: str
    stream: str
    status: str
    counterparty: str | None = None
    contract_number: str | None = None
    commodity_name: str | None = None
    quantity_mt: Decimal | None = None
    currency: str = "USD"
    has_purchase_leg: bool = False
    has_sales_leg: bool = False
    has_fa_leg: bool = False


class ShipmentDetail(ShipmentListItem):
    container: ContainerRead | None = None
    containers: list[ContainerRead] = Field(default_factory=list)
    bills_of_lading: list[BillOfLadingRead] = Field(default_factory=list)
    issues: list[ShipmentIssueRead] = Field(default_factory=list)
    timeline: list[ShipmentTimelineEntry] = Field(default_factory=list)
    transaction: LinkedTransactionRead | None = None
    milestones: list[str] = Field(default_factory=lambda: list(SHIPMENT_MILESTONES))
    statuses: list[str] = Field(default_factory=lambda: list(SHIPMENT_STATUSES))
    bill_of_lading_types: list[str] = Field(default_factory=lambda: list(BILL_OF_LADING_TYPES))
    issue_types: list[str] = Field(default_factory=lambda: list(SHIPMENT_ISSUE_TYPES))
    can_manage: bool = False
    carrier_adapters_available: int = 0
    created_at: datetime


class ShipmentManualUpdate(BaseModel):
    """The manual path, which is the primary path for almost every shipment on this platform.

    Every field is optional and an omitted field is left alone, so a person recording the one
    thing they just learned from a carrier's phone call does not have to restate everything else
    on the shipment.
    """

    status: str | None = None
    milestone: str | None = None
    eta: date | None = None
    etd: date | None = None
    carrier: str | None = Field(default=None, max_length=128)
    vessel: str | None = Field(default=None, max_length=128)
    port_of_loading: str | None = Field(default=None, max_length=128)
    port_of_discharge: str | None = Field(default=None, max_length=128)
    bl_number: str | None = Field(default=None, max_length=64)
    # Recording the bill of lading, which is what BR-07's submission check reads. Optional, and
    # only acted on when `bl_type` is supplied, so an ordinary status correction cannot silently
    # assert that the original has arrived.
    bl_type: str | None = None
    original_bl_received: bool | None = None
    bl_document_id: UUID | None = None
    note: str | None = Field(default=None, max_length=1000)

    @field_validator("status")
    @classmethod
    def _known_status(cls, value: str | None) -> str | None:
        if value is not None and value not in SHIPMENT_STATUSES:
            raise ValueError(f"Status must be one of: {', '.join(SHIPMENT_STATUSES)}")
        return value

    @field_validator("milestone")
    @classmethod
    def _known_milestone(cls, value: str | None) -> str | None:
        if value is not None and value not in SHIPMENT_MILESTONES:
            raise ValueError(f"Milestone must be one of: {', '.join(SHIPMENT_MILESTONES)}")
        return value

    @field_validator("bl_type")
    @classmethod
    def _known_bl_type(cls, value: str | None) -> str | None:
        if value is not None and value not in BILL_OF_LADING_TYPES:
            raise ValueError(
                f"Bill of lading type must be one of: {', '.join(BILL_OF_LADING_TYPES)}"
            )
        return value


class ShipmentRefreshResult(BaseModel):
    """What the refresh actually did, stated without pretending anything happened that did not."""

    shipment: ShipmentDetail
    # False when no adapter handles this shipment, which is the ordinary case. The screen reads it
    # to open the manual fields rather than to show a failure.
    attempted: bool
    updated: bool
    adapter: str | None = None
    message: str
    plausibility_flagged: bool = False


class ShipmentIssueCreate(BaseModel):
    issue_type: str
    description: str = Field(min_length=10, max_length=4000)
    document_id: UUID | None = None

    @field_validator("issue_type")
    @classmethod
    def _known_issue_type(cls, value: str) -> str:
        if value not in SHIPMENT_ISSUE_TYPES:
            raise ValueError(f"Issue type must be one of: {', '.join(SHIPMENT_ISSUE_TYPES)}")
        return value


class ShipmentCreate(BaseModel):
    """Opening a shipment by hand, for cargo whose paperwork has not reached the platform yet."""

    transaction_id: UUID
    container_number: str | None = Field(default=None, max_length=32)
    bl_number: str | None = Field(default=None, max_length=64)
    carrier: str | None = Field(default=None, max_length=128)
    vessel: str | None = Field(default=None, max_length=128)
    port_of_loading: str | None = Field(default=None, max_length=128)
    port_of_discharge: str | None = Field(default=None, max_length=128)
    etd: date | None = None
    eta: date | None = None


class LinkedShipmentRead(BaseModel):
    """A shipment as a transaction workspace shows it: enough to act on, and a link to the rest."""

    id: UUID
    container_number: str | None = None
    bl_number: str | None = None
    carrier: str | None = None
    vessel: str | None = None
    port_of_loading: str | None = None
    port_of_discharge: str | None = None
    etd: date | None = None
    eta: date | None = None
    current_milestone: str | None = None
    status: str
    last_checked_at: datetime | None = None
    last_checked_source: str | None = None
    hours_since_check: float = 0.0
    is_stale: bool = False
    review_flagged: bool = False
    original_bl_received: bool = False


def timeline_payload(entries: list[Any]) -> list[ShipmentTimelineEntry]:
    return [
        ShipmentTimelineEntry(
            occurred_at=entry.occurred_at,
            event_type=entry.event_type,
            summary=entry.summary,
            milestone=entry.milestone,
            status=entry.status,
            source=entry.source,
            actor_name=entry.actor_name,
            detail=entry.detail,
        )
        for entry in entries
    ]

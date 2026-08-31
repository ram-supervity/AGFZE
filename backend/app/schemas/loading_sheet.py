"""Wire models for the Loading Sheet: one row per batch, and the list the screen filters."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.intake import Page


class LoadingSheetRowRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    batch_number: str
    batch_source: str | None = None
    transaction_id: UUID
    supplier_name: str | None = None
    commodity_code: str | None = None
    commodity_name: str | None = None
    quantity_mt: Decimal | None = None
    currency: str
    rate: Decimal | None = None
    amount: Decimal | None = None
    port_of_loading: str | None = None
    supplier_invoice_number: str | None = None
    contract_number: str | None = None
    sync_status: str
    external_reference: str | None = None
    sync_attempts: int = 0
    sync_error: str | None = None
    synced_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    # Whole days since the row was written, computed server-side so every screen ages a row the
    # same way rather than each doing its own arithmetic against its own clock.
    age_days: int = 0
    # The complete tracker payload as it would be posted. Returned so a desk can see exactly what
    # goes to the workbook without opening the integration monitor.
    tracker_payload: dict[str, Any] = Field(default_factory=dict)


class LoadingSheetList(BaseModel):
    items: list[LoadingSheetRowRead]
    page: Page
    # Whether this deployment can actually write to a workbook. False means every row is held
    # here and will be drained the moment a connection is configured; the screen says so rather
    # than presenting `pending` as a failure.
    workbook_configured: bool = False

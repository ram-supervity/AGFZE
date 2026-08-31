"""The Loading Sheet table, and PR-01's two routing rows

Revision ID: 20260801_000027
Revises: 20260701_000026
Create Date: 2026-08-01 00:00:27.000000+00:00

One table and two rows.

`loading_sheet_rows` mirrors `payloads.tracker_fields()` column for column, and holds the
complete payload beside those columns so the sheet and the workbook can never come to describe
the same batch differently. It exists for the deployment that has no SharePoint/Excel workbook
configured - which is every deployment until AGFZE names one - and is drained into the real
workbook by the existing integration worker the moment a connection appears. Nothing about it
replaces the Graph Excel path; it is what waits for it.

The two mapping rows are the whole of what routing PR-01's failures required. No branch in the
exception hook, and none in the rule orchestrator: the fifth rule in a row to be added by data.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, timezone

import sqlalchemy as sa

from alembic import op
from app.models.enums import (
    BATCH_NUMBER_SOURCES,
    LOADING_SHEET_SYNC_STATUSES,
    LoadingSheetSyncStatus,
    sql_in_list,
)
from app.services.governance.categories import purchase_bundle_rule_exception_mappings

revision: str = "20260801_000027"
down_revision: str | None = "20260701_000026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GUID = sa.Uuid(as_uuid=True)
JSONB = sa.JSON().with_variant(
    sa.dialects.postgresql.JSONB(astext_type=sa.Text()), "postgresql"
)

MAPPING_COLUMNS = (
    sa.column("id", GUID),
    sa.column("rule_id", sa.String),
    sa.column("check_key", sa.String),
    sa.column("exception_type", sa.String),
    sa.column("owner_role", sa.String),
    sa.column("priority", sa.String),
    sa.column("description", sa.Text),
    sa.column("is_active", sa.Boolean),
    sa.column("created_at", sa.DateTime(timezone=True)),
)


def upgrade() -> None:
    op.create_table(
        "loading_sheet_rows",
        sa.Column("id", GUID, primary_key=True, default=uuid.uuid4),
        sa.Column("batch_number", sa.String(length=32), nullable=False),
        sa.Column("batch_source", sa.String(length=16), nullable=True),
        sa.Column("transaction_id", GUID, nullable=False),
        sa.Column("supplier_name", sa.String(length=255), nullable=True),
        sa.Column("commodity_code", sa.String(length=32), nullable=True),
        sa.Column("commodity_name", sa.String(length=128), nullable=True),
        sa.Column("quantity_mt", sa.Numeric(14, 3), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="USD"),
        sa.Column("rate", sa.Numeric(18, 4), nullable=True),
        sa.Column("amount", sa.Numeric(18, 4), nullable=True),
        sa.Column("port_of_loading", sa.String(length=128), nullable=True),
        sa.Column("supplier_invoice_number", sa.String(length=64), nullable=True),
        sa.Column("contract_number", sa.String(length=64), nullable=True),
        sa.Column("tracker_payload", JSONB, nullable=True),
        sa.Column(
            "sync_status",
            sa.String(length=16),
            nullable=False,
            server_default=LoadingSheetSyncStatus.PENDING.value,
        ),
        sa.Column("external_reference", sa.String(length=255), nullable=True),
        sa.Column("sync_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sync_error", sa.Text(), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["trade_transactions.id"],
            name="fk_loading_sheet_rows_transaction_id_trade_transactions",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            f"sync_status IN ({sql_in_list(LOADING_SHEET_SYNC_STATUSES)})",
            name="loading_sheet_row_sync_status_valid",
        ),
        sa.CheckConstraint(
            f"batch_source IS NULL OR batch_source IN ({sql_in_list(BATCH_NUMBER_SOURCES)})",
            name="loading_sheet_row_batch_source_valid",
        ),
        sa.CheckConstraint("sync_attempts >= 0", name="loading_sheet_row_sync_attempts_valid"),
        sa.UniqueConstraint("batch_number", name="uq_loading_sheet_rows_batch_number"),
    )
    op.create_index("ix_loading_sheet_rows_batch_number", "loading_sheet_rows", ["batch_number"])
    op.create_index("ix_loading_sheet_rows_batch_source", "loading_sheet_rows", ["batch_source"])
    op.create_index(
        "ix_loading_sheet_rows_transaction_id", "loading_sheet_rows", ["transaction_id"]
    )
    op.create_index("ix_loading_sheet_rows_supplier_name", "loading_sheet_rows", ["supplier_name"])
    op.create_index(
        "ix_loading_sheet_rows_commodity_code", "loading_sheet_rows", ["commodity_code"]
    )
    op.create_index(
        "ix_loading_sheet_rows_supplier_invoice_number",
        "loading_sheet_rows",
        ["supplier_invoice_number"],
    )
    op.create_index(
        "ix_loading_sheet_rows_contract_number", "loading_sheet_rows", ["contract_number"]
    )
    op.create_index("ix_loading_sheet_rows_sync_status", "loading_sheet_rows", ["sync_status"])
    op.create_index("ix_loading_sheet_rows_created_at", "loading_sheet_rows", ["created_at"])
    op.create_index(
        "ix_loading_sheet_rows_sync_status_updated_at",
        "loading_sheet_rows",
        ["sync_status", "updated_at"],
    )

    now = datetime.now(timezone.utc)
    op.bulk_insert(
        sa.table("rule_exception_mappings", *MAPPING_COLUMNS),
        [
            {"id": uuid.uuid4(), **row, "created_at": now}
            for row in purchase_bundle_rule_exception_mappings()
        ],
    )


def downgrade() -> None:
    mappings = sa.table(
        "rule_exception_mappings",
        sa.column("rule_id", sa.String),
        sa.column("check_key", sa.String),
    )
    for row in purchase_bundle_rule_exception_mappings():
        op.execute(
            mappings.delete().where(
                mappings.c.rule_id == row["rule_id"],
                mappings.c.check_key == row["check_key"],
            )
        )
    op.drop_table("loading_sheet_rows")

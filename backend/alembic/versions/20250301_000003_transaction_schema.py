"""trade transactions, the rule engine and the two deferred foreign keys

Revision ID: 20250301_000003
Revises: 20250201_000002
Create Date: 2025-03-01 00:00:03.000000+00:00

Layered on the  and  schemas. Two columns that have carried a transaction identifier
without a constraint since the s that introduced them - `background_jobs.transaction_id` and
`documents.transaction_id` - become real foreign keys here, now that there is finally a table for
them to point at. Both are altered through `batch_alter_table` with an explicit `copy_from`, so
the SQLite fallback the test suite can run on rebuilds the table from a complete definition
rather than from partial reflection, and PostgreSQL takes the plain ALTER path.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.models.enums import (
    BUSINESS_STREAMS,
    DOCUMENT_TYPES,
    EXTRACTION_STATUSES,
    INVOICE_STATUSES,
    MATCH_METHODS,
    PRICE_BASES,
    RULE_SEVERITIES,
    TERRITORIES,
    TRANSACTION_STATUSES,
    DocumentType,
    sql_in_list,
)
from app.services.rules.defaults import COMMODITY_CODES, default_rule_configurations
from app.services.schema_defaults import INVOICE_FIELDS

revision: str = "20250301_000003"
down_revision: str | None = "20250201_000002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GUID = sa.Uuid(as_uuid=True)
JSONB_TYPE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
MONEY = sa.Numeric(18, 4)
QUANTITY = sa.Numeric(14, 3)
PERCENT = sa.Numeric(7, 4)

# Fields this migration adds to the seeded invoice schema. The purchase leg records who invoiced
# and whether the invoice is provisional or final, and neither can be read off a document the
# extraction was never asked to look for them on.
ADDED_INVOICE_FIELDS = ("supplier_name", "invoice_status")


def _documents_table(*, with_transaction_fk: bool = False) -> sa.Table:
    """`documents` exactly as  created it, so a batch rebuild loses nothing.

    A SQLite batch rebuild works from this definition rather than from reflection, so it has to
    describe the table as it stands at that moment: without the transaction foreign key when the
    upgrade is about to add it, and with it when the downgrade is about to drop it.
    """
    metadata = sa.MetaData()
    constraints: list[sa.schema.SchemaItem] = []
    if with_transaction_fk:
        constraints.append(
            sa.ForeignKeyConstraint(
                ["transaction_id"],
                ["trade_transactions.id"],
                name="fk_documents_transaction_id_trade_transactions",
                ondelete="SET NULL",
            )
        )
    table = sa.Table(
        "documents",
        metadata,
        sa.Column("id", GUID, nullable=False),
        sa.Column("request_id", GUID, nullable=False),
        sa.Column("transaction_id", GUID, nullable=True),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("document_type", sa.String(length=32), nullable=True),
        sa.Column("original_document_type", sa.String(length=32), nullable=True),
        sa.Column("document_type_hint", sa.String(length=32), nullable=True),
        sa.Column("territory", sa.String(length=16), nullable=True),
        sa.Column("storage_ref", sa.String(length=512), nullable=False),
        sa.Column("page_image_refs", JSONB_TYPE, nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("extraction_status", sa.String(length=16), nullable=False),
        sa.Column("extraction_error", sa.Text(), nullable=True),
        sa.Column("classification_confidence", sa.Float(), nullable=True),
        sa.Column("classification_rationale", sa.Text(), nullable=True),
        sa.Column("needs_review", sa.Boolean(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_by_id", GUID, nullable=True),
        sa.Column("uploaded_by_id", GUID, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            f"document_type IS NULL OR document_type IN ({sql_in_list(DOCUMENT_TYPES)})",
            name="ck_documents_document_type_valid",
        ),
        sa.CheckConstraint(
            f"territory IS NULL OR territory IN ({sql_in_list(TERRITORIES)})",
            name="ck_documents_document_territory_valid",
        ),
        sa.CheckConstraint(
            f"extraction_status IN ({sql_in_list(EXTRACTION_STATUSES)})",
            name="ck_documents_document_extraction_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["requests.id"],
            name="fk_documents_request_id_requests",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by_id"],
            ["users.id"],
            name="fk_documents_confirmed_by_id_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_id"],
            ["users.id"],
            name="fk_documents_uploaded_by_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_documents"),
        *constraints,
    )
    sa.Index("ix_documents_request_id", table.c.request_id)
    sa.Index("ix_documents_transaction_id", table.c.transaction_id)
    sa.Index("ix_documents_filename", table.c.filename)
    sa.Index("ix_documents_document_type", table.c.document_type)
    sa.Index("ix_documents_territory", table.c.territory)
    sa.Index("ix_documents_content_hash", table.c.content_hash)
    sa.Index("ix_documents_extraction_status", table.c.extraction_status)
    sa.Index("ix_documents_classification_confidence", table.c.classification_confidence)
    sa.Index("ix_documents_needs_review", table.c.needs_review)
    sa.Index("ix_documents_confirmed_at", table.c.confirmed_at)
    sa.Index("ix_documents_confirmed_by_id", table.c.confirmed_by_id)
    sa.Index("ix_documents_uploaded_by_id", table.c.uploaded_by_id)
    sa.Index("ix_documents_created_at", table.c.created_at)
    sa.Index("ix_documents_type_created_at", table.c.document_type, table.c.created_at)
    return table


def _background_jobs_table(*, with_transaction_fk: bool = False) -> sa.Table:
    """`background_jobs` exactly as  created it, plus the key when there is one to drop."""
    metadata = sa.MetaData()
    constraints: list[sa.schema.SchemaItem] = []
    if with_transaction_fk:
        constraints.append(
            sa.ForeignKeyConstraint(
                ["transaction_id"],
                ["trade_transactions.id"],
                name="fk_background_jobs_transaction_id_trade_transactions",
                ondelete="SET NULL",
            )
        )
    table = sa.Table(
        "background_jobs",
        metadata,
        sa.Column("id", GUID, nullable=False),
        sa.Column("job_type", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("result_ref", sa.String(length=512), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("transaction_id", GUID, nullable=True),
        sa.Column("created_by_id", GUID, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "progress >= 0 AND progress <= 100", name="ck_background_jobs_progress_range"
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'processing', 'completed', 'failed')",
            name="ck_background_jobs_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_background_jobs_created_by_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_background_jobs"),
        *constraints,
    )
    sa.Index("ix_background_jobs_job_type", table.c.job_type)
    sa.Index("ix_background_jobs_status", table.c.status)
    sa.Index("ix_background_jobs_transaction_id", table.c.transaction_id)
    sa.Index("ix_background_jobs_created_by_id", table.c.created_by_id)
    return table


def _invoice_schema_with(fields: list[dict]) -> dict:
    return {"fields": fields}


def upgrade() -> None:
    op.create_table(
        "commodity_codes",
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_commodity_codes")),
    )
    op.create_index(op.f("ix_commodity_codes_is_active"), "commodity_codes", ["is_active"])

    op.create_table(
        "batch_sequences",
        sa.Column("prefix", sa.String(length=16), nullable=False),
        sa.Column("next_value", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("prefix", name=op.f("pk_batch_sequences")),
    )

    op.create_table(
        "trade_transactions",
        sa.Column("id", GUID, nullable=False),
        sa.Column("transaction_code", sa.String(length=32), nullable=False),
        sa.Column("batch_number", sa.String(length=32), nullable=False),
        sa.Column("stream", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("commodity_code", sa.String(length=16), nullable=True),
        sa.Column("extracted_commodity_value", sa.String(length=128), nullable=True),
        sa.Column("commodity_needs_review", sa.Boolean(), nullable=False),
        sa.Column("quantity_mt", QUANTITY, nullable=True),
        sa.Column("price_basis", sa.String(length=16), nullable=True),
        sa.Column("lme_percentage", PERCENT, nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("request_id", GUID, nullable=False),
        sa.Column("match_method", sa.String(length=32), nullable=True),
        sa.Column("match_score", sa.Numeric(6, 2), nullable=True),
        sa.Column("match_rationale", sa.Text(), nullable=True),
        sa.Column("field_overrides", JSONB_TYPE, nullable=False),
        sa.Column("created_by_id", GUID, nullable=True),
        sa.Column("submitted_by_id", GUID, nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            f"stream IN ({sql_in_list(BUSINESS_STREAMS)})",
            name=op.f("ck_trade_transactions_trade_transaction_stream_valid"),
        ),
        sa.CheckConstraint(
            f"status IN ({sql_in_list(TRANSACTION_STATUSES)})",
            name=op.f("ck_trade_transactions_trade_transaction_status_valid"),
        ),
        sa.CheckConstraint(
            f"price_basis IS NULL OR price_basis IN ({sql_in_list(PRICE_BASES)})",
            name=op.f("ck_trade_transactions_trade_transaction_price_basis_valid"),
        ),
        sa.CheckConstraint(
            f"match_method IS NULL OR match_method IN ({sql_in_list(MATCH_METHODS)})",
            name=op.f("ck_trade_transactions_trade_transaction_match_method_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["commodity_code"],
            ["commodity_codes.code"],
            name=op.f("fk_trade_transactions_commodity_code_commodity_codes"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["requests.id"],
            name=op.f("fk_trade_transactions_request_id_requests"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_trade_transactions_created_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by_id"],
            ["users.id"],
            name=op.f("fk_trade_transactions_submitted_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trade_transactions")),
    )
    op.create_index(
        op.f("ix_trade_transactions_transaction_code"),
        "trade_transactions",
        ["transaction_code"],
        unique=True,
    )
    op.create_index(
        op.f("ix_trade_transactions_batch_number"),
        "trade_transactions",
        ["batch_number"],
        unique=True,
    )
    op.create_index(op.f("ix_trade_transactions_stream"), "trade_transactions", ["stream"])
    op.create_index(op.f("ix_trade_transactions_status"), "trade_transactions", ["status"])
    op.create_index(
        op.f("ix_trade_transactions_commodity_code"), "trade_transactions", ["commodity_code"]
    )
    op.create_index(
        op.f("ix_trade_transactions_commodity_needs_review"),
        "trade_transactions",
        ["commodity_needs_review"],
    )
    op.create_index(
        op.f("ix_trade_transactions_price_basis"), "trade_transactions", ["price_basis"]
    )
    op.create_index(op.f("ix_trade_transactions_request_id"), "trade_transactions", ["request_id"])
    op.create_index(
        op.f("ix_trade_transactions_match_method"), "trade_transactions", ["match_method"]
    )
    op.create_index(
        op.f("ix_trade_transactions_created_by_id"), "trade_transactions", ["created_by_id"]
    )
    op.create_index(
        op.f("ix_trade_transactions_submitted_by_id"), "trade_transactions", ["submitted_by_id"]
    )
    op.create_index(
        op.f("ix_trade_transactions_submitted_at"), "trade_transactions", ["submitted_at"]
    )
    op.create_index(op.f("ix_trade_transactions_created_at"), "trade_transactions", ["created_at"])
    op.create_index(
        "ix_trade_transactions_stream_status", "trade_transactions", ["stream", "status"]
    )
    op.create_index(
        "ix_trade_transactions_status_created_at", "trade_transactions", ["status", "created_at"]
    )

    op.create_table(
        "purchase_legs",
        sa.Column("id", GUID, nullable=False),
        sa.Column("transaction_id", GUID, nullable=False),
        sa.Column("supplier_name", sa.String(length=255), nullable=True),
        sa.Column("supplier_invoice_number", sa.String(length=64), nullable=True),
        sa.Column("contract_number", sa.String(length=64), nullable=True),
        sa.Column("invoice_status", sa.String(length=16), nullable=False),
        sa.Column("amount", MONEY, nullable=True),
        sa.Column("rate", MONEY, nullable=True),
        sa.Column("advance_payment_percent", PERCENT, nullable=True),
        sa.Column("hedge_date", sa.Date(), nullable=True),
        sa.Column("port_of_loading", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            f"invoice_status IN ({sql_in_list(INVOICE_STATUSES)})",
            name=op.f("ck_purchase_legs_purchase_leg_invoice_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["trade_transactions.id"],
            name=op.f("fk_purchase_legs_transaction_id_trade_transactions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_purchase_legs")),
    )
    op.create_index(
        op.f("ix_purchase_legs_transaction_id"), "purchase_legs", ["transaction_id"], unique=True
    )
    op.create_index(op.f("ix_purchase_legs_supplier_name"), "purchase_legs", ["supplier_name"])
    op.create_index(
        op.f("ix_purchase_legs_supplier_invoice_number"),
        "purchase_legs",
        ["supplier_invoice_number"],
    )
    op.create_index(op.f("ix_purchase_legs_contract_number"), "purchase_legs", ["contract_number"])
    op.create_index(op.f("ix_purchase_legs_invoice_status"), "purchase_legs", ["invoice_status"])

    op.create_table(
        "rule_configurations",
        sa.Column("id", GUID, nullable=False),
        sa.Column("rule_id", sa.String(length=8), nullable=False),
        sa.Column("check_key", sa.String(length=48), nullable=False),
        sa.Column("scope_commodity_code", sa.String(length=16), nullable=True),
        sa.Column("scope_transaction_type", sa.String(length=16), nullable=True),
        sa.Column("scope_stream", sa.String(length=16), nullable=True),
        sa.Column("threshold_value", sa.Numeric(18, 4), nullable=False),
        sa.Column("threshold_unit", sa.String(length=16), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("change_reason", sa.Text(), nullable=False),
        sa.Column("changed_by_id", GUID, nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            f"scope_stream IS NULL OR scope_stream IN ({sql_in_list(BUSINESS_STREAMS)})",
            name=op.f("ck_rule_configurations_rule_configuration_scope_stream_valid"),
        ),
        sa.CheckConstraint(
            "threshold_unit IN ('percent', 'currency', 'count', 'ratio', 'score')",
            name=op.f("ck_rule_configurations_rule_configuration_threshold_unit_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["scope_commodity_code"],
            ["commodity_codes.code"],
            name=op.f("fk_rule_configurations_scope_commodity_code_commodity_codes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["changed_by_id"],
            ["users.id"],
            name=op.f("fk_rule_configurations_changed_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rule_configurations")),
        sa.UniqueConstraint(
            "rule_id",
            "check_key",
            "scope_commodity_code",
            "scope_transaction_type",
            name="uq_rule_configurations_rule_scope",
        ),
    )
    op.create_index(op.f("ix_rule_configurations_rule_id"), "rule_configurations", ["rule_id"])
    op.create_index(op.f("ix_rule_configurations_check_key"), "rule_configurations", ["check_key"])
    op.create_index(
        op.f("ix_rule_configurations_scope_commodity_code"),
        "rule_configurations",
        ["scope_commodity_code"],
    )
    op.create_index(
        op.f("ix_rule_configurations_scope_transaction_type"),
        "rule_configurations",
        ["scope_transaction_type"],
    )
    op.create_index(
        op.f("ix_rule_configurations_scope_stream"), "rule_configurations", ["scope_stream"]
    )
    op.create_index(op.f("ix_rule_configurations_is_active"), "rule_configurations", ["is_active"])
    op.create_index(
        op.f("ix_rule_configurations_changed_by_id"), "rule_configurations", ["changed_by_id"]
    )

    op.create_table(
        "rule_evaluations",
        sa.Column("id", GUID, nullable=False),
        sa.Column("transaction_id", GUID, nullable=False),
        sa.Column("rule_id", sa.String(length=8), nullable=False),
        sa.Column("check_key", sa.String(length=48), nullable=True),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("field_name", sa.String(length=128), nullable=True),
        sa.Column("expected_value", sa.String(length=255), nullable=True),
        sa.Column("actual_value", sa.String(length=255), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("acknowledged", sa.Boolean(), nullable=False),
        sa.Column("acknowledgement_reason", sa.Text(), nullable=True),
        sa.Column("acknowledged_by_id", GUID, nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            f"severity IN ({sql_in_list(RULE_SEVERITIES)})",
            name=op.f("ck_rule_evaluations_rule_evaluation_severity_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["trade_transactions.id"],
            name=op.f("fk_rule_evaluations_transaction_id_trade_transactions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["acknowledged_by_id"],
            ["users.id"],
            name=op.f("fk_rule_evaluations_acknowledged_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rule_evaluations")),
    )
    op.create_index(
        op.f("ix_rule_evaluations_transaction_id"), "rule_evaluations", ["transaction_id"]
    )
    op.create_index(op.f("ix_rule_evaluations_rule_id"), "rule_evaluations", ["rule_id"])
    op.create_index(op.f("ix_rule_evaluations_check_key"), "rule_evaluations", ["check_key"])
    op.create_index(op.f("ix_rule_evaluations_passed"), "rule_evaluations", ["passed"])
    op.create_index(op.f("ix_rule_evaluations_severity"), "rule_evaluations", ["severity"])
    op.create_index(op.f("ix_rule_evaluations_acknowledged"), "rule_evaluations", ["acknowledged"])
    op.create_index(
        op.f("ix_rule_evaluations_acknowledged_by_id"), "rule_evaluations", ["acknowledged_by_id"]
    )
    op.create_index(op.f("ix_rule_evaluations_evaluated_at"), "rule_evaluations", ["evaluated_at"])
    op.create_index(
        "ix_rule_evaluations_transaction_rule",
        "rule_evaluations",
        ["transaction_id", "rule_id", "check_key", "evaluated_at"],
    )

    # --- the two deferred foreign keys ------------------------------------------------------
    with op.batch_alter_table("background_jobs", copy_from=_background_jobs_table()) as batch:
        batch.create_foreign_key(
            "fk_background_jobs_transaction_id_trade_transactions",
            "trade_transactions",
            ["transaction_id"],
            ["id"],
            ondelete="SET NULL",
        )

    with op.batch_alter_table("documents", copy_from=_documents_table()) as batch:
        batch.create_foreign_key(
            "fk_documents_transaction_id_trade_transactions",
            "trade_transactions",
            ["transaction_id"],
            ["id"],
            ondelete="SET NULL",
        )

    # --- seed data ----------------------------------------------------------------------------
    now = datetime.now(timezone.utc)

    op.bulk_insert(
        sa.table(
            "commodity_codes",
            sa.column("code", sa.String),
            sa.column("display_name", sa.String),
            sa.column("is_active", sa.Boolean),
            sa.column("created_at", sa.DateTime(timezone=True)),
        ),
        [{**row, "created_at": now} for row in COMMODITY_CODES],
    )

    op.bulk_insert(
        sa.table(
            "rule_configurations",
            sa.column("id", GUID),
            sa.column("rule_id", sa.String),
            sa.column("check_key", sa.String),
            sa.column("scope_commodity_code", sa.String),
            sa.column("scope_transaction_type", sa.String),
            sa.column("scope_stream", sa.String),
            sa.column("threshold_value", sa.Numeric(18, 4)),
            sa.column("threshold_unit", sa.String),
            sa.column("description", sa.Text),
            sa.column("is_active", sa.Boolean),
            sa.column("change_reason", sa.Text),
            sa.column("changed_by_id", GUID),
            sa.column("changed_at", sa.DateTime(timezone=True)),
            sa.column("created_at", sa.DateTime(timezone=True)),
        ),
        [
            {
                "id": uuid.uuid4(),
                **row,
                "changed_by_id": None,
                "changed_at": now,
                "created_at": now,
            }
            for row in default_rule_configurations()
        ],
    )

    # The invoice schema gains the supplier and the provisional/final marker the purchase leg
    # needs. A field list is data, so this is a row update rather than a code change.
    schemas = sa.table(
        "document_type_schemas",
        sa.column("document_type", sa.String),
        sa.column("field_schema", JSONB_TYPE),
        sa.column("changed_at", sa.DateTime(timezone=True)),
    )
    op.execute(
        schemas.update()
        .where(schemas.c.document_type == DocumentType.INVOICE.value)
        .values(field_schema=_invoice_schema_with(INVOICE_FIELDS), changed_at=now)
    )


def downgrade() -> None:
    schemas = sa.table(
        "document_type_schemas",
        sa.column("document_type", sa.String),
        sa.column("field_schema", JSONB_TYPE),
        sa.column("changed_at", sa.DateTime(timezone=True)),
    )
    op.execute(
        schemas.update()
        .where(schemas.c.document_type == DocumentType.INVOICE.value)
        .values(
            field_schema=_invoice_schema_with(
                [field for field in INVOICE_FIELDS if field["name"] not in ADDED_INVOICE_FIELDS]
            ),
            changed_at=datetime.now(timezone.utc),
        )
    )

    with op.batch_alter_table(
        "documents", copy_from=_documents_table(with_transaction_fk=True)
    ) as batch:
        batch.drop_constraint("fk_documents_transaction_id_trade_transactions", type_="foreignkey")
    with op.batch_alter_table(
        "background_jobs", copy_from=_background_jobs_table(with_transaction_fk=True)
    ) as batch:
        batch.drop_constraint(
            "fk_background_jobs_transaction_id_trade_transactions", type_="foreignkey"
        )

    op.drop_index("ix_rule_evaluations_transaction_rule", table_name="rule_evaluations")
    op.drop_index(op.f("ix_rule_evaluations_evaluated_at"), table_name="rule_evaluations")
    op.drop_index(op.f("ix_rule_evaluations_acknowledged_by_id"), table_name="rule_evaluations")
    op.drop_index(op.f("ix_rule_evaluations_acknowledged"), table_name="rule_evaluations")
    op.drop_index(op.f("ix_rule_evaluations_severity"), table_name="rule_evaluations")
    op.drop_index(op.f("ix_rule_evaluations_passed"), table_name="rule_evaluations")
    op.drop_index(op.f("ix_rule_evaluations_check_key"), table_name="rule_evaluations")
    op.drop_index(op.f("ix_rule_evaluations_rule_id"), table_name="rule_evaluations")
    op.drop_index(op.f("ix_rule_evaluations_transaction_id"), table_name="rule_evaluations")
    op.drop_table("rule_evaluations")

    op.drop_index(op.f("ix_rule_configurations_changed_by_id"), table_name="rule_configurations")
    op.drop_index(op.f("ix_rule_configurations_is_active"), table_name="rule_configurations")
    op.drop_index(op.f("ix_rule_configurations_scope_stream"), table_name="rule_configurations")
    op.drop_index(
        op.f("ix_rule_configurations_scope_transaction_type"), table_name="rule_configurations"
    )
    op.drop_index(
        op.f("ix_rule_configurations_scope_commodity_code"), table_name="rule_configurations"
    )
    op.drop_index(op.f("ix_rule_configurations_check_key"), table_name="rule_configurations")
    op.drop_index(op.f("ix_rule_configurations_rule_id"), table_name="rule_configurations")
    op.drop_table("rule_configurations")

    op.drop_index(op.f("ix_purchase_legs_invoice_status"), table_name="purchase_legs")
    op.drop_index(op.f("ix_purchase_legs_contract_number"), table_name="purchase_legs")
    op.drop_index(op.f("ix_purchase_legs_supplier_invoice_number"), table_name="purchase_legs")
    op.drop_index(op.f("ix_purchase_legs_supplier_name"), table_name="purchase_legs")
    op.drop_index(op.f("ix_purchase_legs_transaction_id"), table_name="purchase_legs")
    op.drop_table("purchase_legs")

    op.drop_index("ix_trade_transactions_status_created_at", table_name="trade_transactions")
    op.drop_index("ix_trade_transactions_stream_status", table_name="trade_transactions")
    op.drop_index(op.f("ix_trade_transactions_created_at"), table_name="trade_transactions")
    op.drop_index(op.f("ix_trade_transactions_submitted_at"), table_name="trade_transactions")
    op.drop_index(op.f("ix_trade_transactions_submitted_by_id"), table_name="trade_transactions")
    op.drop_index(op.f("ix_trade_transactions_created_by_id"), table_name="trade_transactions")
    op.drop_index(op.f("ix_trade_transactions_match_method"), table_name="trade_transactions")
    op.drop_index(op.f("ix_trade_transactions_request_id"), table_name="trade_transactions")
    op.drop_index(op.f("ix_trade_transactions_price_basis"), table_name="trade_transactions")
    op.drop_index(
        op.f("ix_trade_transactions_commodity_needs_review"), table_name="trade_transactions"
    )
    op.drop_index(op.f("ix_trade_transactions_commodity_code"), table_name="trade_transactions")
    op.drop_index(op.f("ix_trade_transactions_status"), table_name="trade_transactions")
    op.drop_index(op.f("ix_trade_transactions_stream"), table_name="trade_transactions")
    op.drop_index(op.f("ix_trade_transactions_batch_number"), table_name="trade_transactions")
    op.drop_index(op.f("ix_trade_transactions_transaction_code"), table_name="trade_transactions")
    op.drop_table("trade_transactions")

    op.drop_table("batch_sequences")

    op.drop_index(op.f("ix_commodity_codes_is_active"), table_name="commodity_codes")
    op.drop_table("commodity_codes")

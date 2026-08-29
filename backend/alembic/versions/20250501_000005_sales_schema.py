"""the sales leg, generated documents, and the sales module's own rule and schema rows

Revision ID: 20250501_000005
Revises: 20250401_000004
Create Date: 2025-05-01 00:00:05.000000+00:00

Layered on the  schema. One table is added and one is altered.

`sales_legs` is the whole of the attachment described in : it carries its own one-to-one
foreign key to `trade_transactions`, and `trade_transactions` itself is not touched by this
migration at all. That is the design  committed to when it built the parent record, and
this migration is the check on it.

`documents` is altered in three ways, all of them to make room for the first document in the
platform that nothing received: `request_id` becomes nullable, a `source` column records how a
document came to exist, and the document-type and extraction-status vocabularies widen to carry
the draft/original bill-of-lading distinction BR-07 turns on, the two documents the platform
generates, and the honest `not_applicable` extraction state of a document the system wrote
itself. As in, the SQLite fallback the test suite can run on rebuilds the table
from an explicit `copy_from` definition rather than from partial reflection, and PostgreSQL takes
the plain ALTER path.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.models.enums import (
    DOCUMENT_SOURCES,
    DOCUMENT_TYPES,
    EXTRACTION_STATUSES,
    FIXATION_STATUSES,
    PAYMENT_CONDITIONS,
    TERRITORIES,
    DocumentSource,
    DocumentType,
    ExtractionStatus,
    sql_in_list,
)
from app.services.governance.categories import sales_rule_exception_mappings
from app.services.rules.defaults import sales_rule_configurations
from app.services.schema_defaults import SEED_CHANGE_REASON, sales_schema_rows

revision: str = "20250501_000005"
down_revision: str | None = "20250401_000004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GUID = sa.Uuid(as_uuid=True)
JSONB_TYPE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
MONEY = sa.Numeric(18, 4)
QUANTITY = sa.Numeric(14, 3)

TYPE_CONSTRAINT = "ck_documents_document_type_valid"
STATUS_CONSTRAINT = "ck_documents_document_extraction_status_valid"
SOURCE_CONSTRAINT = "ck_documents_document_source_valid"
ORIGIN_CONSTRAINT = "ck_documents_document_request_or_generated"

# The vocabularies as they stood before this migration, so the downgrade can put them back.
PREVIOUS_DOCUMENT_TYPES = tuple(
    value
    for value in DOCUMENT_TYPES
    if value
    not in (
        DocumentType.BL_DRAFT.value,
        DocumentType.DRAFT_CONTRACT.value,
        DocumentType.DRAFT_INVOICE.value,
    )
)
PREVIOUS_EXTRACTION_STATUSES = tuple(
    value for value in EXTRACTION_STATUSES if value != ExtractionStatus.NOT_APPLICABLE.value
)


def _documents_table(
    *,
    with_source: bool,
    document_types: tuple[str, ...],
    extraction_statuses: tuple[str, ...],
    request_id_nullable: bool,
) -> sa.Table:
    """`documents` as it stands, so a SQLite batch rebuild loses nothing.

    Every parameter is one of the things this migration changes about the table. The upgrade
    describes it as it is *before* the rebuild for the columns being copied and as it should be
    *after* for the constraints being installed, which is exactly how alembic's batch mode works:
    a column the rebuild adds is not part of the data transfer, so it takes its server default.
    """
    metadata = sa.MetaData()
    columns: list[sa.schema.SchemaItem] = [
        sa.Column("id", GUID, nullable=False),
        sa.Column("request_id", GUID, nullable=request_id_nullable),
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
    ]
    if with_source:
        columns.append(
            sa.Column(
                "source",
                sa.String(length=16),
                nullable=False,
                server_default=DocumentSource.RECEIVED.value,
            )
        )

    constraints: list[sa.schema.SchemaItem] = [
        sa.CheckConstraint(
            f"document_type IS NULL OR document_type IN ({sql_in_list(document_types)})",
            name=TYPE_CONSTRAINT,
        ),
        sa.CheckConstraint(
            f"territory IS NULL OR territory IN ({sql_in_list(TERRITORIES)})",
            name="ck_documents_document_territory_valid",
        ),
        sa.CheckConstraint(
            f"extraction_status IN ({sql_in_list(extraction_statuses)})",
            name=STATUS_CONSTRAINT,
        ),
    ]
    if with_source:
        constraints.extend(
            [
                sa.CheckConstraint(
                    f"source IN ({sql_in_list(DOCUMENT_SOURCES)})", name=SOURCE_CONSTRAINT
                ),
                sa.CheckConstraint(
                    "request_id IS NOT NULL OR source = 'generated'", name=ORIGIN_CONSTRAINT
                ),
            ]
        )

    table = sa.Table(
        "documents",
        metadata,
        *columns,
        *constraints,
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["requests.id"],
            name="fk_documents_request_id_requests",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["trade_transactions.id"],
            name="fk_documents_transaction_id_trade_transactions",
            ondelete="SET NULL",
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
    if with_source:
        sa.Index("ix_documents_source", table.c.source)
    return table


def _alter_documents_upgrade() -> None:
    """Widen `documents` to carry a document the platform wrote itself.

    Split by dialect for the same reason the  migration split its constraint change: batch
    mode's constraint operations re-apply the metadata naming template to names that already
    carry it. PostgreSQL takes plain ALTERs; SQLite, which cannot alter a constraint at all,
    rebuilds the table from the definition above with the new vocabularies already in place.
    """
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(
            "documents",
            copy_from=_documents_table(
                with_source=False,
                document_types=DOCUMENT_TYPES,
                extraction_statuses=EXTRACTION_STATUSES,
                request_id_nullable=False,
            ),
        ) as batch:
            batch.add_column(
                sa.Column(
                    "source",
                    sa.String(length=16),
                    nullable=False,
                    server_default=DocumentSource.RECEIVED.value,
                )
            )
            batch.alter_column("request_id", existing_type=GUID, nullable=True)
        # A second rebuild, from the complete new definition, so the two constraints that name
        # `source` are installed against a table that now has the column.
        with op.batch_alter_table(
            "documents",
            copy_from=_documents_table(
                with_source=True,
                document_types=DOCUMENT_TYPES,
                extraction_statuses=EXTRACTION_STATUSES,
                request_id_nullable=True,
            ),
            recreate="always",
        ):
            pass
        # The index comes with the rebuild, from the definition above. Creating it again here
        # would be a duplicate; the PostgreSQL path below adds it explicitly instead.
        return

    op.add_column(
        "documents",
        sa.Column(
            "source",
            sa.String(length=16),
            nullable=False,
            server_default=DocumentSource.RECEIVED.value,
        ),
    )
    op.create_index("ix_documents_source", "documents", ["source"])
    op.alter_column("documents", "request_id", existing_type=GUID, nullable=True)
    op.execute(f'ALTER TABLE documents DROP CONSTRAINT "{TYPE_CONSTRAINT}"')
    op.execute(
        f'ALTER TABLE documents ADD CONSTRAINT "{TYPE_CONSTRAINT}" '
        f"CHECK (document_type IS NULL OR document_type IN ({sql_in_list(DOCUMENT_TYPES)}))"
    )
    op.execute(f'ALTER TABLE documents DROP CONSTRAINT "{STATUS_CONSTRAINT}"')
    op.execute(
        f'ALTER TABLE documents ADD CONSTRAINT "{STATUS_CONSTRAINT}" '
        f"CHECK (extraction_status IN ({sql_in_list(EXTRACTION_STATUSES)}))"
    )
    op.execute(
        f'ALTER TABLE documents ADD CONSTRAINT "{SOURCE_CONSTRAINT}" '
        f"CHECK (source IN ({sql_in_list(DOCUMENT_SOURCES)}))"
    )
    op.execute(
        f'ALTER TABLE documents ADD CONSTRAINT "{ORIGIN_CONSTRAINT}" '
        "CHECK (request_id IS NOT NULL OR source = 'generated')"
    )


def _alter_documents_downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(
            "documents",
            copy_from=_documents_table(
                with_source=True,
                document_types=PREVIOUS_DOCUMENT_TYPES,
                extraction_statuses=PREVIOUS_EXTRACTION_STATUSES,
                request_id_nullable=True,
            ),
        ) as batch:
            batch.drop_column("source")
            batch.alter_column("request_id", existing_type=GUID, nullable=False)
        return

    op.execute(f'ALTER TABLE documents DROP CONSTRAINT "{ORIGIN_CONSTRAINT}"')
    op.execute(f'ALTER TABLE documents DROP CONSTRAINT "{SOURCE_CONSTRAINT}"')
    op.drop_index("ix_documents_source", table_name="documents")
    op.drop_column("documents", "source")
    op.alter_column("documents", "request_id", existing_type=GUID, nullable=False)
    op.execute(f'ALTER TABLE documents DROP CONSTRAINT "{TYPE_CONSTRAINT}"')
    op.execute(
        f'ALTER TABLE documents ADD CONSTRAINT "{TYPE_CONSTRAINT}" '
        "CHECK (document_type IS NULL OR document_type IN "
        f"({sql_in_list(PREVIOUS_DOCUMENT_TYPES)}))"
    )
    op.execute(f'ALTER TABLE documents DROP CONSTRAINT "{STATUS_CONSTRAINT}"')
    op.execute(
        f'ALTER TABLE documents ADD CONSTRAINT "{STATUS_CONSTRAINT}" '
        f"CHECK (extraction_status IN ({sql_in_list(PREVIOUS_EXTRACTION_STATUSES)}))"
    )


def upgrade() -> None:
    op.create_table(
        "sales_legs",
        sa.Column("id", GUID, nullable=False),
        sa.Column("transaction_id", GUID, nullable=False),
        sa.Column("customer_name", sa.String(length=255), nullable=False),
        sa.Column("territory", sa.String(length=16), nullable=False),
        sa.Column("sales_contract_no", sa.String(length=64), nullable=False),
        sa.Column("contracted_quantity_mt", QUANTITY, nullable=True),
        sa.Column("sales_invoice_number", sa.String(length=64), nullable=True),
        sa.Column("bl_reference", sa.String(length=64), nullable=True),
        sa.Column("payment_condition", sa.String(length=8), nullable=False),
        sa.Column("customer_fixation_status", sa.String(length=16), nullable=False),
        sa.Column("fixation_rate", MONEY, nullable=True),
        sa.Column("fixation_date", sa.Date(), nullable=True),
        sa.Column("port_of_discharge", sa.String(length=128), nullable=True),
        sa.Column("inland_container_depot", sa.String(length=128), nullable=True),
        sa.Column("extracted_commodity_value", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            f"territory IN ({sql_in_list(TERRITORIES)})",
            name=op.f("ck_sales_legs_sales_leg_territory_valid"),
        ),
        sa.CheckConstraint(
            f"payment_condition IN ({sql_in_list(PAYMENT_CONDITIONS)})",
            name=op.f("ck_sales_legs_sales_leg_payment_condition_valid"),
        ),
        sa.CheckConstraint(
            f"customer_fixation_status IN ({sql_in_list(FIXATION_STATUSES)})",
            name=op.f("ck_sales_legs_sales_leg_fixation_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["trade_transactions.id"],
            name=op.f("fk_sales_legs_transaction_id_trade_transactions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sales_legs")),
    )
    # Unique, which is what makes the relationship one-to-one and what stops a second sales leg
    # from being attached to a batch that already carries one.
    op.create_index(
        op.f("ix_sales_legs_transaction_id"), "sales_legs", ["transaction_id"], unique=True
    )
    op.create_index(op.f("ix_sales_legs_customer_name"), "sales_legs", ["customer_name"])
    op.create_index(op.f("ix_sales_legs_territory"), "sales_legs", ["territory"])
    op.create_index(op.f("ix_sales_legs_sales_contract_no"), "sales_legs", ["sales_contract_no"])
    op.create_index(
        op.f("ix_sales_legs_sales_invoice_number"), "sales_legs", ["sales_invoice_number"]
    )
    op.create_index(op.f("ix_sales_legs_bl_reference"), "sales_legs", ["bl_reference"])
    op.create_index(op.f("ix_sales_legs_payment_condition"), "sales_legs", ["payment_condition"])
    op.create_index(
        op.f("ix_sales_legs_customer_fixation_status"),
        "sales_legs",
        ["customer_fixation_status"],
    )
    op.create_index(
        "ix_sales_legs_contract_customer",
        "sales_legs",
        ["sales_contract_no", "customer_name"],
    )

    _alter_documents_upgrade()

    now = datetime.now(timezone.utc)

    # The bill-of-lading extraction schema. The sales workflow triggers off this document type,
    # and  seeded only the invoice and the contract.
    op.bulk_insert(
        sa.table(
            "document_type_schemas",
            sa.column("id", GUID),
            sa.column("document_type", sa.String),
            sa.column("territory", sa.String),
            sa.column("field_schema", JSONB_TYPE),
            sa.column("mandatory_documents", JSONB_TYPE),
            sa.column("change_reason", sa.Text),
            sa.column("changed_by_id", GUID),
            sa.column("changed_at", sa.DateTime(timezone=True)),
            sa.column("created_at", sa.DateTime(timezone=True)),
        ),
        [
            {
                "id": uuid.uuid4(),
                "document_type": row["document_type"],
                "territory": row["territory"],
                "field_schema": row["field_schema"],
                "mandatory_documents": row["mandatory_documents"],
                "change_reason": SEED_CHANGE_REASON,
                "changed_by_id": None,
                "changed_at": now,
                "created_at": now,
            }
            for row in sales_schema_rows()
        ],
    )

    # SL-01's threshold, into the table every other rule already reads from.
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
            for row in sales_rule_configurations()
        ],
    )

    # Two rows, and the whole of what routing the sales module's failures required. No branch was
    # added to the exception hook, and none to the rule orchestrator.
    op.bulk_insert(
        sa.table(
            "rule_exception_mappings",
            sa.column("id", GUID),
            sa.column("rule_id", sa.String),
            sa.column("check_key", sa.String),
            sa.column("exception_type", sa.String),
            sa.column("owner_role", sa.String),
            sa.column("priority", sa.String),
            sa.column("description", sa.Text),
            sa.column("is_active", sa.Boolean),
            sa.column("created_at", sa.DateTime(timezone=True)),
        ),
        [{"id": uuid.uuid4(), **row, "created_at": now} for row in sales_rule_exception_mappings()],
    )


def downgrade() -> None:
    mappings = sa.table(
        "rule_exception_mappings",
        sa.column("rule_id", sa.String),
        sa.column("check_key", sa.String),
    )
    for row in sales_rule_exception_mappings():
        op.execute(
            mappings.delete().where(
                mappings.c.rule_id == row["rule_id"],
                mappings.c.check_key == row["check_key"],
            )
        )

    configurations = sa.table("rule_configurations", sa.column("rule_id", sa.String))
    op.execute(
        configurations.delete().where(
            configurations.c.rule_id.in_(
                sorted({row["rule_id"] for row in sales_rule_configurations()})
            )
        )
    )

    schemas = sa.table("document_type_schemas", sa.column("document_type", sa.String))
    op.execute(
        schemas.delete().where(
            schemas.c.document_type.in_(
                sorted({row["document_type"] for row in sales_schema_rows()})
            )
        )
    )

    # Anything the narrowed vocabularies would reject goes before they are reinstated. A
    # generated draft cannot exist under the old schema at all - it has no request behind it -
    # so it is removed rather than left to break the NOT NULL that is about to come back.
    documents = sa.table(
        "documents",
        sa.column("source", sa.String),
        sa.column("document_type", sa.String),
        sa.column("extraction_status", sa.String),
    )
    op.execute(documents.delete().where(documents.c.source == DocumentSource.GENERATED.value))
    op.execute(
        documents.update()
        .where(documents.c.document_type == DocumentType.BL_DRAFT.value)
        .values(document_type=DocumentType.BL.value)
    )
    op.execute(
        documents.update()
        .where(documents.c.extraction_status == ExtractionStatus.NOT_APPLICABLE.value)
        .values(extraction_status=ExtractionStatus.COMPLETED.value)
    )

    _alter_documents_downgrade()

    op.drop_index("ix_sales_legs_contract_customer", table_name="sales_legs")
    op.drop_index(op.f("ix_sales_legs_customer_fixation_status"), table_name="sales_legs")
    op.drop_index(op.f("ix_sales_legs_payment_condition"), table_name="sales_legs")
    op.drop_index(op.f("ix_sales_legs_bl_reference"), table_name="sales_legs")
    op.drop_index(op.f("ix_sales_legs_sales_invoice_number"), table_name="sales_legs")
    op.drop_index(op.f("ix_sales_legs_sales_contract_no"), table_name="sales_legs")
    op.drop_index(op.f("ix_sales_legs_territory"), table_name="sales_legs")
    op.drop_index(op.f("ix_sales_legs_customer_name"), table_name="sales_legs")
    op.drop_index(op.f("ix_sales_legs_transaction_id"), table_name="sales_legs")
    op.drop_table("sales_legs")

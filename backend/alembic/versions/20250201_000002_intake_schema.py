"""email and document intake schema

Revision ID: 20250201_000002
Revises: 20250101_000001
Create Date: 2025-02-01 00:00:02.000000+00:00

Layered on top of the Step 1 schema: nothing here alters `users`, `audit_events` or
`background_jobs`. `documents.transaction_id` deliberately carries no foreign key, exactly like
`background_jobs.transaction_id`, because the transactions table does not exist until Step 3.
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
    REQUEST_CATEGORIES,
    REQUEST_SOURCES,
    REQUEST_STATUSES,
    TERRITORIES,
    sql_in_list,
)
from app.services.schema_defaults import SEED_CHANGE_REASON, default_schema_rows

revision: str = "20250201_000002"
down_revision: str | None = "20250101_000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GUID = sa.Uuid(as_uuid=True)
JSONB_TYPE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "email_messages",
        sa.Column("id", GUID, nullable=False),
        sa.Column("provider_message_id", sa.String(length=512), nullable=False),
        sa.Column("mailbox_address", sa.String(length=320), nullable=False),
        sa.Column("sender_address", sa.String(length=320), nullable=True),
        sa.Column("sender_name", sa.String(length=255), nullable=True),
        sa.Column("subject", sa.String(length=1024), nullable=True),
        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("has_attachments", sa.Boolean(), nullable=False),
        sa.Column("raw_storage_ref", sa.String(length=512), nullable=True),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_messages")),
    )
    op.create_index(
        op.f("ix_email_messages_provider_message_id"),
        "email_messages",
        ["provider_message_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_email_messages_mailbox_address"), "email_messages", ["mailbox_address"]
    )
    op.create_index(op.f("ix_email_messages_sender_address"), "email_messages", ["sender_address"])
    op.create_index(op.f("ix_email_messages_received_at"), "email_messages", ["received_at"])

    op.create_table(
        "requests",
        sa.Column("id", GUID, nullable=False),
        sa.Column("request_code", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("email_message_id", GUID, nullable=True),
        sa.Column("category", sa.String(length=32), nullable=True),
        sa.Column("category_confidence", sa.Float(), nullable=True),
        sa.Column("category_rationale", sa.Text(), nullable=True),
        sa.Column("original_category", sa.String(length=32), nullable=True),
        sa.Column("category_overridden", sa.Boolean(), nullable=False),
        sa.Column("category_override_reason", sa.Text(), nullable=True),
        sa.Column("category_overridden_by_id", GUID, nullable=True),
        sa.Column("category_overridden_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stream", sa.String(length=16), nullable=True),
        sa.Column("original_stream", sa.String(length=16), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("needs_review", sa.Boolean(), nullable=False),
        sa.Column("classification_error", sa.Text(), nullable=True),
        sa.Column("created_by_id", GUID, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            f"source IN ({sql_in_list(REQUEST_SOURCES)})",
            name=op.f("ck_requests_request_source_valid"),
        ),
        sa.CheckConstraint(
            f"category IS NULL OR category IN ({sql_in_list(REQUEST_CATEGORIES)})",
            name=op.f("ck_requests_request_category_valid"),
        ),
        sa.CheckConstraint(
            f"stream IS NULL OR stream IN ({sql_in_list(BUSINESS_STREAMS)})",
            name=op.f("ck_requests_request_stream_valid"),
        ),
        sa.CheckConstraint(
            f"status IN ({sql_in_list(REQUEST_STATUSES)})",
            name=op.f("ck_requests_request_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["email_message_id"],
            ["email_messages.id"],
            name=op.f("fk_requests_email_message_id_email_messages"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["category_overridden_by_id"],
            ["users.id"],
            name=op.f("fk_requests_category_overridden_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_requests_created_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_requests")),
    )
    op.create_index(op.f("ix_requests_request_code"), "requests", ["request_code"], unique=True)
    op.create_index(op.f("ix_requests_source"), "requests", ["source"])
    op.create_index(op.f("ix_requests_email_message_id"), "requests", ["email_message_id"])
    op.create_index(op.f("ix_requests_category"), "requests", ["category"])
    op.create_index(op.f("ix_requests_category_confidence"), "requests", ["category_confidence"])
    op.create_index(op.f("ix_requests_category_overridden"), "requests", ["category_overridden"])
    op.create_index(
        op.f("ix_requests_category_overridden_by_id"), "requests", ["category_overridden_by_id"]
    )
    op.create_index(op.f("ix_requests_stream"), "requests", ["stream"])
    op.create_index(op.f("ix_requests_status"), "requests", ["status"])
    op.create_index(op.f("ix_requests_needs_review"), "requests", ["needs_review"])
    op.create_index(op.f("ix_requests_created_by_id"), "requests", ["created_by_id"])
    op.create_index(op.f("ix_requests_created_at"), "requests", ["created_at"])
    op.create_index("ix_requests_status_created_at", "requests", ["status", "created_at"])

    op.create_table(
        "documents",
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
            name=op.f("ck_documents_document_type_valid"),
        ),
        sa.CheckConstraint(
            f"territory IS NULL OR territory IN ({sql_in_list(TERRITORIES)})",
            name=op.f("ck_documents_document_territory_valid"),
        ),
        sa.CheckConstraint(
            f"extraction_status IN ({sql_in_list(EXTRACTION_STATUSES)})",
            name=op.f("ck_documents_document_extraction_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["requests.id"],
            name=op.f("fk_documents_request_id_requests"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by_id"],
            ["users.id"],
            name=op.f("fk_documents_confirmed_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_id"],
            ["users.id"],
            name=op.f("fk_documents_uploaded_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
    )
    op.create_index(op.f("ix_documents_request_id"), "documents", ["request_id"])
    op.create_index(op.f("ix_documents_transaction_id"), "documents", ["transaction_id"])
    op.create_index(op.f("ix_documents_filename"), "documents", ["filename"])
    op.create_index(op.f("ix_documents_document_type"), "documents", ["document_type"])
    op.create_index(op.f("ix_documents_territory"), "documents", ["territory"])
    op.create_index(op.f("ix_documents_content_hash"), "documents", ["content_hash"])
    op.create_index(op.f("ix_documents_extraction_status"), "documents", ["extraction_status"])
    op.create_index(
        op.f("ix_documents_classification_confidence"), "documents", ["classification_confidence"]
    )
    op.create_index(op.f("ix_documents_needs_review"), "documents", ["needs_review"])
    op.create_index(op.f("ix_documents_confirmed_at"), "documents", ["confirmed_at"])
    op.create_index(op.f("ix_documents_confirmed_by_id"), "documents", ["confirmed_by_id"])
    op.create_index(op.f("ix_documents_uploaded_by_id"), "documents", ["uploaded_by_id"])
    op.create_index(op.f("ix_documents_created_at"), "documents", ["created_at"])
    op.create_index("ix_documents_type_created_at", "documents", ["document_type", "created_at"])

    op.create_table(
        "extracted_fields",
        sa.Column("id", GUID, nullable=False),
        sa.Column("document_id", GUID, nullable=False),
        sa.Column("field_name", sa.String(length=128), nullable=False),
        sa.Column("field_value", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("source_page", sa.Integer(), nullable=True),
        sa.Column("source_reference", JSONB_TYPE, nullable=True),
        sa.Column("has_conflict", sa.Boolean(), nullable=False),
        sa.Column("conflicting_values", JSONB_TYPE, nullable=False),
        sa.Column("is_overridden", sa.Boolean(), nullable=False),
        sa.Column("original_ai_value", sa.Text(), nullable=True),
        sa.Column("original_confidence", sa.Float(), nullable=True),
        sa.Column("override_reason", sa.Text(), nullable=True),
        sa.Column("overridden_by_id", GUID, nullable=True),
        sa.Column("overridden_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_extracted_fields_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["overridden_by_id"],
            ["users.id"],
            name=op.f("fk_extracted_fields_overridden_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_extracted_fields")),
        sa.UniqueConstraint("document_id", "field_name", name="uq_extracted_fields_document_field"),
    )
    op.create_index(op.f("ix_extracted_fields_document_id"), "extracted_fields", ["document_id"])
    op.create_index(op.f("ix_extracted_fields_field_name"), "extracted_fields", ["field_name"])
    op.create_index(op.f("ix_extracted_fields_confidence"), "extracted_fields", ["confidence"])
    op.create_index(op.f("ix_extracted_fields_has_conflict"), "extracted_fields", ["has_conflict"])
    op.create_index(
        op.f("ix_extracted_fields_is_overridden"), "extracted_fields", ["is_overridden"]
    )
    op.create_index(
        op.f("ix_extracted_fields_overridden_by_id"), "extracted_fields", ["overridden_by_id"]
    )

    document_type_schemas = op.create_table(
        "document_type_schemas",
        sa.Column("id", GUID, nullable=False),
        sa.Column("document_type", sa.String(length=32), nullable=False),
        sa.Column("territory", sa.String(length=16), nullable=True),
        sa.Column("field_schema", JSONB_TYPE, nullable=False),
        sa.Column("mandatory_documents", JSONB_TYPE, nullable=False),
        sa.Column("change_reason", sa.Text(), nullable=False),
        sa.Column("changed_by_id", GUID, nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            f"document_type IN ({sql_in_list(DOCUMENT_TYPES)})",
            name=op.f("ck_document_type_schemas_document_type_schema_type_valid"),
        ),
        sa.CheckConstraint(
            f"territory IS NULL OR territory IN ({sql_in_list(TERRITORIES)})",
            name=op.f("ck_document_type_schemas_document_type_schema_territory_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["changed_by_id"],
            ["users.id"],
            name=op.f("fk_document_type_schemas_changed_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_type_schemas")),
        sa.UniqueConstraint(
            "document_type", "territory", name="uq_document_type_schemas_document_type"
        ),
    )
    op.create_index(
        op.f("ix_document_type_schemas_document_type"), "document_type_schemas", ["document_type"]
    )
    op.create_index(
        op.f("ix_document_type_schemas_territory"), "document_type_schemas", ["territory"]
    )
    op.create_index(
        op.f("ix_document_type_schemas_changed_by_id"), "document_type_schemas", ["changed_by_id"]
    )

    _seed_document_type_schemas(document_type_schemas)


def _seed_document_type_schemas(table: sa.Table) -> None:
    """Write the default extraction schemas.

    The values go in as native Python objects. `bulk_insert` binds them through the table's own
    column types, so JSONB_TYPE serialises them once for whichever dialect is running -
    serialising them here first would store a JSON string of a JSON string on SQLite.
    """
    now = datetime.now(timezone.utc)
    op.bulk_insert(
        table,
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
            for row in default_schema_rows()
        ],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_document_type_schemas_changed_by_id"), table_name="document_type_schemas"
    )
    op.drop_index(op.f("ix_document_type_schemas_territory"), table_name="document_type_schemas")
    op.drop_index(
        op.f("ix_document_type_schemas_document_type"), table_name="document_type_schemas"
    )
    op.drop_table("document_type_schemas")

    op.drop_index(op.f("ix_extracted_fields_overridden_by_id"), table_name="extracted_fields")
    op.drop_index(op.f("ix_extracted_fields_is_overridden"), table_name="extracted_fields")
    op.drop_index(op.f("ix_extracted_fields_has_conflict"), table_name="extracted_fields")
    op.drop_index(op.f("ix_extracted_fields_confidence"), table_name="extracted_fields")
    op.drop_index(op.f("ix_extracted_fields_field_name"), table_name="extracted_fields")
    op.drop_index(op.f("ix_extracted_fields_document_id"), table_name="extracted_fields")
    op.drop_table("extracted_fields")

    op.drop_index("ix_documents_type_created_at", table_name="documents")
    op.drop_index(op.f("ix_documents_created_at"), table_name="documents")
    op.drop_index(op.f("ix_documents_uploaded_by_id"), table_name="documents")
    op.drop_index(op.f("ix_documents_confirmed_by_id"), table_name="documents")
    op.drop_index(op.f("ix_documents_confirmed_at"), table_name="documents")
    op.drop_index(op.f("ix_documents_needs_review"), table_name="documents")
    op.drop_index(op.f("ix_documents_classification_confidence"), table_name="documents")
    op.drop_index(op.f("ix_documents_extraction_status"), table_name="documents")
    op.drop_index(op.f("ix_documents_content_hash"), table_name="documents")
    op.drop_index(op.f("ix_documents_territory"), table_name="documents")
    op.drop_index(op.f("ix_documents_document_type"), table_name="documents")
    op.drop_index(op.f("ix_documents_filename"), table_name="documents")
    op.drop_index(op.f("ix_documents_transaction_id"), table_name="documents")
    op.drop_index(op.f("ix_documents_request_id"), table_name="documents")
    op.drop_table("documents")

    op.drop_index("ix_requests_status_created_at", table_name="requests")
    op.drop_index(op.f("ix_requests_created_at"), table_name="requests")
    op.drop_index(op.f("ix_requests_created_by_id"), table_name="requests")
    op.drop_index(op.f("ix_requests_needs_review"), table_name="requests")
    op.drop_index(op.f("ix_requests_status"), table_name="requests")
    op.drop_index(op.f("ix_requests_stream"), table_name="requests")
    op.drop_index(op.f("ix_requests_category_overridden_by_id"), table_name="requests")
    op.drop_index(op.f("ix_requests_category_overridden"), table_name="requests")
    op.drop_index(op.f("ix_requests_category_confidence"), table_name="requests")
    op.drop_index(op.f("ix_requests_category"), table_name="requests")
    op.drop_index(op.f("ix_requests_email_message_id"), table_name="requests")
    op.drop_index(op.f("ix_requests_source"), table_name="requests")
    op.drop_index(op.f("ix_requests_request_code"), table_name="requests")
    op.drop_table("requests")

    op.drop_index(op.f("ix_email_messages_received_at"), table_name="email_messages")
    op.drop_index(op.f("ix_email_messages_sender_address"), table_name="email_messages")
    op.drop_index(op.f("ix_email_messages_mailbox_address"), table_name="email_messages")
    op.drop_index(op.f("ix_email_messages_provider_message_id"), table_name="email_messages")
    op.drop_table("email_messages")

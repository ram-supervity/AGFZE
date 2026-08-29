"""integration jobs, document packs, and the two states an approval can now reach

Revision ID: 20250701_000007
Revises: 20250601_000006
Create Date: 2025-07-01 00:00:07.000000+00:00

Two tables are added, and exactly one existing object is altered: the check constraint that
guards `trade_transactions.status`. That alteration is genuinely necessary rather than
incidental - `Integration Pending` and `Committed` are new states, and a constraint written
before they existed would refuse them - so it is done explicitly here rather than left to a
model definition that a database migrated months ago has never seen.

`Closed` is added to the constraint too, and this migration is the only place in the entire 
that mentions it. It is declared so the vocabulary is honest that the state exists; no code path
in this  sets it, because the real closure conditions - payment confirmation, complete
documentation, shipment completeness - are not specified anywhere in this platform's material.
A state the schema permits and no code can reach is the correct way to say that.

No previously-deferred foreign key needs upgrading here. Nothing built in held a
reference to an integration job or a document pack waiting for a table to exist, and no seed data
is needed either: the integration-failure exception category has been registered in the catalog
since  and routes through the standalone case-creation function rather than through a
rule-to-category mapping row, exactly as shipment staleness does.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.models.enums import (
    DOCUMENT_PACK_TYPES,
    INTEGRATION_JOB_STATUSES,
    INTEGRATION_TARGET_SYSTEMS,
    TRANSACTION_STATUSES,
    sql_in_list,
)

revision: str = "20250701_000007"
down_revision: str | None = "20250601_000006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GUID = sa.Uuid(as_uuid=True)
JSONB_TYPE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")

TRANSACTION_STATUS_CONSTRAINT = "ck_trade_transactions_trade_transaction_status_valid"

# The vocabulary as it stood before this migration. Kept literal rather than derived, so the
# downgrade restores what was actually there rather than whatever the enum happens to say later.
PREVIOUS_TRANSACTION_STATUSES: tuple[str, ...] = (
    "received",
    "classified",
    "extraction_pending",
    "extracted",
    "matched",
    "validation_pending",
    "approval_pending",
    "approved",
)


def _widen_transaction_statuses(values: tuple[str, ...]) -> None:
    """Rewrite the status check constraint.

    PostgreSQL only. SQLite - which is the suite's container-less fallback and nothing else -
    cannot drop a constraint declared inside CREATE TABLE, and does not need to: a SQLite
    database is always built from scratch by running every migration in order, so its constraint
    is created from the current vocabulary in the first place.
    """
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        f"ALTER TABLE trade_transactions DROP CONSTRAINT IF EXISTS {TRANSACTION_STATUS_CONSTRAINT}"
    )
    op.execute(
        f"ALTER TABLE trade_transactions ADD CONSTRAINT {TRANSACTION_STATUS_CONSTRAINT} "
        f"CHECK (status IN ({sql_in_list(values)}))"
    )


def _create_integration_jobs() -> None:
    op.create_table(
        "integration_jobs",
        sa.Column("id", GUID, nullable=False),
        sa.Column("transaction_id", GUID, nullable=False),
        sa.Column("target_system", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("external_reference", sa.String(length=255), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "completed_manually",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("completed_manually_by_id", GUID, nullable=True),
        sa.Column("completed_manually_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("manual_note", sa.Text(), nullable=True),
        sa.Column("prepared_payload", JSONB_TYPE, nullable=True),
        sa.Column("manual_instruction", sa.Text(), nullable=True),
        sa.Column("last_attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            f"target_system IN ({sql_in_list(INTEGRATION_TARGET_SYSTEMS)})",
            name=op.f("ck_integration_jobs_integration_job_target_system_valid"),
        ),
        sa.CheckConstraint(
            f"status IN ({sql_in_list(INTEGRATION_JOB_STATUSES)})",
            name=op.f("ck_integration_jobs_integration_job_status_valid"),
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name=op.f("ck_integration_jobs_integration_job_attempt_count_valid"),
        ),
        # The database's own guarantee behind the API's refusal of an empty reference: a job
        # marked as completed by a person must say what they completed.
        sa.CheckConstraint(
            "completed_manually = false OR external_reference IS NOT NULL",
            name=op.f("ck_integration_jobs_integration_job_manual_needs_reference"),
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["trade_transactions.id"],
            name=op.f("fk_integration_jobs_transaction_id_trade_transactions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["completed_manually_by_id"],
            ["users.id"],
            name=op.f("fk_integration_jobs_completed_manually_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_integration_jobs")),
        # Exactly one job per target per transaction. Two competing accounts of whether a deal
        # reached SAP is the one thing this table must never be able to hold.
        sa.UniqueConstraint(
            "transaction_id", "target_system", name="uq_integration_jobs_transaction_target"
        ),
    )
    op.create_index(
        op.f("ix_integration_jobs_transaction_id"), "integration_jobs", ["transaction_id"]
    )
    op.create_index(
        op.f("ix_integration_jobs_target_system"), "integration_jobs", ["target_system"]
    )
    op.create_index(op.f("ix_integration_jobs_status"), "integration_jobs", ["status"])
    op.create_index(
        op.f("ix_integration_jobs_completed_manually"),
        "integration_jobs",
        ["completed_manually"],
    )
    op.create_index(
        op.f("ix_integration_jobs_completed_manually_by_id"),
        "integration_jobs",
        ["completed_manually_by_id"],
    )
    op.create_index(
        op.f("ix_integration_jobs_last_attempted_at"), "integration_jobs", ["last_attempted_at"]
    )
    op.create_index(op.f("ix_integration_jobs_created_at"), "integration_jobs", ["created_at"])
    # What the retry sweep actually queries: everything queued, oldest attempt first.
    op.create_index(
        "ix_integration_jobs_status_last_attempted_at",
        "integration_jobs",
        ["status", "last_attempted_at"],
    )


def _create_document_packs() -> None:
    op.create_table(
        "document_packs",
        sa.Column("id", GUID, nullable=False),
        sa.Column("transaction_id", GUID, nullable=False),
        sa.Column("pack_type", sa.String(length=24), nullable=False),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("storage_ref", sa.String(length=512), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "source_document_ids", JSONB_TYPE, nullable=False, server_default=sa.text("'[]'")
        ),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dms_document_id", sa.String(length=255), nullable=True),
        sa.Column("dms_uploaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            f"pack_type IN ({sql_in_list(DOCUMENT_PACK_TYPES)})",
            name=op.f("ck_document_packs_document_pack_type_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["trade_transactions.id"],
            name=op.f("fk_document_packs_transaction_id_trade_transactions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_packs")),
        sa.UniqueConstraint(
            "transaction_id", "pack_type", name="uq_document_packs_transaction_pack_type"
        ),
    )
    op.create_index(op.f("ix_document_packs_transaction_id"), "document_packs", ["transaction_id"])
    op.create_index(op.f("ix_document_packs_pack_type"), "document_packs", ["pack_type"])


def upgrade() -> None:
    _widen_transaction_statuses(TRANSACTION_STATUSES)
    _create_integration_jobs()
    _create_document_packs()


def downgrade() -> None:
    op.drop_table("document_packs")
    op.drop_index("ix_integration_jobs_status_last_attempted_at", table_name="integration_jobs")
    op.drop_table("integration_jobs")
    # Anything the earlier vocabulary cannot express goes back to the last state it could, so the
    # narrowed constraint can be restored against real rows rather than failing on them.
    op.execute(
        "UPDATE trade_transactions SET status = 'approved' "
        "WHERE status IN ('integration_pending', 'committed', 'closed')"
    )
    _widen_transaction_statuses(PREVIOUS_TRANSACTION_STATUSES)

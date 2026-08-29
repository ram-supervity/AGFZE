"""initial schema

Revision ID: 20250101_000001
Revises:
Create Date: 2025-01-01 00:00:01.000000+00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20250101_000001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirrors app/db/types.py: PostgreSQL gets its native types, every other dialect (the disposable
# SQLite test database) falls back to JSON so this migration is the single source of schema truth.
GUID = sa.Uuid(as_uuid=True)
JSONB_TYPE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
STRING_ARRAY_TYPE = sa.JSON().with_variant(postgresql.ARRAY(sa.String(64)), "postgresql")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", GUID, nullable=False),
        sa.Column("subject_id", sa.String(length=255), nullable=False),
        sa.Column("entra_object_id", sa.String(length=255), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("roles", STRING_ARRAY_TYPE, nullable=False),
        sa.Column("default_stream_filter", sa.String(length=64), nullable=True),
        sa.Column("notification_channel", sa.String(length=32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_index(op.f("ix_users_subject_id"), "users", ["subject_id"], unique=True)
    op.create_index(op.f("ix_users_entra_object_id"), "users", ["entra_object_id"], unique=True)
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_index(op.f("ix_users_last_login_at"), "users", ["last_login_at"])

    op.create_table(
        "audit_events",
        sa.Column("id", GUID, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", GUID, nullable=True),
        sa.Column("actor_type", sa.String(length=16), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("entity_type", sa.String(length=128), nullable=False),
        sa.Column("entity_id", sa.String(length=128), nullable=True),
        sa.Column("metadata", JSONB_TYPE, nullable=False),
        sa.CheckConstraint(
            "actor_type IN ('user', 'system', 'agent')",
            name=op.f("ck_audit_events_actor_type_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name=op.f("fk_audit_events_actor_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )
    op.create_index(op.f("ix_audit_events_occurred_at"), "audit_events", ["occurred_at"])
    op.create_index(op.f("ix_audit_events_actor_id"), "audit_events", ["actor_id"])
    op.create_index(op.f("ix_audit_events_event_type"), "audit_events", ["event_type"])
    op.create_index(op.f("ix_audit_events_entity_type"), "audit_events", ["entity_type"])
    op.create_index(op.f("ix_audit_events_entity_id"), "audit_events", ["entity_id"])
    op.create_index("ix_audit_events_entity", "audit_events", ["entity_type", "entity_id"])

    op.create_table(
        "background_jobs",
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
            "progress >= 0 AND progress <= 100", name=op.f("ck_background_jobs_progress_range")
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'processing', 'completed', 'failed')",
            name=op.f("ck_background_jobs_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_background_jobs_created_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_background_jobs")),
    )
    op.create_index(op.f("ix_background_jobs_job_type"), "background_jobs", ["job_type"])
    op.create_index(op.f("ix_background_jobs_status"), "background_jobs", ["status"])
    op.create_index(
        op.f("ix_background_jobs_transaction_id"), "background_jobs", ["transaction_id"]
    )
    op.create_index(op.f("ix_background_jobs_created_by_id"), "background_jobs", ["created_by_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_background_jobs_created_by_id"), table_name="background_jobs")
    op.drop_index(op.f("ix_background_jobs_transaction_id"), table_name="background_jobs")
    op.drop_index(op.f("ix_background_jobs_status"), table_name="background_jobs")
    op.drop_index(op.f("ix_background_jobs_job_type"), table_name="background_jobs")
    op.drop_table("background_jobs")

    op.drop_index("ix_audit_events_entity", table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_entity_id"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_entity_type"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_event_type"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_actor_id"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_occurred_at"), table_name="audit_events")
    op.drop_table("audit_events")

    op.drop_index(op.f("ix_users_last_login_at"), table_name="users")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_index(op.f("ix_users_entra_object_id"), table_name="users")
    op.drop_index(op.f("ix_users_subject_id"), table_name="users")
    op.drop_table("users")

"""the reports table

Revision ID: 20250801_000008
Revises: 20250701_000007
Create Date: 2025-08-01 00:00:08.000000+00:00

Additive only, and genuinely so: one new table and not one alteration to anything built in 
1-7. No previously-deferred foreign key needs upgrading here either - nothing built earlier held
a reference to a report waiting for a table to exist - and no seed data is needed, because the
report templates are shipped in code as a configuration structure rather than as rows, exactly as
the sales document templates already are.

That is the whole shape of this  at the database layer, and it is the point: the dashboard,
the analytics page and every figure in a generated report are computed from the tables the
previous already write. Nothing here stores a metric, a rollup, a daily total or any
other copy of a figure that lives somewhere else, because a stored aggregate is a figure that can
disagree with the transaction of record.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.models.reporting import REPORT_FORMATS, REPORT_STREAMS, REPORT_TYPES

revision: str = "20250801_000008"
down_revision: str | None = "20250701_000007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GUID = sa.Uuid(as_uuid=True)
JSONB_TYPE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.create_table(
        "reports",
        sa.Column("id", GUID, primary_key=True),
        sa.Column("report_type", sa.String(16), nullable=False),
        sa.Column("output_format", sa.String(8), nullable=False),
        sa.Column("template_key", sa.String(48), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stream", sa.String(8), nullable=False, server_default="both"),
        sa.Column("status_filter", sa.String(32)),
        sa.Column("storage_ref", sa.String(512), nullable=False),
        sa.Column("byte_size", sa.Integer()),
        sa.Column("generation_reference", sa.String(48), nullable=False),
        sa.Column("parameters", JSONB_TYPE, nullable=False),
        sa.Column("content", JSONB_TYPE, nullable=False),
        sa.Column(
            "generated_by_id",
            GUID,
            sa.ForeignKey("users.id", ondelete="SET NULL", name="fk_reports_generated_by_id_users"),
        ),
        sa.Column(
            "audit_event_id",
            GUID,
            sa.ForeignKey(
                "audit_events.id",
                ondelete="SET NULL",
                name="fk_reports_audit_event_id_audit_events",
            ),
        ),
        sa.Column("ai_summary_error", sa.String(64)),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            f"report_type IN ({_in_list(REPORT_TYPES)})", name="ck_reports_report_type_valid"
        ),
        sa.CheckConstraint(
            f"output_format IN ({_in_list(REPORT_FORMATS)})", name="ck_reports_report_format_valid"
        ),
        sa.CheckConstraint(
            f"stream IN ({_in_list(REPORT_STREAMS)})", name="ck_reports_report_stream_valid"
        ),
        sa.CheckConstraint("period_end >= period_start", name="ck_reports_report_period_ordered"),
    )
    op.create_index("ix_reports_report_type", "reports", ["report_type"])
    op.create_index("ix_reports_output_format", "reports", ["output_format"])
    op.create_index("ix_reports_template_key", "reports", ["template_key"])
    op.create_index("ix_reports_period_start", "reports", ["period_start"])
    op.create_index("ix_reports_period_end", "reports", ["period_end"])
    op.create_index("ix_reports_stream", "reports", ["stream"])
    op.create_index("ix_reports_generated_by_id", "reports", ["generated_by_id"])
    op.create_index("ix_reports_audit_event_id", "reports", ["audit_event_id"])
    op.create_index("ix_reports_generated_at", "reports", ["generated_at"])
    # Unique, because the reference printed inside a rendered document has to resolve to exactly
    # one generation. Two rows sharing one would make a figure on paper unattributable.
    op.create_index(
        "ix_reports_generation_reference", "reports", ["generation_reference"], unique=True
    )
    op.create_index("ix_reports_type_generated_at", "reports", ["report_type", "generated_at"])


def downgrade() -> None:
    op.drop_index("ix_reports_type_generated_at", table_name="reports")
    op.drop_index("ix_reports_generation_reference", table_name="reports")
    op.drop_index("ix_reports_generated_at", table_name="reports")
    op.drop_index("ix_reports_audit_event_id", table_name="reports")
    op.drop_index("ix_reports_generated_by_id", table_name="reports")
    op.drop_index("ix_reports_stream", table_name="reports")
    op.drop_index("ix_reports_period_end", table_name="reports")
    op.drop_index("ix_reports_period_start", table_name="reports")
    op.drop_index("ix_reports_template_key", table_name="reports")
    op.drop_index("ix_reports_output_format", table_name="reports")
    op.drop_index("ix_reports_report_type", table_name="reports")
    op.drop_table("reports")

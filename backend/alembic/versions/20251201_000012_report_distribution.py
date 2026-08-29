"""Configured distribution for the two scheduled reports

Revision ID: 20251201_000012
Revises: 20251101_000011
Create Date: 2025-12-01 00:00:12.000000+00:00

One table, and no seed rows at all.

The empty table is the point. Before this migration a scheduled report reached nobody because the
platform had no way to send it; after it, a scheduled report still reaches nobody until an
administrator says who should receive it and why. That is the same posture every other
configuration on this platform takes - a threshold nobody set does not quietly default to a number
somebody might disagree with - and it means this migration cannot, on its own, cause a single
message to be sent to a single person.

`adhoc` is absent from the report-type check constraint deliberately. An ad-hoc report's requester
is already watching the job-progress indicator that produced it, and the constraint is what makes
"ad-hoc reports are not distributed" a property of the schema rather than a filter somebody could
later drop from a query.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20251201_000012"
down_revision: str | None = "20251101_000011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GUID = sa.Uuid(as_uuid=True)
JSONB_TYPE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "report_distribution_rules",
        sa.Column("id", GUID, primary_key=True),
        sa.Column("report_type", sa.String(16), nullable=False),
        sa.Column("recipient_roles", JSONB_TYPE, nullable=False),
        sa.Column("recipient_user_ids", JSONB_TYPE, nullable=False),
        sa.Column("channel", sa.String(16), nullable=False, server_default="in_app"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("change_reason", sa.Text(), nullable=False),
        sa.Column(
            "changed_by_id",
            GUID,
            sa.ForeignKey(
                "users.id",
                ondelete="SET NULL",
                name="fk_report_distribution_rules_changed_by_id_users",
            ),
        ),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "report_type IN ('daily', 'monthly')",
            name="report_distribution_type_valid",
        ),
        sa.CheckConstraint(
            "channel IN ('in_app', 'email', 'both')",
            name="report_distribution_channel_valid",
        ),
    )
    op.create_index(
        "ix_report_distribution_rules_report_type",
        "report_distribution_rules",
        ["report_type"],
    )
    op.create_index(
        "ix_report_distribution_rules_is_active",
        "report_distribution_rules",
        ["is_active"],
    )
    op.create_index(
        "ix_report_distribution_rules_changed_by_id",
        "report_distribution_rules",
        ["changed_by_id"],
    )
    op.create_index(
        "ix_report_distribution_rules_created_at",
        "report_distribution_rules",
        ["created_at"],
    )
    op.create_index(
        "ix_report_distribution_rules_type_active",
        "report_distribution_rules",
        ["report_type", "is_active"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_report_distribution_rules_type_active", table_name="report_distribution_rules"
    )
    op.drop_index("ix_report_distribution_rules_created_at", table_name="report_distribution_rules")
    op.drop_index(
        "ix_report_distribution_rules_changed_by_id", table_name="report_distribution_rules"
    )
    op.drop_index("ix_report_distribution_rules_is_active", table_name="report_distribution_rules")
    op.drop_index(
        "ix_report_distribution_rules_report_type", table_name="report_distribution_rules"
    )
    op.drop_table("report_distribution_rules")

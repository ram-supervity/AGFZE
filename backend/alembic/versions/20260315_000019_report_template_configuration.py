"""Report structure as configuration, seeded with the three shipped templates

Revision ID: 20260315_000019
Revises: 20260301_000018
Create Date: 2026-03-15 00:00:19.000000+00:00

One table, three rows, and no change to a single report's output.

The reporting module was always built against a template rather than against hard-coded layouts -
the PDF and XLSX renderers switch on a section's declared kind and on nothing else, and neither
one has ever known a section's name. What was missing was the last step of that promise: the
structures themselves lived in a Python module, so confirming a report's shape with AGFZE meant a
release rather than an edit.

This migration moves them into a table an administrator edits, and seeds it with the three
structures exactly as they shipped. That is the point of seeding rather than starting empty: at
cutover every report generates byte-identically to the day before, and the first thing that
changes is the first thing somebody deliberately changes - with a stated reason, on the audit
trail, like every other configuration on this platform.

`change_reason` is NOT NULL from the outset and the seed rows carry a real one. A row that arrived
without a reason would make the very first thing this table records an exception to its own rule.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import asdict
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.services.analytics.report_templates import TEMPLATES

revision: str = "20260315_000019"
down_revision: str | None = "20260301_000018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GUID = sa.Uuid(as_uuid=True)
JSONB_TYPE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")

SEED_REASON = (
    "Seeded with the platform: the report structure exactly as it shipped, so nothing about any "
    "report changes until somebody edits it here."
)


def upgrade() -> None:
    op.create_table(
        "report_template_configurations",
        sa.Column("id", GUID, primary_key=True),
        sa.Column("template_key", sa.String(48), nullable=False),
        sa.Column("report_type", sa.String(16), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("sections", JSONB_TYPE, nullable=False),
        sa.Column("disclosures", JSONB_TYPE, nullable=False),
        sa.Column("wants_ai_summary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("include_detail_rows", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("default_period_days", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("change_reason", sa.Text(), nullable=False),
        sa.Column(
            "changed_by_id",
            GUID,
            sa.ForeignKey(
                "users.id",
                ondelete="SET NULL",
                name="fk_report_template_configurations_changed_by_id_users",
            ),
        ),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "report_type IN ('daily', 'monthly', 'adhoc')",
            name="report_template_type_valid",
        ),
        sa.UniqueConstraint("report_type", name="uq_report_template_configurations_report_type"),
    )
    # A unique *index* rather than a unique constraint, because that is what
    # `mapped_column(unique=True, index=True)` renders to on the model. Two spellings of the same
    # guarantee would leave `alembic check` reporting a difference on every run forever.
    op.create_index(
        "ix_report_template_configurations_template_key",
        "report_template_configurations",
        ["template_key"],
        unique=True,
    )
    op.create_index(
        "ix_report_template_configurations_report_type",
        "report_template_configurations",
        ["report_type"],
    )
    op.create_index(
        "ix_report_template_configurations_changed_by_id",
        "report_template_configurations",
        ["changed_by_id"],
    )
    op.create_index(
        "ix_report_template_configurations_created_at",
        "report_template_configurations",
        ["created_at"],
    )

    now = datetime.now(timezone.utc)
    op.bulk_insert(
        sa.table(
            "report_template_configurations",
            sa.column("id", GUID),
            sa.column("template_key", sa.String),
            sa.column("report_type", sa.String),
            sa.column("title", sa.String),
            sa.column("description", sa.Text),
            sa.column("sections", JSONB_TYPE),
            sa.column("disclosures", JSONB_TYPE),
            sa.column("wants_ai_summary", sa.Boolean),
            sa.column("include_detail_rows", sa.Boolean),
            sa.column("default_period_days", sa.Integer),
            sa.column("change_reason", sa.Text),
            sa.column("changed_by_id", GUID),
            sa.column("changed_at", sa.DateTime(timezone=True)),
            sa.column("created_at", sa.DateTime(timezone=True)),
        ),
        [
            {
                "id": uuid.uuid4(),
                "template_key": template.key,
                "report_type": template.report_type,
                "title": template.title,
                "description": template.description,
                # Serialised straight off the shipped dataclasses, so the seed cannot drift from
                # what the module declares: a section retyped by hand here would be a second,
                # silently different structure.
                "sections": [
                    {**asdict(section), "figures": list(section.figures)}
                    for section in template.sections
                ],
                "disclosures": list(template.disclosures),
                "wants_ai_summary": template.wants_ai_summary,
                "include_detail_rows": template.include_detail_rows,
                "default_period_days": template.default_period_days,
                "change_reason": SEED_REASON,
                "changed_by_id": None,
                "changed_at": now,
                "created_at": now,
            }
            for template in TEMPLATES
        ],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_report_template_configurations_created_at",
        table_name="report_template_configurations",
    )
    op.drop_index(
        "ix_report_template_configurations_changed_by_id",
        table_name="report_template_configurations",
    )
    op.drop_index(
        "ix_report_template_configurations_report_type",
        table_name="report_template_configurations",
    )
    op.drop_index(
        "ix_report_template_configurations_template_key",
        table_name="report_template_configurations",
    )
    op.drop_table("report_template_configurations")

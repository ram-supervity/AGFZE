"""IV-01's threshold, and nothing else

Revision ID: 20251101_000011
Revises: 20251001_000010
Create Date: 2025-11-01 00:00:11.000000+00:00

The smallest migration in the build, and deliberately so. The hardening  adds exactly one
business rule, and a rule that reads its threshold out of `rule_configurations` needs one row -
no table, no column, no constraint and no change to anything eleven prior migrations wrote.

There is no `rule_exception_mappings` row here either, and its absence is the point. IV-01 is an
acknowledgeable flag rather than a hard failure, so it never reaches the hard-fail hook and never
opens an exception case. Giving it a category would create a queue entry for a policy AGFZE has
not confirmed, which is precisely the outcome the rule is written to avoid.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, timezone

import sqlalchemy as sa

from alembic import op
from app.services.rules.defaults import invoice_date_rule_configurations

revision: str = "20251101_000011"
down_revision: str | None = "20251001_000010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GUID = sa.Uuid(as_uuid=True)

RULE_CONFIGURATION_COLUMNS = (
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
)


def upgrade() -> None:
    now = datetime.now(timezone.utc)
    op.bulk_insert(
        sa.table("rule_configurations", *RULE_CONFIGURATION_COLUMNS),
        [
            {
                "id": uuid.uuid4(),
                **row,
                "changed_by_id": None,
                "changed_at": now,
                "created_at": now,
            }
            for row in invoice_date_rule_configurations()
        ],
    )


def downgrade() -> None:
    configurations = sa.table(
        "rule_configurations",
        sa.column("rule_id", sa.String),
        sa.column("check_key", sa.String),
    )
    for row in invoice_date_rule_configurations():
        op.execute(
            configurations.delete().where(
                configurations.c.rule_id == row["rule_id"],
                configurations.c.check_key == row["check_key"],
            )
        )

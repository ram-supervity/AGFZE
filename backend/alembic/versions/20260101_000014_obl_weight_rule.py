"""LG-01's threshold and its routing row

Revision ID: 20260101_000014
Revises: 20251215_000013
Create Date: 2026-01-01 00:00:14.000000+00:00

Two rows, and no schema change at all.

A rule with a threshold in `rule_configurations` and a category in `rule_exception_mappings` is the
whole of what adding a business rule to this platform costs. The orchestrator in `rules/engine.py`
and the exception hook in `governance/hooks.py` are untouched by this migration and by the
evaluator it seeds - neither of them learns that LG-01 exists, which is the property the mapping
table was built to have and the fourth rule in a row to demonstrate it.

The threshold's value is *not* confirmed by AGFZE. Discovery named the invoice-versus-bill-of-lading
weight difference as the trigger for a debit or a credit note and never named the difference that
triggers one, so 1% is this platform's own cautious starting point, chosen to sit below the 5%
BR-05 allows against the contract. The reason is written onto the row itself, as every seeded
threshold's is, so whoever reads it later can see it was chosen rather than confirmed.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, timezone

import sqlalchemy as sa

from alembic import op
from app.services.governance.categories import obl_weight_rule_exception_mappings
from app.services.rules.defaults import obl_weight_rule_configurations

revision: str = "20260101_000014"
down_revision: str | None = "20251215_000013"
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
            for row in obl_weight_rule_configurations()
        ],
    )
    op.bulk_insert(
        sa.table("rule_exception_mappings", *MAPPING_COLUMNS),
        [
            {"id": uuid.uuid4(), **row, "created_at": now}
            for row in obl_weight_rule_exception_mappings()
        ],
    )


def downgrade() -> None:
    mappings = sa.table(
        "rule_exception_mappings",
        sa.column("rule_id", sa.String),
        sa.column("check_key", sa.String),
    )
    for row in obl_weight_rule_exception_mappings():
        op.execute(
            mappings.delete().where(
                mappings.c.rule_id == row["rule_id"],
                mappings.c.check_key == row["check_key"],
            )
        )

    configurations = sa.table(
        "rule_configurations",
        sa.column("rule_id", sa.String),
        sa.column("check_key", sa.String),
    )
    for row in obl_weight_rule_configurations():
        op.execute(
            configurations.delete().where(
                configurations.c.rule_id == row["rule_id"],
                configurations.c.check_key == row["check_key"],
            )
        )

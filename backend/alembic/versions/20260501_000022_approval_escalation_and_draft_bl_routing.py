"""The second approval-ageing threshold, and BR-07's missing routing row

Revision ID: 20260501_000022
Revises: 20260415_000021
Create Date: 2026-05-01 00:00:22.000000+00:00

Two seeded rows. No schema change.

The first is the second tier of the approval clock. The platform has always had one threshold -
past it, an "approval not received" case is opened and the approving desk is told - and the
governing material asks for two: a turnaround time *per approval level*, with an approver who has
not acted on the reminder escalated past rather than reminded again. `approval_escalation_hours`
is that second level. It is seeded above the first (96 against 72) so the ordering holds on a
fresh install; both are ordinary configuration rows an administrator edits with a stated reason.

The second closes a real hole. BR-07's `final_bl_present` has routed to the sales desk since the
sales module shipped. Its sibling `draft_bl_present` - the same rule, the same document, the same
desk - never got a row, so every transaction failing it produced a blocking failure that no queue
owned and no notification reached, while the log quietly recorded `exception_mapping_missing`. An
exception without an accountable owner is precisely what the governance principles forbid.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, timezone

import sqlalchemy as sa

from alembic import op
from app.services.governance.categories import draft_bl_rule_exception_mapping
from app.services.governance.thresholds import GovernanceKey, GovernanceRule

revision: str = "20260501_000022"
down_revision: str | None = "20260415_000021"
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

ESCALATION_ROW = {
    "rule_id": GovernanceRule.APPROVALS,
    "check_key": GovernanceKey.APPROVAL_ESCALATION_HOURS,
    "scope_commodity_code": None,
    "scope_transaction_type": None,
    "scope_stream": None,
    "threshold_value": "96",
    "threshold_unit": "count",
    "description": (
        "Hours a transaction may wait on a decision before the 'approval not received' case "
        "already open against it is escalated. The second tier of the same clock: the first "
        "tells the approving desk, this one says the desk has not acted on being told."
    ),
    "is_active": True,
    "change_reason": (
        "Seeded with the second approval-ageing tier. The governing material asks for a "
        "turnaround time per approval level and for an absent approver to be escalated past "
        "rather than reminded indefinitely; one threshold could only ever do the first half."
    ),
}


def upgrade() -> None:
    now = datetime.now(timezone.utc)
    op.bulk_insert(
        sa.table("rule_configurations", *RULE_CONFIGURATION_COLUMNS),
        [
            {
                "id": uuid.uuid4(),
                **ESCALATION_ROW,
                "changed_by_id": None,
                "changed_at": now,
                "created_at": now,
            }
        ],
    )
    op.bulk_insert(
        sa.table("rule_exception_mappings", *MAPPING_COLUMNS),
        [
            {"id": uuid.uuid4(), **row, "created_at": now}
            for row in draft_bl_rule_exception_mapping()
        ],
    )


def downgrade() -> None:
    mappings = sa.table(
        "rule_exception_mappings",
        sa.column("rule_id", sa.String),
        sa.column("check_key", sa.String),
    )
    for row in draft_bl_rule_exception_mapping():
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
    op.execute(
        configurations.delete().where(
            configurations.c.rule_id == GovernanceRule.APPROVALS,
            configurations.c.check_key == GovernanceKey.APPROVAL_ESCALATION_HOURS,
        )
    )

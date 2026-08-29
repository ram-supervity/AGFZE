"""exception cases, approval tasks and the rule-to-exception mapping

Revision ID: 20250401_000004
Revises: 20250301_000003
Create Date: 2025-04-01 00:00:04.000000+00:00

Layered on the  schema. No previously-deferred foreign key needs upgrading here: nothing
built earlier held a reference to an approval or an exception waiting for a table to exist.

One existing table is altered, and only in one way: `trade_transactions.status` gains `approved`
as a permitted value. The check constraint is rebuilt through `batch_alter_table` with an
explicit `copy_from`, so the SQLite fallback the test suite can run on rebuilds the table from a
complete definition rather than from partial reflection, and PostgreSQL takes the plain ALTER
path - exactly as the  migration handled its own constrained columns.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.core.roles import ALL_ROLES
from app.models.enums import (
    APPROVAL_DECISIONS,
    BUSINESS_STREAMS,
    EXCEPTION_CATEGORIES,
    EXCEPTION_PRIORITIES,
    MATCH_METHODS,
    PRICE_BASES,
    TRANSACTION_STATUSES,
    TransactionStatus,
    sql_in_list,
)
from app.services.governance.categories import default_rule_exception_mappings
from app.services.governance.thresholds import default_governance_configurations

revision: str = "20250401_000004"
down_revision: str | None = "20250301_000003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GUID = sa.Uuid(as_uuid=True)
JSONB_TYPE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
QUANTITY = sa.Numeric(14, 3)
PERCENT = sa.Numeric(7, 4)

STATUS_CONSTRAINT = "ck_trade_transactions_trade_transaction_status_valid"

# The status vocabulary as it stood before this migration: everything except `approved`.
PREVIOUS_STATUSES = tuple(
    value for value in TRANSACTION_STATUSES if value != TransactionStatus.APPROVED.value
)


def _trade_transactions_table(*, statuses: tuple[str, ...]) -> sa.Table:
    """`trade_transactions` exactly as it stands, so a batch rebuild loses nothing.

    The status vocabulary is a parameter because that is the only thing this migration changes
    about the table: the upgrade rebuilds it from the old list and installs the new one, and the
    downgrade does the reverse.
    """
    metadata = sa.MetaData()
    table = sa.Table(
        "trade_transactions",
        metadata,
        sa.Column("id", GUID, nullable=False),
        sa.Column("transaction_code", sa.String(length=32), nullable=False),
        sa.Column("batch_number", sa.String(length=32), nullable=False),
        sa.Column("stream", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("commodity_code", sa.String(length=16), nullable=True),
        sa.Column("extracted_commodity_value", sa.String(length=128), nullable=True),
        sa.Column("commodity_needs_review", sa.Boolean(), nullable=False),
        sa.Column("quantity_mt", QUANTITY, nullable=True),
        sa.Column("price_basis", sa.String(length=16), nullable=True),
        sa.Column("lme_percentage", PERCENT, nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("request_id", GUID, nullable=False),
        sa.Column("match_method", sa.String(length=32), nullable=True),
        sa.Column("match_score", sa.Numeric(6, 2), nullable=True),
        sa.Column("match_rationale", sa.Text(), nullable=True),
        sa.Column("field_overrides", JSONB_TYPE, nullable=False),
        sa.Column("created_by_id", GUID, nullable=True),
        sa.Column("submitted_by_id", GUID, nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            f"stream IN ({sql_in_list(BUSINESS_STREAMS)})",
            name="ck_trade_transactions_trade_transaction_stream_valid",
        ),
        sa.CheckConstraint(
            f"status IN ({sql_in_list(statuses)})",
            name=STATUS_CONSTRAINT,
        ),
        sa.CheckConstraint(
            f"price_basis IS NULL OR price_basis IN ({sql_in_list(PRICE_BASES)})",
            name="ck_trade_transactions_trade_transaction_price_basis_valid",
        ),
        sa.CheckConstraint(
            f"match_method IS NULL OR match_method IN ({sql_in_list(MATCH_METHODS)})",
            name="ck_trade_transactions_trade_transaction_match_method_valid",
        ),
        sa.ForeignKeyConstraint(
            ["commodity_code"],
            ["commodity_codes.code"],
            name="fk_trade_transactions_commodity_code_commodity_codes",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["requests.id"],
            name="fk_trade_transactions_request_id_requests",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_trade_transactions_created_by_id_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by_id"],
            ["users.id"],
            name="fk_trade_transactions_submitted_by_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_trade_transactions"),
    )
    sa.Index("ix_trade_transactions_transaction_code", table.c.transaction_code, unique=True)
    sa.Index("ix_trade_transactions_batch_number", table.c.batch_number, unique=True)
    sa.Index("ix_trade_transactions_stream", table.c.stream)
    sa.Index("ix_trade_transactions_status", table.c.status)
    sa.Index("ix_trade_transactions_commodity_code", table.c.commodity_code)
    sa.Index("ix_trade_transactions_commodity_needs_review", table.c.commodity_needs_review)
    sa.Index("ix_trade_transactions_price_basis", table.c.price_basis)
    sa.Index("ix_trade_transactions_request_id", table.c.request_id)
    sa.Index("ix_trade_transactions_match_method", table.c.match_method)
    sa.Index("ix_trade_transactions_created_by_id", table.c.created_by_id)
    sa.Index("ix_trade_transactions_submitted_by_id", table.c.submitted_by_id)
    sa.Index("ix_trade_transactions_submitted_at", table.c.submitted_at)
    sa.Index("ix_trade_transactions_created_at", table.c.created_at)
    sa.Index("ix_trade_transactions_stream_status", table.c.stream, table.c.status)
    sa.Index("ix_trade_transactions_status_created_at", table.c.status, table.c.created_at)
    return table


def _set_status_vocabulary(statuses: tuple[str, ...]) -> None:
    """Replace the status check constraint with one covering exactly `statuses`.

    Split by dialect rather than routed through `batch_alter_table`'s constraint operations,
    because those re-apply the metadata's `ck_` naming template to a name that already carries it
    and then look the constraint up under the doubled name. PostgreSQL takes two plain ALTERs;
    SQLite, which cannot alter a constraint at all, rebuilds the table from the full definition
    above with the new vocabulary already in it.
    """
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(
            "trade_transactions",
            copy_from=_trade_transactions_table(statuses=statuses),
            recreate="always",
        ):
            pass
        return

    op.execute(f'ALTER TABLE trade_transactions DROP CONSTRAINT "{STATUS_CONSTRAINT}"')
    op.execute(
        f'ALTER TABLE trade_transactions ADD CONSTRAINT "{STATUS_CONSTRAINT}" '
        f"CHECK (status IN ({sql_in_list(statuses)}))"
    )


def upgrade() -> None:
    _set_status_vocabulary(TRANSACTION_STATUSES)

    op.create_table(
        "rule_exception_mappings",
        sa.Column("id", GUID, nullable=False),
        sa.Column("rule_id", sa.String(length=8), nullable=False),
        sa.Column("check_key", sa.String(length=48), nullable=True),
        sa.Column("exception_type", sa.String(length=48), nullable=False),
        sa.Column("owner_role", sa.String(length=32), nullable=False),
        sa.Column("priority", sa.String(length=8), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            f"exception_type IN ({sql_in_list(EXCEPTION_CATEGORIES)})",
            name=op.f("ck_rule_exception_mappings_rule_exception_mapping_type_valid"),
        ),
        sa.CheckConstraint(
            f"owner_role IN ({sql_in_list(ALL_ROLES)})",
            name=op.f("ck_rule_exception_mappings_rule_exception_mapping_owner_role_valid"),
        ),
        sa.CheckConstraint(
            f"priority IN ({sql_in_list(EXCEPTION_PRIORITIES)})",
            name=op.f("ck_rule_exception_mappings_rule_exception_mapping_priority_valid"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rule_exception_mappings")),
        sa.UniqueConstraint("rule_id", "check_key", name="uq_rule_exception_mappings_rule_check"),
    )
    op.create_index(
        op.f("ix_rule_exception_mappings_rule_id"), "rule_exception_mappings", ["rule_id"]
    )
    op.create_index(
        op.f("ix_rule_exception_mappings_check_key"), "rule_exception_mappings", ["check_key"]
    )
    op.create_index(
        op.f("ix_rule_exception_mappings_exception_type"),
        "rule_exception_mappings",
        ["exception_type"],
    )
    op.create_index(
        op.f("ix_rule_exception_mappings_owner_role"), "rule_exception_mappings", ["owner_role"]
    )
    op.create_index(
        op.f("ix_rule_exception_mappings_is_active"), "rule_exception_mappings", ["is_active"]
    )

    op.create_table(
        "exception_cases",
        sa.Column("id", GUID, nullable=False),
        sa.Column("transaction_id", GUID, nullable=True),
        sa.Column("document_id", GUID, nullable=True),
        sa.Column("request_id", GUID, nullable=True),
        sa.Column("exception_type", sa.String(length=48), nullable=False),
        sa.Column("rule_id", sa.String(length=8), nullable=True),
        sa.Column("check_key", sa.String(length=48), nullable=True),
        sa.Column("owner_role", sa.String(length=32), nullable=False),
        sa.Column("assigned_to_id", GUID, nullable=True),
        sa.Column("priority", sa.String(length=8), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("field_name", sa.String(length=128), nullable=True),
        sa.Column("expected_value", sa.String(length=255), nullable=True),
        sa.Column("actual_value", sa.String(length=255), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by_id", GUID, nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("escalated", sa.Boolean(), nullable=False),
        sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("escalated_by_id", GUID, nullable=True),
        sa.Column("escalation_note", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            f"exception_type IN ({sql_in_list(EXCEPTION_CATEGORIES)})",
            name=op.f("ck_exception_cases_exception_case_type_valid"),
        ),
        sa.CheckConstraint(
            f"owner_role IN ({sql_in_list(ALL_ROLES)})",
            name=op.f("ck_exception_cases_exception_case_owner_role_valid"),
        ),
        sa.CheckConstraint(
            f"priority IN ({sql_in_list(EXCEPTION_PRIORITIES)})",
            name=op.f("ck_exception_cases_exception_case_priority_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["trade_transactions.id"],
            name=op.f("fk_exception_cases_transaction_id_trade_transactions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_exception_cases_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["requests.id"],
            name=op.f("fk_exception_cases_request_id_requests"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_to_id"],
            ["users.id"],
            name=op.f("fk_exception_cases_assigned_to_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by_id"],
            ["users.id"],
            name=op.f("fk_exception_cases_resolved_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["escalated_by_id"],
            ["users.id"],
            name=op.f("fk_exception_cases_escalated_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_exception_cases")),
    )
    op.create_index(
        op.f("ix_exception_cases_transaction_id"), "exception_cases", ["transaction_id"]
    )
    op.create_index(op.f("ix_exception_cases_document_id"), "exception_cases", ["document_id"])
    op.create_index(op.f("ix_exception_cases_request_id"), "exception_cases", ["request_id"])
    op.create_index(
        op.f("ix_exception_cases_exception_type"), "exception_cases", ["exception_type"]
    )
    op.create_index(op.f("ix_exception_cases_rule_id"), "exception_cases", ["rule_id"])
    op.create_index(op.f("ix_exception_cases_check_key"), "exception_cases", ["check_key"])
    op.create_index(op.f("ix_exception_cases_owner_role"), "exception_cases", ["owner_role"])
    op.create_index(
        op.f("ix_exception_cases_assigned_to_id"), "exception_cases", ["assigned_to_id"]
    )
    op.create_index(op.f("ix_exception_cases_priority"), "exception_cases", ["priority"])
    op.create_index(op.f("ix_exception_cases_opened_at"), "exception_cases", ["opened_at"])
    op.create_index(op.f("ix_exception_cases_resolved_at"), "exception_cases", ["resolved_at"])
    op.create_index(
        op.f("ix_exception_cases_resolved_by_id"), "exception_cases", ["resolved_by_id"]
    )
    op.create_index(op.f("ix_exception_cases_escalated"), "exception_cases", ["escalated"])
    op.create_index(
        op.f("ix_exception_cases_escalated_by_id"), "exception_cases", ["escalated_by_id"]
    )
    op.create_index(
        "ix_exception_cases_type_resolved_at",
        "exception_cases",
        ["exception_type", "resolved_at"],
    )
    op.create_index(
        "ix_exception_cases_owner_role_resolved_at",
        "exception_cases",
        ["owner_role", "resolved_at"],
    )

    op.create_table(
        "approval_tasks",
        sa.Column("id", GUID, nullable=False),
        sa.Column("transaction_id", GUID, nullable=False),
        sa.Column("approver_role", sa.String(length=32), nullable=False),
        sa.Column("assignee_id", GUID, nullable=True),
        sa.Column("requested_by_id", GUID, nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decision", sa.String(length=24), nullable=False),
        sa.Column("decided_by_id", GUID, nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("ai_summary", sa.Text(), nullable=True),
        sa.Column("ai_summary_generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ai_summary_error", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            f"decision IN ({sql_in_list(APPROVAL_DECISIONS)})",
            name=op.f("ck_approval_tasks_approval_task_decision_valid"),
        ),
        sa.CheckConstraint(
            f"approver_role IN ({sql_in_list(ALL_ROLES)})",
            name=op.f("ck_approval_tasks_approval_task_approver_role_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["trade_transactions.id"],
            name=op.f("fk_approval_tasks_transaction_id_trade_transactions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["assignee_id"],
            ["users.id"],
            name=op.f("fk_approval_tasks_assignee_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_id"],
            ["users.id"],
            name=op.f("fk_approval_tasks_requested_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_id"],
            ["users.id"],
            name=op.f("fk_approval_tasks_decided_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_approval_tasks")),
    )
    op.create_index(op.f("ix_approval_tasks_transaction_id"), "approval_tasks", ["transaction_id"])
    op.create_index(op.f("ix_approval_tasks_approver_role"), "approval_tasks", ["approver_role"])
    op.create_index(op.f("ix_approval_tasks_assignee_id"), "approval_tasks", ["assignee_id"])
    op.create_index(
        op.f("ix_approval_tasks_requested_by_id"), "approval_tasks", ["requested_by_id"]
    )
    op.create_index(op.f("ix_approval_tasks_requested_at"), "approval_tasks", ["requested_at"])
    op.create_index(op.f("ix_approval_tasks_decision"), "approval_tasks", ["decision"])
    op.create_index(op.f("ix_approval_tasks_decided_by_id"), "approval_tasks", ["decided_by_id"])
    op.create_index(op.f("ix_approval_tasks_decided_at"), "approval_tasks", ["decided_at"])
    op.create_index(
        "ix_approval_tasks_decision_requested_at",
        "approval_tasks",
        ["decision", "requested_at"],
    )

    # --- seed data ----------------------------------------------------------------------------
    now = datetime.now(timezone.utc)

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
        [
            {"id": uuid.uuid4(), **row, "created_at": now}
            for row in default_rule_exception_mappings()
        ],
    )

    # The governance thresholds live in the table the business rules already use, namespaced
    # GOV- so they are never mistaken for one.
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
            for row in default_governance_configurations()
        ],
    )


def downgrade() -> None:
    configurations = sa.table(
        "rule_configurations",
        sa.column("rule_id", sa.String),
    )
    op.execute(
        configurations.delete().where(
            configurations.c.rule_id.in_(
                sorted({row["rule_id"] for row in default_governance_configurations()})
            )
        )
    )

    op.drop_index("ix_approval_tasks_decision_requested_at", table_name="approval_tasks")
    op.drop_index(op.f("ix_approval_tasks_decided_at"), table_name="approval_tasks")
    op.drop_index(op.f("ix_approval_tasks_decided_by_id"), table_name="approval_tasks")
    op.drop_index(op.f("ix_approval_tasks_decision"), table_name="approval_tasks")
    op.drop_index(op.f("ix_approval_tasks_requested_at"), table_name="approval_tasks")
    op.drop_index(op.f("ix_approval_tasks_requested_by_id"), table_name="approval_tasks")
    op.drop_index(op.f("ix_approval_tasks_assignee_id"), table_name="approval_tasks")
    op.drop_index(op.f("ix_approval_tasks_approver_role"), table_name="approval_tasks")
    op.drop_index(op.f("ix_approval_tasks_transaction_id"), table_name="approval_tasks")
    op.drop_table("approval_tasks")

    op.drop_index("ix_exception_cases_owner_role_resolved_at", table_name="exception_cases")
    op.drop_index("ix_exception_cases_type_resolved_at", table_name="exception_cases")
    op.drop_index(op.f("ix_exception_cases_escalated_by_id"), table_name="exception_cases")
    op.drop_index(op.f("ix_exception_cases_escalated"), table_name="exception_cases")
    op.drop_index(op.f("ix_exception_cases_resolved_by_id"), table_name="exception_cases")
    op.drop_index(op.f("ix_exception_cases_resolved_at"), table_name="exception_cases")
    op.drop_index(op.f("ix_exception_cases_opened_at"), table_name="exception_cases")
    op.drop_index(op.f("ix_exception_cases_priority"), table_name="exception_cases")
    op.drop_index(op.f("ix_exception_cases_assigned_to_id"), table_name="exception_cases")
    op.drop_index(op.f("ix_exception_cases_owner_role"), table_name="exception_cases")
    op.drop_index(op.f("ix_exception_cases_check_key"), table_name="exception_cases")
    op.drop_index(op.f("ix_exception_cases_rule_id"), table_name="exception_cases")
    op.drop_index(op.f("ix_exception_cases_exception_type"), table_name="exception_cases")
    op.drop_index(op.f("ix_exception_cases_request_id"), table_name="exception_cases")
    op.drop_index(op.f("ix_exception_cases_document_id"), table_name="exception_cases")
    op.drop_index(op.f("ix_exception_cases_transaction_id"), table_name="exception_cases")
    op.drop_table("exception_cases")

    op.drop_index(
        op.f("ix_rule_exception_mappings_is_active"), table_name="rule_exception_mappings"
    )
    op.drop_index(
        op.f("ix_rule_exception_mappings_owner_role"), table_name="rule_exception_mappings"
    )
    op.drop_index(
        op.f("ix_rule_exception_mappings_exception_type"), table_name="rule_exception_mappings"
    )
    op.drop_index(
        op.f("ix_rule_exception_mappings_check_key"), table_name="rule_exception_mappings"
    )
    op.drop_index(op.f("ix_rule_exception_mappings_rule_id"), table_name="rule_exception_mappings")
    op.drop_table("rule_exception_mappings")

    # Any transaction that reached `Approved` goes back to the last state the old vocabulary
    # knew, so the narrowed constraint can be reinstated without rejecting a live row.
    transactions = sa.table(
        "trade_transactions",
        sa.column("status", sa.String),
    )
    op.execute(
        transactions.update()
        .where(transactions.c.status == TransactionStatus.APPROVED.value)
        .values(status=TransactionStatus.APPROVAL_PENDING.value)
    )
    _set_status_vocabulary(PREVIOUS_STATUSES)

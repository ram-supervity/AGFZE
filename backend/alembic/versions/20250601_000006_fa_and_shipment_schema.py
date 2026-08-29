"""the FA leg, containers, shipments, bills of lading and shipment issues

Revision ID: 20250601_000006
Revises: 20250501_000005
Create Date: 2025-06-01 00:00:06.000000+00:00

Layered on the Step 5 schema. Five tables are added and **no existing table is altered at all** -
not `trade_transactions`, not `documents`, not `rule_configurations`. That is worth stating
plainly, because it is the claim the last three steps have each been making about the design:
`fa_legs` attaches through its own one-to-one foreign key exactly as `sales_legs` did, and
`containers` and `shipments` attach through their own many-to-one keys, so the parent record is
untouched for the third time running.

No previously-deferred foreign key needs upgrading here either. Nothing built earlier held a
reference to a container, a shipment or an FA leg waiting for a table to exist.

The seed data is the other half of the step. The `fa_document` schema Step 2 anticipated as a
`document_type` value and never gave a field list finally gets one - seven fields, exactly the
minimal set AGFZE's material names and nothing beyond it. The FA-scoped rule configurations sit
beside the unscoped platform defaults rather than replacing them, so FA can be given a figure of
its own the day the business decides one. And BR-03's threshold and mapping row make a rule that
has been registered-but-dormant since Step 3 real.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.models.enums import (
    BILL_OF_LADING_TYPES,
    SHIPMENT_ISSUE_TYPES,
    SHIPMENT_MILESTONES,
    SHIPMENT_STATUSES,
    ShipmentStatus,
    sql_in_list,
)
from app.services.governance.categories import shipment_rule_exception_mappings
from app.services.governance.thresholds import shipment_governance_configurations
from app.services.rules.defaults import (
    fa_rule_configurations,
    shipment_rule_configurations,
)
from app.services.schema_defaults import SEED_CHANGE_REASON, fa_schema_rows

revision: str = "20250601_000006"
down_revision: str | None = "20250501_000005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GUID = sa.Uuid(as_uuid=True)
JSONB_TYPE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
QUANTITY = sa.Numeric(14, 3)

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


def _create_fa_legs() -> None:
    op.create_table(
        "fa_legs",
        sa.Column("id", GUID, nullable=False),
        sa.Column("transaction_id", GUID, nullable=False),
        sa.Column("counterparty_name", sa.String(length=255), nullable=True),
        sa.Column("fa_contract_reference", sa.String(length=64), nullable=True),
        sa.Column("document_type", sa.String(length=64), nullable=True),
        sa.Column("extra_fields", JSONB_TYPE, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["trade_transactions.id"],
            name=op.f("fk_fa_legs_transaction_id_trade_transactions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fa_legs")),
    )
    # Unique, which is what makes the relationship one-to-one and stops a second FA leg being
    # attached to a transaction that already carries one - the same guarantee `sales_legs` has.
    op.create_index(op.f("ix_fa_legs_transaction_id"), "fa_legs", ["transaction_id"], unique=True)
    op.create_index(op.f("ix_fa_legs_counterparty_name"), "fa_legs", ["counterparty_name"])
    op.create_index(op.f("ix_fa_legs_fa_contract_reference"), "fa_legs", ["fa_contract_reference"])
    op.create_index(op.f("ix_fa_legs_document_type"), "fa_legs", ["document_type"])


def _create_containers() -> None:
    op.create_table(
        "containers",
        sa.Column("id", GUID, nullable=False),
        sa.Column("transaction_id", GUID, nullable=False),
        sa.Column("container_number", sa.String(length=32), nullable=False),
        sa.Column("seal_number", sa.String(length=32), nullable=True),
        sa.Column("quantity_mt", QUANTITY, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["trade_transactions.id"],
            name=op.f("fk_containers_transaction_id_trade_transactions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_containers")),
        # Unique per transaction, never globally. A container legitimately appears on two
        # transactions in the real world when something has gone wrong, and BR-03 is what has to
        # report that - a database constraint would instead reject the document that revealed it.
        sa.UniqueConstraint(
            "transaction_id",
            "container_number",
            name=op.f("uq_containers_transaction_id"),
        ),
    )
    op.create_index(op.f("ix_containers_transaction_id"), "containers", ["transaction_id"])
    # BR-03's match key, and the reason it can ask its question without a table scan.
    op.create_index(op.f("ix_containers_container_number"), "containers", ["container_number"])


def _create_shipments() -> None:
    op.create_table(
        "shipments",
        sa.Column("id", GUID, nullable=False),
        sa.Column("transaction_id", GUID, nullable=False),
        sa.Column("container_id", GUID, nullable=True),
        sa.Column("bl_number", sa.String(length=64), nullable=True),
        sa.Column("carrier", sa.String(length=128), nullable=True),
        sa.Column("vessel", sa.String(length=128), nullable=True),
        sa.Column("port_of_loading", sa.String(length=128), nullable=True),
        sa.Column("port_of_discharge", sa.String(length=128), nullable=True),
        sa.Column("etd", sa.Date(), nullable=True),
        sa.Column("eta", sa.Date(), nullable=True),
        sa.Column("current_milestone", sa.String(length=24), nullable=True),
        # Server defaults on the columns a row must have but the ORM fills in Python, so a row
        # inserted by a fixture or by hand cannot violate NOT NULL.
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=ShipmentStatus.ON_SCHEDULE.value,
        ),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_checked_source", sa.String(length=64), nullable=True),
        sa.Column(
            "consecutive_failures", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("review_flagged", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("review_reason", sa.Text(), nullable=True),
        sa.Column("review_flagged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            f"status IN ({sql_in_list(SHIPMENT_STATUSES)})",
            name=op.f("ck_shipments_shipment_status_valid"),
        ),
        sa.CheckConstraint(
            "current_milestone IS NULL OR current_milestone IN "
            f"({sql_in_list(SHIPMENT_MILESTONES)})",
            name=op.f("ck_shipments_shipment_milestone_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["trade_transactions.id"],
            name=op.f("fk_shipments_transaction_id_trade_transactions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["container_id"],
            ["containers.id"],
            name=op.f("fk_shipments_container_id_containers"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shipments")),
    )
    op.create_index(op.f("ix_shipments_transaction_id"), "shipments", ["transaction_id"])
    op.create_index(op.f("ix_shipments_container_id"), "shipments", ["container_id"])
    op.create_index(op.f("ix_shipments_bl_number"), "shipments", ["bl_number"])
    op.create_index(op.f("ix_shipments_carrier"), "shipments", ["carrier"])
    op.create_index(op.f("ix_shipments_port_of_loading"), "shipments", ["port_of_loading"])
    op.create_index(op.f("ix_shipments_port_of_discharge"), "shipments", ["port_of_discharge"])
    op.create_index(op.f("ix_shipments_eta"), "shipments", ["eta"])
    op.create_index(op.f("ix_shipments_current_milestone"), "shipments", ["current_milestone"])
    op.create_index(op.f("ix_shipments_status"), "shipments", ["status"])
    op.create_index(op.f("ix_shipments_last_checked_at"), "shipments", ["last_checked_at"])
    op.create_index(op.f("ix_shipments_review_flagged"), "shipments", ["review_flagged"])
    op.create_index(op.f("ix_shipments_created_at"), "shipments", ["created_at"])
    # The staleness sweep's own index: the shipments still moving, oldest check first.
    op.create_index(
        "ix_shipments_status_last_checked_at", "shipments", ["status", "last_checked_at"]
    )


def _create_bills_of_lading() -> None:
    op.create_table(
        "bills_of_lading",
        sa.Column("id", GUID, nullable=False),
        sa.Column("shipment_id", GUID, nullable=False),
        sa.Column("bl_type", sa.String(length=16), nullable=False),
        sa.Column("bl_number", sa.String(length=64), nullable=True),
        sa.Column("is_original_received", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("document_id", GUID, nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            f"bl_type IN ({sql_in_list(BILL_OF_LADING_TYPES)})",
            name=op.f("ck_bills_of_lading_bill_of_lading_type_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["shipment_id"],
            ["shipments.id"],
            name=op.f("fk_bills_of_lading_shipment_id_shipments"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_bills_of_lading_document_id_documents"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bills_of_lading")),
    )
    op.create_index(op.f("ix_bills_of_lading_shipment_id"), "bills_of_lading", ["shipment_id"])
    op.create_index(op.f("ix_bills_of_lading_bl_type"), "bills_of_lading", ["bl_type"])
    op.create_index(op.f("ix_bills_of_lading_bl_number"), "bills_of_lading", ["bl_number"])
    # The column BR-07's submission check now reads, indexed because it reads it on every run.
    op.create_index(
        op.f("ix_bills_of_lading_is_original_received"),
        "bills_of_lading",
        ["is_original_received"],
    )
    op.create_index(op.f("ix_bills_of_lading_document_id"), "bills_of_lading", ["document_id"])


def _create_shipment_issues() -> None:
    op.create_table(
        "shipment_issues",
        sa.Column("id", GUID, nullable=False),
        sa.Column("shipment_id", GUID, nullable=False),
        sa.Column("issue_type", sa.String(length=16), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("document_id", GUID, nullable=True),
        sa.Column("logged_by_id", GUID, nullable=True),
        sa.Column("logged_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            f"issue_type IN ({sql_in_list(SHIPMENT_ISSUE_TYPES)})",
            name=op.f("ck_shipment_issues_shipment_issue_type_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["shipment_id"],
            ["shipments.id"],
            name=op.f("fk_shipment_issues_shipment_id_shipments"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_shipment_issues_document_id_documents"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["logged_by_id"],
            ["users.id"],
            name=op.f("fk_shipment_issues_logged_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shipment_issues")),
    )
    op.create_index(op.f("ix_shipment_issues_shipment_id"), "shipment_issues", ["shipment_id"])
    op.create_index(op.f("ix_shipment_issues_issue_type"), "shipment_issues", ["issue_type"])
    op.create_index(op.f("ix_shipment_issues_document_id"), "shipment_issues", ["document_id"])
    op.create_index(op.f("ix_shipment_issues_logged_by_id"), "shipment_issues", ["logged_by_id"])
    op.create_index(op.f("ix_shipment_issues_logged_at"), "shipment_issues", ["logged_at"])
    op.create_index(op.f("ix_shipment_issues_resolved_at"), "shipment_issues", ["resolved_at"])


def upgrade() -> None:
    _create_fa_legs()
    _create_containers()
    _create_shipments()
    _create_bills_of_lading()
    _create_shipment_issues()

    now = datetime.now(timezone.utc)

    # The `fa_document` extraction schema. Step 2 declared the document type and deliberately
    # never gave it a field list; this is that field list, and it is exactly the minimal set
    # AGFZE's material names. Nothing has been added to round it out.
    op.bulk_insert(
        sa.table(
            "document_type_schemas",
            sa.column("id", GUID),
            sa.column("document_type", sa.String),
            sa.column("territory", sa.String),
            sa.column("field_schema", JSONB_TYPE),
            sa.column("mandatory_documents", JSONB_TYPE),
            sa.column("change_reason", sa.Text),
            sa.column("changed_by_id", GUID),
            sa.column("changed_at", sa.DateTime(timezone=True)),
            sa.column("created_at", sa.DateTime(timezone=True)),
        ),
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
            for row in fa_schema_rows()
        ],
    )

    # FA's own tolerances, BR-03's threshold and the shipment module's governance figures - all
    # into the one table every threshold in the platform already lives in.
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
            for row in (
                *fa_rule_configurations(),
                *shipment_rule_configurations(),
                *shipment_governance_configurations(),
            )
        ],
    )

    # One row, and the whole of what routing BR-03's failures required. No branch was added to
    # the exception hook, and none to the rule orchestrator.
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
            for row in shipment_rule_exception_mappings()
        ],
    )


def downgrade() -> None:
    mappings = sa.table(
        "rule_exception_mappings",
        sa.column("rule_id", sa.String),
        sa.column("check_key", sa.String),
    )
    for row in shipment_rule_exception_mappings():
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
        sa.column("scope_stream", sa.String),
    )
    # Removed by exact scope, so the FA-scoped rows go and the unscoped platform defaults that
    # share their rule and check keys stay exactly where they are.
    for row in fa_rule_configurations():
        op.execute(
            configurations.delete().where(
                configurations.c.rule_id == row["rule_id"],
                configurations.c.check_key == row["check_key"],
                configurations.c.scope_stream == row["scope_stream"],
            )
        )
    for row in (*shipment_rule_configurations(), *shipment_governance_configurations()):
        op.execute(
            configurations.delete().where(
                configurations.c.rule_id == row["rule_id"],
                configurations.c.check_key == row["check_key"],
            )
        )

    schemas = sa.table("document_type_schemas", sa.column("document_type", sa.String))
    op.execute(
        schemas.delete().where(
            schemas.c.document_type.in_(sorted({row["document_type"] for row in fa_schema_rows()}))
        )
    )

    op.drop_table("shipment_issues")
    op.drop_table("bills_of_lading")
    op.drop_index("ix_shipments_status_last_checked_at", table_name="shipments")
    op.drop_table("shipments")
    op.drop_table("containers")
    op.drop_table("fa_legs")

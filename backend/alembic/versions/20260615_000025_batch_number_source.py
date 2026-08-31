"""Whether a batch number is the counterparty's own or a placeholder the platform allocated

Revision ID: 20260615_000025
Revises: 20260530_000024
Create Date: 2026-06-15 00:00:25.000000+00:00

One column, and it closes a defect that split a single deal in two.

A batch number is the identity of the physical cargo. Not every document states one - a purchase
contract quotes a contract number and nothing else - so a transaction opened by the first
document to arrive is given a number off the platform's own sequence to have an identity at all.
Until now nothing recorded that the number was a stand-in, so it never moved: the supplier's
invoice would fuzzy-match onto it and leave it alone, and the packing list behind it, matching
strictly on the batch number both documents actually quote, would find nothing and open a second
transaction for the same container. BR-03 then reported one container on two batches and blocked
a deal that was never really two.

With the source recorded, an allocated number is adopted onto the stated one the moment a
document carrying it is matched. A number that came off a document is authoritative and never
moves. `transaction_code` is untouched by any of it - that is the platform's permanent handle on
the row, and other systems have already been told it.

The backfill marks every existing transaction `document`, which is the conservative reading: it
leaves every number already in the table exactly where it is, and only transactions created after
this migration can be adopted.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260615_000025"
down_revision: str | None = "20260530_000024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "trade_transactions",
        sa.Column(
            "batch_number_source",
            sa.String(length=16),
            nullable=False,
            server_default="document",
        ),
    )
    with op.batch_alter_table("trade_transactions") as batch:
        batch.alter_column("batch_number_source", server_default=None)
        batch.create_check_constraint(
            "trade_transaction_batch_number_source_valid",
            "batch_number_source IN ('allocated', 'document')",
        )


def downgrade() -> None:
    with op.batch_alter_table("trade_transactions") as batch:
        batch.drop_constraint("trade_transaction_batch_number_source_valid", type_="check")
    op.drop_column("trade_transactions", "batch_number_source")

"""The B2B tag on a purchase leg, and deliberately nothing else about B2B

Revision ID: 20251215_000013
Revises: 20251201_000012
Create Date: 2025-12-15 00:00:13.000000+00:00

Two columns: whether a purchase is a joint B2B deal, and who the partner is.

What this migration does *not* add is the point of it. Discovery described a B2B model with a
negotiated profit split, shared expenses and a loss borne by one side - and gave illustrative
percentages (50/50, 60/40, 65/35) rather than a rule for choosing between them, no mechanism for
capturing a shared expense, and no definition of what a borne loss means operationally. Columns for
those would be a guess with a schema around it, and would have to be migrated a second time the day
somebody confirms the real shape. So this adds the half that was unambiguous - a deal can be
identified as B2B and filtered for - and leaves the arithmetic to a later migration written against
a confirmed specification.

`is_b2b` is NOT NULL with a server default of false because every existing purchase leg genuinely
is not a B2B deal: the platform had no way to record one until now, so false is the true value for
every row already in the table rather than a convenient fill.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20251215_000013"
down_revision: str | None = "20251201_000012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "purchase_legs",
        sa.Column("is_b2b", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("purchase_legs", sa.Column("b2b_partner_name", sa.String(255)))
    op.create_index("ix_purchase_legs_is_b2b", "purchase_legs", ["is_b2b"])


def downgrade() -> None:
    op.drop_index("ix_purchase_legs_is_b2b", table_name="purchase_legs")
    op.drop_column("purchase_legs", "b2b_partner_name")
    op.drop_column("purchase_legs", "is_b2b")

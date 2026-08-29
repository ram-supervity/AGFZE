"""The three-month LME quotation as a price basis in its own right

Revision ID: 20260301_000018
Revises: 20260215_000017
Create Date: 2026-03-01 00:00:18.000000+00:00

One widened check constraint, no new column and no seed row.

Discovery names three sales pricing mechanisms, not two: a locked price, a percentage of the LME
cash settlement, and a price struck against the three-month quotation taken ahead of ETD/ETA. Only
the first two were ever storable, so a three-month deal was recorded as whichever of them it most
resembled and the distinction was lost the moment it was written down.

There is deliberately no column here to hold an averaged figure, and no code anywhere that
computes one. Discovery is equally explicit that the exchange has no usable feed and that the
three-month price is entered by hand for the day, so this platform holds no daily series to
average. It records the basis and the percentage struck against it; the price itself lands in the
rate and fixation columns that already exist, entered by the person who read it off the source.

The constraint is only genuinely altered on PostgreSQL. Migrations 3 and 4 build it from the
`PriceBasis` enum itself, so any schema created from base - which is every SQLite database this
project ever makes, and every CI run - already carries the widened vocabulary before this
migration is reached. What needs the ALTER is a real deployment whose schema was built before the
enum grew, and those are PostgreSQL.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from app.models.enums import PRICE_BASES, sql_in_list

revision: str = "20260301_000018"
down_revision: str | None = "20260215_000017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT = "ck_trade_transactions_trade_transaction_price_basis_valid"

# The vocabulary as it stood before this migration, for the downgrade. Written out rather than
# derived from the enum, because the enum is exactly what this migration changes: deriving it
# would make the downgrade a no-op the day somebody adds a fourth basis.
PREVIOUS_PRICE_BASES: tuple[str, ...] = ("fixed", "lme_percent")


def _set_price_basis_vocabulary(bases: tuple[str, ...]) -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f'ALTER TABLE trade_transactions DROP CONSTRAINT IF EXISTS "{CONSTRAINT}"')
    op.execute(
        f'ALTER TABLE trade_transactions ADD CONSTRAINT "{CONSTRAINT}" '
        f"CHECK (price_basis IS NULL OR price_basis IN ({sql_in_list(bases)}))"
    )


def upgrade() -> None:
    _set_price_basis_vocabulary(tuple(PRICE_BASES))


def downgrade() -> None:
    # A transaction already recorded on the three-month basis would fail the narrower constraint,
    # so it is put back on the plain LME percentage first. That is where such a deal was recorded
    # before this migration existed, and the percentage it carries is unchanged either way.
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "UPDATE trade_transactions SET price_basis = 'lme_percent' "
            "WHERE price_basis = 'three_month_lme'"
        )
    _set_price_basis_vocabulary(PREVIOUS_PRICE_BASES)

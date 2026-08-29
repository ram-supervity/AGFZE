"""The hedging day's low and high exchange price

Revision ID: 20260201_000016
Revises: 20260115_000015
Create Date: 2026-02-01 00:00:16.000000+00:00

Two nullable columns on `purchase_legs`, and no rule behind them.

Discovery names a hedging *range* - the lowest and highest exchange price on the day a deal was
hedged - alongside the single `hedge_date`/`rate` the platform already recorded. It also names an
"LLME", the lowest LME, which is the low end of that same range rather than a third quantity; it is
`hedge_low_price` here rather than a second column holding the same number under another name.

Deliberately capture-and-display only. What counts as a tolerable position inside a day's range is
a commercial judgement nobody has stated, and a rule derived from these columns would be inventing
that judgement. Both are nullable because most deals are not LME-priced, and one that is may have
been hedged before anybody recorded where the market went.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260201_000016"
down_revision: str | None = "20260115_000015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MONEY = sa.Numeric(18, 4)


def upgrade() -> None:
    op.add_column("purchase_legs", sa.Column("hedge_low_price", MONEY))
    op.add_column("purchase_legs", sa.Column("hedge_high_price", MONEY))


def downgrade() -> None:
    op.drop_column("purchase_legs", "hedge_high_price")
    op.drop_column("purchase_legs", "hedge_low_price")

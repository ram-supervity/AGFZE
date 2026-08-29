"""Whether an account has seen the first-login walkthrough

Revision ID: 20260215_000017
Revises: 20260201_000016
Create Date: 2026-02-15 00:00:17.000000+00:00

One boolean, NOT NULL, defaulting false.

False is the true value for every row already in the table rather than a convenient fill: no
account has seen the walkthrough, because until now there was not one. That also means the first
sign-in after this deploys shows the tour to existing staff as well as to new joiners, which is the
correct behaviour - the screens it points at are new to them too.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260215_000017"
down_revision: str | None = "20260201_000016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "has_completed_onboarding", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "has_completed_onboarding")

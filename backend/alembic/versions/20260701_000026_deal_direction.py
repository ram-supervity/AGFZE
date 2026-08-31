"""Add deal direction detection columns to documents and requests

Revision ID: 20260701_000026
Revises: 20260615_000025
Create Date: 2026-07-01 00:00:26.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260701_000026"
down_revision: str | None = "20260615_000025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("deal_direction", sa.String(length=32), nullable=True))
    op.add_column("documents", sa.Column("deal_direction_confidence", sa.Float(), nullable=True))
    op.add_column("documents", sa.Column("deal_direction_rationale", sa.Text(), nullable=True))
    op.create_index("ix_documents_deal_direction", "documents", ["deal_direction"])
    op.create_index("ix_documents_deal_direction_confidence", "documents", ["deal_direction_confidence"])

    with op.batch_alter_table("documents") as batch:
        batch.create_check_constraint(
            "document_deal_direction_valid",
            "deal_direction IS NULL OR deal_direction IN ('purchase', 'sales', 'not_trade')",
        )

    op.add_column("requests", sa.Column("deal_direction", sa.String(length=32), nullable=True))
    op.create_index("ix_requests_deal_direction", "requests", ["deal_direction"])

    with op.batch_alter_table("requests") as batch:
        batch.create_check_constraint(
            "request_deal_direction_valid",
            "deal_direction IS NULL OR deal_direction IN ('purchase', 'sales', 'not_trade')",
        )


def downgrade() -> None:
    with op.batch_alter_table("requests") as batch:
        batch.drop_constraint("request_deal_direction_valid", type_="check")
    op.drop_index("ix_requests_deal_direction", table_name="requests")
    op.drop_column("requests", "deal_direction")

    with op.batch_alter_table("documents") as batch:
        batch.drop_constraint("document_deal_direction_valid", type_="check")
    op.drop_index("ix_documents_deal_direction_confidence", table_name="documents")
    op.drop_index("ix_documents_deal_direction", table_name="documents")
    op.drop_column("documents", "deal_direction_rationale")
    op.drop_column("documents", "deal_direction_confidence")
    op.drop_column("documents", "deal_direction")

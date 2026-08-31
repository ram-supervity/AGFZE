"""Record what a shipment document actually is, so BR-04 stops reading filenames

Revision ID: 20260530_000024
Revises: 20260515_000023
Create Date: 2026-05-30 00:00:24.000000+00:00

Two columns on `documents`.

The mandatory-document checklists BR-04 enforces are written in a vocabulary the classifier could
not speak. A packing list, a certificate of origin, a chemical analysis and a mill test
certificate are four separate entries on the China and India packs and all four classify as a
single `shipping_document`, so the rule had nothing to read and fell back to looking for the
words in the file's name. That works until a supplier attaches `scan001.pdf`, and it never
worked for the case AGFZE's own sample pack contains: one mill certificate printing its assay
table on its face, which is genuinely both the mill test certificate and the chemical analysis.

`document_kinds` is that vocabulary - a list, because one document can honestly be two entries.
`kinds_overridden` is the same guarantee `extracted_fields.is_overridden` gives one level down:
a person's correction survives the next re-extraction.

The backfill is deliberately empty. Nothing here guesses a kind for a document already in the
table: `_pack_entry_present` still falls back to the type and the filename exactly as before, so
existing packs resolve exactly as they did, and a document re-extracted after this migration
picks up its kinds from the classifier for real.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260530_000024"
down_revision: str | None = "20260515_000023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Declared here rather than imported from the models, exactly as every earlier migration does: a
# migration has to keep meaning what it meant when it ran, whatever the application later becomes.
JSONB_TYPE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("document_kinds", JSONB_TYPE, nullable=False, server_default=sa.text("'[]'")),
    )
    op.add_column(
        "documents",
        sa.Column("kinds_overridden", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # The defaults exist only to make both columns NOT NULL over the rows already there. Left in
    # place they would let an INSERT that forgets either column succeed silently.
    with op.batch_alter_table("documents") as batch:
        batch.alter_column("document_kinds", server_default=None)
        batch.alter_column("kinds_overridden", server_default=None)


def downgrade() -> None:
    op.drop_column("documents", "kinds_overridden")
    op.drop_column("documents", "document_kinds")

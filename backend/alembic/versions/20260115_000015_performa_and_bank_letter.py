"""Two more generated document types: the Performa invoice and the bank cover letter

Revision ID: 20260115_000015
Revises: 20260101_000014
Create Date: 2026-01-15 00:00:15.000000+00:00

A check-constraint widening and nothing else. `documents.document_type` is a plain string guarded
by a membership check rather than a PostgreSQL enum - exactly so a later  could add a value
without a type-altering migration - and this is the second time that decision has paid for itself.

Both new types are documents the platform *generates*, never receives. Nothing classifies a
document as either of them and nothing extracts from one; they exist so a generated draft can say
what it is.

The downgrade puts the previous vocabulary back, and will fail loudly rather than silently
discarding rows if either type is in use - which is correct. A generated Performa invoice is a real
document somebody produced, and a downgrade is not a licence to delete it.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from app.models.enums import DOCUMENT_TYPES, DocumentType, sql_in_list

revision: str = "20260115_000015"
down_revision: str | None = "20260101_000014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TYPE_CONSTRAINT = "ck_documents_document_type_valid"

NEW_TYPES = (
    DocumentType.DRAFT_PERFORMA_INVOICE.value,
    DocumentType.DRAFT_BANK_COVER_LETTER.value,
)

# The vocabulary as it stood before this migration, so the downgrade restores exactly that.
PREVIOUS_DOCUMENT_TYPES = tuple(value for value in DOCUMENT_TYPES if value not in NEW_TYPES)


def upgrade() -> None:
    op.execute(f'ALTER TABLE documents DROP CONSTRAINT "{TYPE_CONSTRAINT}"')
    op.execute(
        f'ALTER TABLE documents ADD CONSTRAINT "{TYPE_CONSTRAINT}" '
        f"CHECK (document_type IS NULL OR document_type IN ({sql_in_list(DOCUMENT_TYPES)}))"
    )


def downgrade() -> None:
    op.execute(f'ALTER TABLE documents DROP CONSTRAINT "{TYPE_CONSTRAINT}"')
    op.execute(
        f'ALTER TABLE documents ADD CONSTRAINT "{TYPE_CONSTRAINT}" '
        "CHECK (document_type IS NULL OR document_type IN "
        f"({sql_in_list(PREVIOUS_DOCUMENT_TYPES)}))"
    )

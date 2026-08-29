"""Replying on the thread a request arrived on, as a human-approved draft

Revision ID: 20260401_000020
Revises: 20260315_000019
Create Date: 2026-04-01 00:00:20.000000+00:00

One table. Nothing is sent by creating it, and nothing can be.

Discovery asks the platform to answer a broker or a supplier on the thread their message arrived
on, "initially via human-approved draft", and that every reply carry the standing disclaimer. Up
to this migration the platform could read a mailbox and could not write to one at all: there was
no outbound path, dormant or otherwise.

This adds one, and it is deliberately not automatic at either end. A reply is composed into a row
here, where it can be read and rewritten; it becomes a message in somebody's inbox only inside a
request a signed-in person made, and `sent_by_id` records which one. There is no worker, no
scheduler and no retry with a route to the send path.

The capability is switched off besides: `GRAPH_REPLY_ENABLED` defaults to false, because reading a
shared mailbox and writing from AGFZE's address are different decisions and the second one needs
`Mail.ReadWrite` and `Mail.Send` granted on top of the read scope. With it off, a reply is still
composed and still readable here - it simply cannot leave, and the endpoint says so plainly rather
than reporting a send that did not happen.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260401_000020"
down_revision: str | None = "20260315_000019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GUID = sa.Uuid(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "email_reply_drafts",
        sa.Column("id", GUID, primary_key=True),
        sa.Column(
            "request_id",
            GUID,
            sa.ForeignKey(
                "requests.id", ondelete="CASCADE", name="fk_email_reply_drafts_request_id_requests"
            ),
            nullable=False,
        ),
        sa.Column(
            "email_message_id",
            GUID,
            sa.ForeignKey(
                "email_messages.id",
                ondelete="CASCADE",
                name="fk_email_reply_drafts_email_message_id_email_messages",
            ),
            nullable=False,
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("subject", sa.String(1024)),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("provider_draft_id", sa.String(512)),
        sa.Column("failure_reason", sa.Text()),
        sa.Column(
            "composed_by_id",
            GUID,
            sa.ForeignKey(
                "users.id",
                ondelete="SET NULL",
                name="fk_email_reply_drafts_composed_by_id_users",
            ),
        ),
        sa.Column("composed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "sent_by_id",
            GUID,
            sa.ForeignKey(
                "users.id", ondelete="SET NULL", name="fk_email_reply_drafts_sent_by_id_users"
            ),
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft', 'sent', 'failed', 'withdrawn')",
            name="reply_status_valid",
        ),
    )
    op.create_index("ix_email_reply_drafts_request_id", "email_reply_drafts", ["request_id"])
    op.create_index(
        "ix_email_reply_drafts_email_message_id", "email_reply_drafts", ["email_message_id"]
    )
    op.create_index("ix_email_reply_drafts_status", "email_reply_drafts", ["status"])
    op.create_index(
        "ix_email_reply_drafts_composed_by_id", "email_reply_drafts", ["composed_by_id"]
    )
    op.create_index("ix_email_reply_drafts_sent_by_id", "email_reply_drafts", ["sent_by_id"])
    op.create_index(
        "ix_email_reply_drafts_request_status", "email_reply_drafts", ["request_id", "status"]
    )


def downgrade() -> None:
    op.drop_index("ix_email_reply_drafts_request_status", table_name="email_reply_drafts")
    op.drop_index("ix_email_reply_drafts_sent_by_id", table_name="email_reply_drafts")
    op.drop_index("ix_email_reply_drafts_composed_by_id", table_name="email_reply_drafts")
    op.drop_index("ix_email_reply_drafts_status", table_name="email_reply_drafts")
    op.drop_index("ix_email_reply_drafts_email_message_id", table_name="email_reply_drafts")
    op.drop_index("ix_email_reply_drafts_request_id", table_name="email_reply_drafts")
    op.drop_table("email_reply_drafts")

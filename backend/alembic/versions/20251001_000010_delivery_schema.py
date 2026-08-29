"""push subscriptions, and the two delivery timestamps  withheld

Revision ID: 20251001_000010
Revises: 20250901_000009
Create Date: 2025-10-01 00:00:10.000000+00:00

One new table and two new columns, which is the whole of this 's schema.

`push_subscriptions` is the sole gate on push delivery. It is unique on (user, endpoint) because
a browser that re-subscribes presents the same endpoint with rotated keys, and the correct answer
to that is an update in place - a second row would be a second delivery of the same sentence to
the same device.

`notifications.email_sent_at` and `notifications.push_sent_at` are the columns  deliberately
did not create. Its migration said they would arrive with the code that sends them; this is that
migration. Both are nullable, and NULL is the ordinary state - for a recipient who is not on that
channel, and equally for one whose delivery failed. The in-app row stands either way.

No table built in  1-9 other than `notifications` needs a deferred foreign key or a column
upgraded here.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20251001_000010"
down_revision: str | None = "20250901_000009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GUID = sa.Uuid(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "push_subscriptions",
        sa.Column("id", GUID, primary_key=True),
        sa.Column(
            "user_id",
            GUID,
            sa.ForeignKey(
                "users.id", ondelete="CASCADE", name="fk_push_subscriptions_user_id_users"
            ),
            nullable=False,
        ),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("p256dh", sa.String(255), nullable=False),
        sa.Column("auth", sa.String(255), nullable=False),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("user_id", "endpoint", name="uq_push_subscriptions_user_endpoint"),
    )
    op.create_index("ix_push_subscriptions_user_id", "push_subscriptions", ["user_id"])

    op.add_column(
        "notifications", sa.Column("email_sent_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "notifications", sa.Column("push_sent_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("notifications", "push_sent_at")
    op.drop_column("notifications", "email_sent_at")
    op.drop_index("ix_push_subscriptions_user_id", table_name="push_subscriptions")
    op.drop_table("push_subscriptions")

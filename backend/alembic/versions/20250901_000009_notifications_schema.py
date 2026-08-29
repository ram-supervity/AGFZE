"""the notifications table

Revision ID: 20250901_000009
Revises: 20250801_000008
Create Date: 2025-09-01 00:00:09.000000+00:00

One new table and nothing else. The administration module this step ships edits
`rule_configurations` and `document_type_schemas` exactly as they were created in Steps 2 and 3 -
both have carried a mandatory `change_reason` since the migration that created them, so making
them editable needs no schema change at all, only the endpoint and the screen that finally
enforce what the column has always demanded. The audit explorer reads `audit_events` as it
stands, and the settings page writes `users.notification_channel`, which has existed since
Step 1.

No previously-deferred foreign key needs upgrading here either: nothing built in Steps 1-8 held
a reference to a notification waiting for a table to exist.

`notifications` carries no `email_sent_at` and no `push_sent_at`. Those channels do not exist on
this platform, and a nullable timestamp for a delivery that can never happen would read as a
feature that is merely switched off. They arrive with the code that sends them.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20250901_000009"
down_revision: str | None = "20250801_000008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GUID = sa.Uuid(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", GUID, primary_key=True),
        sa.Column(
            "user_id",
            GUID,
            sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_notifications_user_id_users"),
            nullable=False,
        ),
        sa.Column("notification_type", sa.String(48), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("link", sa.String(512), nullable=True),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    op.create_index("ix_notifications_notification_type", "notifications", ["notification_type"])
    op.create_index("ix_notifications_is_read", "notifications", ["is_read"])
    op.create_index("ix_notifications_created_at", "notifications", ["created_at"])
    # The composite behind both reads that matter: the centre's own list and the header's
    # unread count.
    op.create_index(
        "ix_notifications_user_read_created",
        "notifications",
        ["user_id", "is_read", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_user_read_created", table_name="notifications")
    op.drop_index("ix_notifications_created_at", table_name="notifications")
    op.drop_index("ix_notifications_is_read", table_name="notifications")
    op.drop_index("ix_notifications_notification_type", table_name="notifications")
    op.drop_index("ix_notifications_user_id", table_name="notifications")
    op.drop_table("notifications")

"""The in-app notification: one row per person who needs to be told one thing.

There is exactly one writer, `app.services.notification_service.notify`, and every trigger point
in the platform goes through it. Nothing else constructs this model, for the same reason nothing
else constructs an `AuditEvent`: a second writer is a second set of rules about who gets told
what, and there is no way to keep two of those in agreement.

`email_sent_at` and `push_sent_at` arrive here in Step 10, with the code that sends them - Step 9
withheld them deliberately, because a nullable timestamp for a delivery that could not happen
would have read as a channel that was merely switched off. Both stay nullable and both mean one
narrow thing: the moment a delivery on that channel was accepted by the relay or the push
service. NULL is the normal state for a recipient who is not on that channel, and it is also what
a failed delivery leaves behind - the in-app row is the record either way, and it stands whether
or not anything left the building.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow
from app.db.types import GUID


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        # The one query the notification centre and the header bell both run: this user's rows,
        # unread first, newest first.
        Index("ix_notifications_user_read_created", "user_id", "is_read", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    notification_type: Mapped[str] = mapped_column(String(48), index=True)
    message: Mapped[str] = mapped_column(Text)
    # An in-app path, always relative. Nothing here ever holds an absolute URL, so a notification
    # can never navigate somebody off this platform.
    link: Mapped[str | None] = mapped_column(String(512))
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, default=utcnow
    )
    # Delivery, recorded per channel and never inferred from the other. A user can genuinely be
    # on all three at once: in-app always, email by preference, push by subscription.
    email_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    push_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

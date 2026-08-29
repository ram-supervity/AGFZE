"""One browser's Web Push registration, and the sole gate on push delivery.

A row here is not a preference. `users.notification_channel` says whether somebody additionally
wants email; nothing in that column has any bearing on push, because push is a permission the
browser grants and the browser can withdraw. Whether a person receives a push is answered by one
question only - does an active subscription exist for them - and this table is that answer.

Unique on (user, endpoint) on purpose. A browser that re-subscribes presents the same endpoint
with freshly rotated keys, and the correct response to that is to update the keys in place. A
second row would mean two deliveries of the same sentence to the same device, and then three.

The endpoint URL, the p256dh key and the auth secret are the browser's own material, not this
platform's. They are worth nothing without the VAPID private key that signs a delivery, which
never leaves the server.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow
from app.db.types import GUID


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    __table_args__ = (
        UniqueConstraint("user_id", "endpoint", name="uq_push_subscriptions_user_endpoint"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # Push services issue long, opaque URLs; Text rather than a guessed ceiling.
    endpoint: Mapped[str] = mapped_column(Text)
    p256dh: Mapped[str] = mapped_column(String(255))
    auth: Mapped[str] = mapped_column(String(255))
    # Only so an administrator can tell one of somebody's browsers from another. Never parsed.
    user_agent: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # Set when a delivery to this endpoint was last accepted. A subscription the push service
    # rejects as gone is deleted rather than stamped, so this only ever records a success.
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

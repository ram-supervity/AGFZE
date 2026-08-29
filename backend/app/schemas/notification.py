"""Read models for the notification centre and the header bell.

There is no create schema for a notification, and there will not be one: notifications are written
by the platform through `app.services.notification_service.notify` in response to something that
happened, never by a client asking for one.

The push-subscription schemas added in  are the exception that proves it. They do not
create a notification either - they register the browser a notification may later be delivered to,
which is the one thing about notifications a client genuinely owns.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.intake import Page


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    notification_type: str
    message: str
    # Always an in-app path. Nothing here ever carries an absolute URL.
    link: str | None
    is_read: bool
    created_at: datetime


class NotificationList(BaseModel):
    items: list[NotificationRead]
    page: Page
    unread_count: int


class MarkAllReadResult(BaseModel):
    marked: int
    unread_count: int


class VapidPublicKey(BaseModel):
    """The half of the VAPID pair the Web Push standard means to be public."""

    public_key: str
    # False on a deployment that has not generated a pair. The screen says so plainly rather than
    # offering a subscribe button that cannot work.
    configured: bool


class PushSubscriptionKeys(BaseModel):
    p256dh: str = Field(min_length=1, max_length=255)
    auth: str = Field(min_length=1, max_length=255)


class PushSubscriptionCreate(BaseModel):
    """Exactly the shape `PushSubscription.toJSON()` produces in the browser.

    `expirationTime` is accepted and ignored: it is almost always null, and this platform treats
    a subscription as live until a push service says it is gone.
    """

    model_config = ConfigDict(extra="ignore")

    endpoint: str = Field(min_length=1, max_length=2048)
    keys: PushSubscriptionKeys

    @field_validator("endpoint")
    @classmethod
    def _must_be_https(cls, value: str) -> str:
        endpoint = value.strip()
        if not endpoint.startswith("https://"):
            raise ValueError("A push endpoint must be an https:// URL issued by a push service.")
        return endpoint


class PushSubscriptionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    endpoint: str
    user_agent: str | None
    created_at: datetime
    last_used_at: datetime | None


class PushSubscriptionRemoval(BaseModel):
    """Which of the caller's own browsers to forget. Omitted, it forgets all of them."""

    model_config = ConfigDict(extra="ignore")

    endpoint: str | None = Field(default=None, max_length=2048)


class PushUnsubscribeResult(BaseModel):
    removed: int

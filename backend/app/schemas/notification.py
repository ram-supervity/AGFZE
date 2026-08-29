"""Read models for the notification centre and the header bell.

There is no create schema for a notification, and there will not be one: notifications are written
by the platform through `app.services.notification_service.notify` in response to something that
happened, never by a client asking for one.

The push-subscription schemas added in Step 10 are the exception that proves it. They do not
create a notification either - they register the browser a notification may later be delivered to,
which is the one thing about notifications a client genuinely owns.
"""

from __future__ import annotations

import base64
import binascii
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


def _urlsafe_bytes(value: str, field: str) -> bytes:
    """Decode the unpadded URL-safe base64 the Push API hands out in JavaScript.

    Browsers omit the padding, so it is restored here rather than demanded of the client.
    """
    padded = value + "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(padded)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"{field} is not valid URL-safe base64.") from exc


class PushSubscriptionKeys(BaseModel):
    """The two values `PushSubscription.getKey()` yields, checked for what they claim to be.

    Both are validated here rather than taken on trust, because a subscription carrying a key
    that is not really a key is worse than a rejected one. Delivery to it fails inside the
    encryption step, before any push service is contacted, so no push service ever returns the
    404 or 410 that prunes dead endpoints - the row simply stays in the table and fails silently
    for ever. Refusing it at the boundary hands the browser a 422 it can report instead.

    A real browser always sends valid values, so this rejects nothing legitimate.
    """

    p256dh: str = Field(min_length=1, max_length=255)
    auth: str = Field(min_length=1, max_length=255)

    @field_validator("p256dh")
    @classmethod
    def _must_be_a_point_on_the_curve(cls, value: str) -> str:
        # The length and the 0x04 uncompressed-point prefix are not sufficient: 65 arbitrary
        # bytes starting 0x04 satisfy both and still fail to decode. Only asking the curve
        # itself distinguishes a key from a string that resembles one, and that is precisely
        # the check `http_ece` performs at delivery time, brought forward to registration.
        from cryptography.hazmat.primitives.asymmetric import ec

        raw = _urlsafe_bytes(value, "p256dh")
        try:
            ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw)
        except ValueError as exc:
            raise ValueError("p256dh is not a valid P-256 public key.") from exc
        return value

    @field_validator("auth")
    @classmethod
    def _must_be_sixteen_bytes(cls, value: str) -> str:
        # RFC 8291 fixes the authentication secret at 16 octets; the encryption assumes it.
        if len(_urlsafe_bytes(value, "auth")) != 16:
            raise ValueError("auth must be a 16-byte value.")
        return value


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

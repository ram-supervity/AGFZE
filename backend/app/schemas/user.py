from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    subject_id: str
    entra_object_id: str | None
    # Mirrors whatever the identity provider asserted; it is not re-validated here. Corporate
    # realms legitimately use internal TLDs such as .local or .internal, which a strict RFC
    # deliverability check rejects.
    email: str
    display_name: str
    roles: list[str]
    default_stream_filter: str | None
    notification_channel: str
    is_active: bool
    has_completed_onboarding: bool = False
    created_at: datetime
    last_login_at: datetime | None


# Every value the column will accept, with the meaning  settled on it.
#
# In-app delivery is created for every notification and every user regardless of what is stored
# here - it is the platform's durable record, not a channel somebody can be without. So this
# column answers exactly one question: does this account ALSO get an email? `email` means yes,
# `in_app` (the default) means no.
#
# `push` remains accepted so that a value stored before  still validates, but it grants
# nothing: push is gated solely on whether the account has an active `PushSubscription`, which is
# a browser permission rather than a settings-page flag. Stored here it behaves as `in_app`. The
# settings page accordingly presents email as a simple toggle and push as its own, quite different
# browser-permission control beside it.
NOTIFICATION_CHANNELS: tuple[str, ...] = ("in_app", "email", "push")

# The streams a user may pin their dashboard and queues to by default. `None` means "everything
# my roles can see", which is the shipped default and stays a valid choice.
STREAM_FILTERS: tuple[str, ...] = ("scrap", "fa")


class UserPreferencesUpdate(BaseModel):
    """The endpoint deliberately left unbuilt in , completed here.

    Both fields are optional and each is applied only when present, so a client sending one never
    silently resets the other. There is no `roles`, no `is_active` and no `email` on this schema:
    a user editing their own settings must not be able to reach anything the identity provider
    owns, and the safest way to guarantee that is for the fields not to exist.
    """

    notification_channel: str | None = Field(default=None)
    default_stream_filter: str | None = Field(default=None)

    @field_validator("notification_channel")
    @classmethod
    def _known_channel(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value not in NOTIFICATION_CHANNELS:
            raise ValueError(
                "Not a notification channel this platform recognises: "
                + ", ".join(NOTIFICATION_CHANNELS)
            )
        return value

    @field_validator("default_stream_filter")
    @classmethod
    def _known_stream(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        if value not in STREAM_FILTERS:
            raise ValueError("Not a business stream: " + ", ".join(STREAM_FILTERS))
        return value

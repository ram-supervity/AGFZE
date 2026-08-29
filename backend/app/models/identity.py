from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow
from app.db.types import GUID, StringArrayType


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    subject_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    entra_object_id: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255))
    roles: Mapped[list[str]] = mapped_column(StringArrayType, default=list)
    default_stream_filter: Mapped[str | None] = mapped_column(String(64))
    notification_channel: Mapped[str] = mapped_column(String(32), default="in_app")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Whether this account has been shown the first-login walkthrough, either by finishing it or by
    # dismissing it. False for every existing account, which is true of them: nobody has seen a
    # walkthrough that did not exist. It is set once and never reset from the UI - somebody who
    # dismissed the tour meant it, and showing it again on the next login would be the platform
    # arguing with them.
    has_completed_onboarding: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

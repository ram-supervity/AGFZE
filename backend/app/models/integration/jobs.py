"""One posting attempt per target system, per transaction.

Three rows are written the moment a transaction is approved, and each of them is worked
independently: a DMS upload that cannot happen never holds up the tracker sync, and an SAP
posting that fails never touches either of the others. That independence is the whole reason
this is three rows rather than one status column on the transaction.

Two columns carry the honesty this module turns on.

`status` has a fifth value, `awaiting_manual_action`, because the SAP and DMS fallbacks are
genuinely neither a success nor a failure: the payload is prepared, the pack is compiled, and a
person has to finish the posting somewhere this platform cannot reach.

`completed_manually` records that a `succeeded` job got there because an administrator said so,
not because a call returned 200. It exists so no screen and no report can ever present a person's
work as if it had been automated.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, utcnow
from app.db.types import GUID, JSONBType
from app.models.enums import (
    INTEGRATION_JOB_STATUSES,
    INTEGRATION_TARGET_SYSTEMS,
    IntegrationJobStatus,
    sql_in_list,
)
from app.models.identity import User


class IntegrationJob(Base):
    __tablename__ = "integration_jobs"
    __table_args__ = (
        CheckConstraint(
            f"target_system IN ({sql_in_list(INTEGRATION_TARGET_SYSTEMS)})",
            name="integration_job_target_system_valid",
        ),
        CheckConstraint(
            f"status IN ({sql_in_list(INTEGRATION_JOB_STATUSES)})",
            name="integration_job_status_valid",
        ),
        CheckConstraint("attempt_count >= 0", name="integration_job_attempt_count_valid"),
        # A job that was completed by hand must say what was completed. The API refuses an empty
        # reference before it gets here; this is the guarantee behind that check.
        CheckConstraint(
            "completed_manually = false OR external_reference IS NOT NULL",
            name="integration_job_manual_needs_reference",
        ),
        # Exactly one job per target per transaction, so a re-run can never leave two competing
        # accounts of whether this deal reached SAP.
        UniqueConstraint(
            "transaction_id", "target_system", name="uq_integration_jobs_transaction_target"
        ),
        Index("ix_integration_jobs_status_last_attempted_at", "status", "last_attempted_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("trade_transactions.id", ondelete="CASCADE"), index=True
    )
    target_system: Mapped[str] = mapped_column(String(16), index=True)
    status: Mapped[str] = mapped_column(
        String(24), index=True, default=IntegrationJobStatus.QUEUED.value
    )
    # The receiving system's own identifier for what was posted, whether an automated call
    # returned it or an administrator typed in the one they got by hand.
    external_reference: Mapped[str | None] = mapped_column(String(255))
    failure_reason: Mapped[str | None] = mapped_column(Text)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    # True only where the success came from a person confirming they finished the posting
    # outside this platform. Never inferred, never defaulted true, and always rendered.
    completed_manually: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    completed_manually_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    completed_manually_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The reason the administrator gave. Required by the endpoint, and kept beside the job rather
    # than only on the audit trail so the monitor can show it without a second lookup.
    manual_note: Mapped[str | None] = mapped_column(Text)
    # What a person needs in front of them to finish this posting themselves: the structured
    # payload for SAP, the compiled pack's reference for the DMS. Written only on the fallback
    # path, and holding business data exclusively - never a credential, a token or a URL that
    # carries one.
    prepared_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONBType)
    # What the platform would like the person to do, in their words rather than an error's.
    manual_instruction: Mapped[str | None] = mapped_column(Text)
    last_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    completed_manually_by: Mapped[User | None] = relationship(
        lazy="selectin", foreign_keys=[completed_manually_by_id]
    )

"""One generated report, and every generation is one of these.

Two columns carry the discipline this table exists to hold.

`generation_reference` is minted once, printed visibly inside the rendered document itself, and
unique across the table. Somebody holding a printed page can read the reference off it and resolve
it back here to the exact date range, stream and status filter the figures were computed over, and
to the audit row that recorded the generation. A figure on paper with no way back to the query
behind it is exactly what this platform is replacing.

`content` is the report as it was produced - the sections, the figures, and the drill-through
filter behind each figure. It is the document, not a cache of the platform's current state: the
viewer renders what was generated at `generated_at`, which is what the downloadable file contains,
and every figure in it links through to a live, filtered query that reproduces it. Nothing reads
this column to answer a dashboard question; the dashboard computes from the governed tables every
time.

Nothing here is ever overwritten. Two generations with identical parameters produce two rows, in
the same versioning discipline `rule_evaluations` and the generated sales drafts already follow.

There is no `distributed_to`, no `sent_at` and no recipient column anywhere in *this* table, and
there still should not be. Distribution is not a property of a generated document: the same report
can be sent to a list that changes between one generation and the next, and stamping the list of
the day onto the row would make the document's own record disagree with the audit trail the moment
somebody edited the list. Who receives which scheduled report lives in `ReportDistributionRule`
below, and what was actually sent lives in the notification rows and the audit trail, which is
where every other delivery on this platform is already recorded.
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
from app.models.identity import User

REPORT_TYPES: tuple[str, ...] = ("daily", "monthly", "adhoc")
REPORT_FORMATS: tuple[str, ...] = ("pdf", "xlsx")
# `both` is the default and the honest one: AGFZE runs two business lines and a report that
# silently covered one of them would be read as covering the company.
REPORT_STREAMS: tuple[str, ...] = ("scrap", "fa", "both")


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (
        CheckConstraint(f"report_type IN ({_in_list(REPORT_TYPES)})", name="report_type_valid"),
        CheckConstraint(
            f"output_format IN ({_in_list(REPORT_FORMATS)})", name="report_format_valid"
        ),
        CheckConstraint(f"stream IN ({_in_list(REPORT_STREAMS)})", name="report_stream_valid"),
        CheckConstraint("period_end >= period_start", name="report_period_ordered"),
        Index("ix_reports_type_generated_at", "report_type", "generated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    report_type: Mapped[str] = mapped_column(String(16), index=True)
    output_format: Mapped[str] = mapped_column(String(8), index=True)
    # Which template produced it, recorded so a later reader knows the structure this document
    # was built to. Templates are editable configuration, so the key answers "what shape was this
    # report when it was generated" rather than "what shape is that report today".
    template_key: Mapped[str] = mapped_column(String(48), index=True)
    title: Mapped[str] = mapped_column(String(255))
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    stream: Mapped[str] = mapped_column(String(8), index=True, default="both")
    # The transaction status this report was narrowed to, where one was asked for. NULL is every
    # status, and is the normal case.
    status_filter: Mapped[str | None] = mapped_column(String(32))
    # Opaque storage key, resolved through the existing signed-URL download route. Never a path.
    storage_ref: Mapped[str] = mapped_column(String(512))
    byte_size: Mapped[int | None] = mapped_column(Integer)
    generation_reference: Mapped[str] = mapped_column(String(48), unique=True, index=True)
    # Exactly what was asked for, kept verbatim so the reference resolves back to a query somebody
    # can re-run rather than to a description of one.
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)
    # The rendered sections, their figures, and each figure's drill-through filter.
    content: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)
    # NULL for a scheduled generation. A system-produced report is not attributed to a person,
    # and inventing a service account to hold it would put a name on work nobody did.
    generated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    # The append-only row that recorded this generation, so the reference resolves to the audit
    # trail directly rather than through a search.
    audit_event_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("audit_events.id", ondelete="SET NULL"), index=True
    )
    # Set only where the monthly report's AI paragraph could not be produced. The report is
    # complete and correct either way; this is what the viewer renders instead of the paragraph.
    ai_summary_error: Mapped[str | None] = mapped_column(String(64))
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, default=utcnow
    )

    generated_by: Mapped[User | None] = relationship(lazy="selectin")


class ReportTemplateConfiguration(Base):
    """A report's structure, as an editable row rather than as layout code.

    What is held here is exactly the structure: which sections a report carries, in what order,
    and which figures go in each. What is *not* held here is any figure. Every number a report
    prints is still computed from the governed tables at generation time - this table decides only
    what is asked for and how it is laid out, which is why editing a template can never change
    what a past report said and can never make a new one say something the data does not.

    The same discipline every other configuration table on this platform follows: a mandatory
    `change_reason`, an attributed editor, and no value anywhere in application code. The three
    shipped structures are seeded by the migration that creates this table, so the day the screen
    arrives nothing about any report changes until somebody deliberately edits one.

    `template_key` and `report_type` are the row's identity and are never editable. Re-pointing a
    template at another report type would leave the reports already generated under it claiming a
    structure they were not built to, and `reports.template_key` records which structure produced
    each document precisely so that stays answerable.
    """

    __tablename__ = "report_template_configurations"
    __table_args__ = (
        CheckConstraint(
            f"report_type IN ({_in_list(REPORT_TYPES)})", name="report_template_type_valid"
        ),
        # One template per report type. The generator resolves a template by the type it was asked
        # for, so two rows claiming the same type would make which structure it used a matter of
        # row order.
        UniqueConstraint("report_type", name="uq_report_template_configurations_report_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    template_key: Mapped[str] = mapped_column(String(48), unique=True, index=True)
    report_type: Mapped[str] = mapped_column(String(16), index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    # `[{key, title, kind, source, description, figures: [...]}]`, in the order they are printed.
    sections: Mapped[list[dict[str, Any]]] = mapped_column(JSONBType, default=list)
    # The standing disclosures printed on the document itself. Editable with everything else,
    # because a disclosure that could not follow a structure change would go stale silently.
    disclosures: Mapped[list[str]] = mapped_column(JSONBType, default=list)
    # Whether this template asks the model for its one-paragraph summary, and whether it lists the
    # transactions themselves under the summary. Behavioural rather than structural, and carried
    # here so the whole template is one row rather than a row plus two constants.
    wants_ai_summary: Mapped[bool] = mapped_column(Boolean, default=False)
    include_detail_rows: Mapped[bool] = mapped_column(Boolean, default=False)
    default_period_days: Mapped[int] = mapped_column(Integer, default=1)
    change_reason: Mapped[str] = mapped_column(Text)
    changed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )

    changed_by: Mapped[User | None] = relationship(lazy="selectin")


# Which report types can be distributed. Ad-hoc is deliberately absent and must stay absent: its
# requester is already watching the job-progress indicator, and the check constraint is what stops
# a rule for one from being stored at all rather than being filtered out later.
DISTRIBUTABLE_REPORT_TYPES: tuple[str, ...] = ("daily", "monthly")

# What a rule may ask for, as a ceiling on delivery rather than an instruction to it. `in_app`
# means the notification row and nothing else; `email` and `both` additionally permit the email
# attempt the notification service's delivery step already makes. A recipient's own
# `User.notification_channel` preference still governs whether that attempt is made - a rule
# cannot email somebody who did not ask to be emailed, it can only decline to.
DISTRIBUTION_CHANNELS: tuple[str, ...] = ("in_app", "email", "both")


class ReportDistributionRule(Base):
    """Who receives a scheduled report, and on which channel.

    Configuration, in the same discipline as `rule_configurations`: a mandatory `change_reason`,
    an attributed `changed_by`, and no value anywhere in application code. A report type with no
    active rule is not an error - it generates and is viewable exactly as it always was, and
    nothing is distributed.

    Recipients are held as two independent lists because the business names them both ways: a
    standing "every approver" rule that stays correct as the desk's membership changes, and a
    named individual who is not covered by a role. Both resolve through the same
    `notification_service.notify` call, which de-duplicates a person named twice.

    Nothing here holds a report file or an address. Distribution is a notification pointing at the
    report's authenticated detail page, never an attachment - the platform does not email
    documents, and this table must never become the reason it starts.
    """

    __tablename__ = "report_distribution_rules"
    __table_args__ = (
        CheckConstraint(
            f"report_type IN ({_in_list(DISTRIBUTABLE_REPORT_TYPES)})",
            name="report_distribution_type_valid",
        ),
        CheckConstraint(
            f"channel IN ({_in_list(DISTRIBUTION_CHANNELS)})",
            name="report_distribution_channel_valid",
        ),
        Index("ix_report_distribution_rules_type_active", "report_type", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    report_type: Mapped[str] = mapped_column(String(16), index=True)
    # Role names, resolved to their active holders at send time rather than at save time, so a
    # rule naming a desk stays correct as people join and leave it.
    recipient_roles: Mapped[list[str]] = mapped_column(JSONBType, default=list)
    # Individual user ids, for a recipient no role covers.
    recipient_user_ids: Mapped[list[str]] = mapped_column(JSONBType, default=list)
    channel: Mapped[str] = mapped_column(String(16), default="in_app")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    change_reason: Mapped[str] = mapped_column(Text)
    changed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )

    changed_by: Mapped[User | None] = relationship(lazy="selectin")

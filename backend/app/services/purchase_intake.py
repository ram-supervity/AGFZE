"""The buying desk's intake bundle: what a purchase deal arrives as, and what it does not.

A purchase deal reaches AGFZE as exactly three inbound documents - the supplier's proforma or
commercial invoice, the packing list, and the weighbridge ticket. This module is the one place
that fact is written down as behaviour, and it is deliberately written in the vocabulary BR-04
already checks its territory packs in: `invoice` is a document *type*, and `packing_list` and
`weight_slip` are `DocumentKind` values the classifier assigns. Nothing here invents a second
completeness mechanism beside the one the platform already has.

The one thing this module refuses to expect is the purchase contract. That is a document this
platform *writes* out of the confirmed figures, so waiting for it inbound would make a deal that
arrived correctly look incomplete for ever, and would count the platform's own draft as a
supplier's paperwork if one ever came back round on an email thread.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.roles import PlatformRole
from app.models.enums import (
    PURCHASE_BUNDLE_ITEMS,
    PURCHASE_BUNDLE_LABELS,
    PURCHASE_INTAKE_UNEXPECTED_DOCUMENT_TYPES,
    DocumentSource,
    ExceptionCategory,
    ExceptionPriority,
    RequestCategory,
)
from app.models.intake import Document, Request
from app.services.audit_service import ActorType, record_audit_event


class AuditEvent:
    BUNDLE_EVALUATED = "purchase.bundle_evaluated"
    BUNDLE_INCOMPLETE = "purchase.bundle_incomplete"
    BUNDLE_UNEXPECTED_DOCUMENT = "purchase.bundle_unexpected_document"


def pack_entry_present(entry: str, documents: list[Document]) -> Document | None:
    """Is this checklist entry evidenced by something actually attached?

    Three signals, strongest first - the document's own **kind**, then its **type**, then its
    **filename**. This is the matcher BR-04 was already written around, lifted to one place so
    the purchase bundle and the territory pack cannot drift into judging "present" differently.
    """
    needle = entry.strip().lower()
    compact = needle.replace("_", "")
    for document in documents:
        if needle in (document.document_kinds or ()):
            return document
        if document.document_type == needle or document.document_type_hint == needle:
            return document
        haystack = document.filename.lower()
        if needle.replace("_", " ") in haystack or compact in haystack.replace(" ", "").replace(
            "_", ""
        ).replace("-", ""):
            return document
    return None


@dataclass(frozen=True)
class BundleItem:
    """One expected document, and the document that satisfied it if one has arrived."""

    item: str
    label: str
    received: bool
    document_id: UUID | None
    filename: str | None
    confirmed: bool


@dataclass(frozen=True)
class BundleStatus:
    items: tuple[BundleItem, ...]
    unexpected: tuple[Document, ...]

    @property
    def missing(self) -> tuple[str, ...]:
        return tuple(row.item for row in self.items if not row.received)

    @property
    def complete(self) -> bool:
        return not self.missing

    @property
    def confirmed(self) -> bool:
        """Every expected document present *and* signed off by the desk."""
        return bool(self.items) and all(row.confirmed for row in self.items)

    @property
    def pure(self) -> bool:
        return not self.unexpected

    def summary(self) -> str:
        received = sum(1 for row in self.items if row.received)
        return f"{received} of {len(self.items)} purchase documents received"


def inbound(documents: list[Document]) -> list[Document]:
    """Everything that genuinely came in. A draft this platform wrote is not an arrival."""
    return [row for row in documents if row.source != DocumentSource.GENERATED.value]


def is_unexpected(document: Document) -> bool:
    """A document on a purchase intake that the bundle never asks for.

    A purchase contract is the case that matters and the reason this exists: it is generated
    here, so one arriving inbound is either filed against the wrong deal or is this platform's
    own draft coming back round. Either way a person decides.
    """
    if document.document_type in PURCHASE_INTAKE_UNEXPECTED_DOCUMENT_TYPES:
        return True
    return document.deal_direction == "sales"


def status_for(documents: list[Document]) -> BundleStatus:
    """The bundle, item by item, against the documents actually attached."""
    arrivals = inbound(documents)
    items: list[BundleItem] = []
    for entry in PURCHASE_BUNDLE_ITEMS:
        match = pack_entry_present(entry, arrivals)
        items.append(
            BundleItem(
                item=entry,
                label=PURCHASE_BUNDLE_LABELS.get(entry, entry.replace("_", " ").title()),
                received=match is not None,
                document_id=match.id if match is not None else None,
                filename=match.filename if match is not None else None,
                confirmed=bool(match is not None and match.confirmed_at is not None),
            )
        )
    return BundleStatus(
        items=tuple(items),
        unexpected=tuple(row for row in arrivals if is_unexpected(row)),
    )


def is_purchase_request(request: Request) -> bool:
    return (
        request.deal_direction == "purchase"
        or request.category == RequestCategory.PURCHASE.value
    )


async def documents_of_request(session: AsyncSession, request_id: UUID) -> list[Document]:
    return list(
        (
            await session.scalars(
                select(Document)
                .where(Document.request_id == request_id)
                .order_by(Document.created_at)
            )
        ).all()
    )


async def documents_of_transaction(session: AsyncSession, transaction_id: UUID) -> list[Document]:
    return list(
        (
            await session.scalars(
                select(Document)
                .where(Document.transaction_id == transaction_id)
                .order_by(Document.created_at)
            )
        ).all()
    )


async def status_for_transaction(session: AsyncSession, transaction_id: UUID) -> BundleStatus:
    return status_for(await documents_of_transaction(session, transaction_id))


async def evaluate_request(
    session: AsyncSession,
    request: Request,
    documents: list[Document] | None = None,
) -> BundleStatus:
    """Check one purchase intake, flag it where it is short or impure, and audit the outcome.

    The flag is the existing one. A short or impure bundle sets `needs_review` on the request and
    opens the ordinary exception case through the ordinary hook - there is no second review queue
    and no second severity vocabulary here.
    """
    rows = documents if documents is not None else await documents_of_request(session, request.id)
    status = status_for(rows)

    await record_audit_event(
        session,
        event_type=AuditEvent.BUNDLE_EVALUATED,
        entity_type="request",
        entity_id=request.id,
        actor_type=ActorType.AGENT,
        metadata={
            "expected": list(PURCHASE_BUNDLE_ITEMS),
            "received": [row.item for row in status.items if row.received],
            "missing": list(status.missing),
            "unexpected": [
                {"document_id": str(row.id), "document_type": row.document_type}
                for row in status.unexpected
            ],
        },
    )

    if status.complete and status.pure:
        return status

    request.needs_review = True
    for document in status.unexpected:
        document.needs_review = True

    # Imported here rather than at module scope: the hook reaches the notification service, and
    # the intake pipeline is imported by it in turn. One local import is cheaper than a cycle.
    from app.services.governance import hooks as governance_hooks

    if status.missing:
        await governance_hooks.open_case(
            session,
            category=ExceptionCategory.MISSING_MANDATORY_DOCUMENT.value,
            owner_role=PlatformRole.PURCHASE_USER.value,
            priority=ExceptionPriority.HIGH.value,
            summary=(
                f"{request.request_code} is short of its purchase bundle. Still missing: "
                + ", ".join(
                    PURCHASE_BUNDLE_LABELS.get(entry, entry).lower() for entry in status.missing
                )
                + ". Nothing is generated for this deal until all three arrive."
            ),
            document_id=status.items[0].document_id if status.items else None,
            request_id=request.id,
            rule_id="PR-01",
            check_key="purchase_bundle_complete",
            field_name="purchase_bundle",
            expected_value=f"{len(status.items)} of {len(status.items)} documents",
            actual_value=status.summary(),
            assigned_to_id=request.created_by_id,
        )
        await record_audit_event(
            session,
            event_type=AuditEvent.BUNDLE_INCOMPLETE,
            entity_type="request",
            entity_id=request.id,
            actor_type=ActorType.AGENT,
            metadata={"missing": list(status.missing)},
        )

    for document in status.unexpected:
        await governance_hooks.open_case(
            session,
            category=ExceptionCategory.UNMATCHED_REFERENCE.value,
            owner_role=PlatformRole.PURCHASE_USER.value,
            priority=ExceptionPriority.MEDIUM.value,
            summary=(
                f"'{document.filename}' arrived on purchase intake {request.request_code} as a "
                f"{(document.document_type or 'document').replace('_', ' ')}, which a purchase "
                "bundle never carries - the purchase contract is written by this platform, not "
                "received. Confirm which deal it belongs to before it is relied on."
            ),
            document_id=document.id,
            request_id=request.id,
            rule_id="PR-01",
            check_key="purchase_bundle_purity",
            field_name="document_type",
            expected_value=", ".join(PURCHASE_BUNDLE_ITEMS),
            actual_value=document.document_type or "unknown",
            assigned_to_id=request.created_by_id,
        )
        await record_audit_event(
            session,
            event_type=AuditEvent.BUNDLE_UNEXPECTED_DOCUMENT,
            entity_type="document",
            entity_id=document.id,
            actor_type=ActorType.AGENT,
            metadata={
                "request_id": str(request.id),
                "document_type": document.document_type,
            },
        )

    return status

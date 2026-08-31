"""What a confirmed purchase extraction sets off, once the bundle is genuinely complete.

Two things, and only these two:

* the platform's **existing** generation logic is queued for the purchase contract and the cost
  sheet - `draft_service.queue_generation`, the same function behind
  `POST /transactions/{id}/generate-draft`, the same background job service, the same templates,
  the same audit events. There is no second generator here and there must never be one;
* the batch's **Loading Sheet** row is written, from `tracker_fields(transaction)` and through
  the Graph Excel path where a workbook is configured.

Both are gated and both are idempotent, and the two properties are separate:

The gate is `draft_service.purchase_draft_generation_permitted`, unchanged. Supplier name,
quantity, commodity and a rate or price have to be on the record, because a purchase contract
missing any of them is not a draft with a gap in it - it is a contract stating the wrong thing.
Where the gate refuses, the existing blocker message is what comes back and nothing is generated.

The idempotency is `drafts_for` / `_draft_count` plus the in-flight job check below. Confirming a
second document on the same batch, or re-confirming the first, is an ordinary thing for a desk to
do; it must never stack a second purchase contract on the transaction. Regeneration on purpose is
still available on the workspace's own button, which is where a person asks for it deliberately.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.enums import PURCHASE_GENERATED_DOCUMENT_TYPES, DocumentSource
from app.models.identity import User
from app.models.intake import Document
from app.models.jobs import BackgroundJob, JobStatus
from app.models.transactions import TradeTransaction
from app.services import draft_service, purchase_intake
from app.services.audit_service import ActorType, record_audit_event
from app.services.integration import loading_sheet
from app.services.transaction_fields import LOCKED_STATUSES

logger = get_logger(__name__)


class AuditEvent:
    COMPLETION_RUN = "purchase.completion_run"
    COMPLETION_BLOCKED = "purchase.completion_blocked"


@dataclass
class CompletionResult:
    """What the confirmation actually set off, in terms a screen can render without guessing."""

    bundle_complete: bool = False
    bundle_missing: tuple[str, ...] = ()
    generated: dict[str, UUID] = field(default_factory=dict)
    already_present: tuple[str, ...] = ()
    blocker: str | None = None
    loading_sheet_batch: str | None = None
    loading_sheet_created: bool = False
    loading_sheet_status: str | None = None

    @property
    def ran(self) -> bool:
        return bool(self.generated or self.loading_sheet_batch)


async def _in_flight(session: AsyncSession, transaction_id: UUID) -> bool:
    """Is a draft generation for this transaction already running?

    `_draft_count` answers "has one been produced"; this answers "is one being produced right
    now". Both are needed: generation is a background job, so two confirmations moments apart
    would otherwise each see nothing on the record and each queue their own.
    """
    job = await session.scalar(
        select(BackgroundJob.id).where(
            BackgroundJob.transaction_id == transaction_id,
            BackgroundJob.job_type == draft_service.JOB_TYPE_DRAFT,
            BackgroundJob.status.in_((JobStatus.QUEUED.value, JobStatus.PROCESSING.value)),
        )
    )
    return job is not None


async def _existing_types(session: AsyncSession, transaction_id: UUID) -> set[str]:
    rows = (
        await session.scalars(
            select(Document.document_type).where(
                Document.transaction_id == transaction_id,
                Document.source == DocumentSource.GENERATED.value,
                Document.document_type.in_(PURCHASE_GENERATED_DOCUMENT_TYPES),
            )
        )
    ).all()
    return {row for row in rows if row}


async def on_purchase_confirmed(
    session: AsyncSession,
    transaction: TradeTransaction,
    *,
    actor: User,
) -> CompletionResult:
    """Run the completion step for one confirmed purchase transaction.

    Safe to call after every confirmation on a purchase batch. It decides for itself whether
    anything is owed, and does nothing at all where nothing is.
    """
    result = CompletionResult()
    if transaction.purchase_leg is None:
        return result

    status = await purchase_intake.status_for_transaction(session, transaction.id)
    result.bundle_complete = status.complete
    result.bundle_missing = status.missing

    if not status.complete or not status.pure:
        # The bundle rule has already flagged this and opened its case. Nothing is generated for
        # a deal whose paperwork is short or carries something a purchase never does.
        result.blocker = (
            "The purchase bundle is incomplete. Still missing: "
            + ", ".join(entry.replace("_", " ") for entry in status.missing)
            + "."
            if status.missing
            else "This purchase intake carries paperwork a purchase bundle never does, so "
            "nothing has been generated for it."
        )
        await record_audit_event(
            session,
            event_type=AuditEvent.COMPLETION_BLOCKED,
            entity_type="trade_transaction",
            entity_id=transaction.id,
            actor_id=actor.id,
            actor_type=ActorType.USER,
            metadata={
                "batch_number": transaction.batch_number,
                "missing": list(status.missing),
                "unexpected": [str(row.id) for row in status.unexpected],
                "reason": "bundle_incomplete",
            },
        )
        return result

    permitted, blocker = draft_service.purchase_draft_generation_permitted(transaction)
    if not permitted:
        # The existing gate, and the existing message. Surfaced rather than worked around: a
        # purchase contract with no rate on it is not a draft, it is a wrong contract.
        result.blocker = blocker
        await record_audit_event(
            session,
            event_type=AuditEvent.COMPLETION_BLOCKED,
            entity_type="trade_transaction",
            entity_id=transaction.id,
            actor_id=actor.id,
            actor_type=ActorType.USER,
            metadata={
                "batch_number": transaction.batch_number,
                "reason": "draft_generation_not_permitted",
                "blocker": blocker,
            },
        )
        return result

    # The Loading Sheet is written whether or not a draft is owed. A batch whose drafts were
    # produced on an earlier confirmation still has to have its row kept current.
    upserted = await loading_sheet.upsert_row(session, transaction, actor_id=actor.id)
    result.loading_sheet_batch = upserted.row.batch_number
    result.loading_sheet_created = upserted.created
    result.loading_sheet_status = upserted.row.sync_status

    produced = await _existing_types(session, transaction.id)
    result.already_present = tuple(sorted(produced))

    if transaction.status in LOCKED_STATUSES:
        # Approved or awaiting approval: a new draft here would not match what the approver was
        # shown. The same refusal the manual endpoint makes, for the same reason.
        result.blocker = (
            "This transaction is awaiting approval or already approved, so its drafts are frozen "
            "with it."
        )
    elif await _in_flight(session, transaction.id):
        result.blocker = "A draft is already being generated for this batch."
    else:
        for document_type in PURCHASE_GENERATED_DOCUMENT_TYPES:
            if document_type in produced:
                continue
            if await draft_service._draft_count(session, transaction.id, document_type):
                continue
            job_id = await draft_service.queue_generation(
                session,
                transaction,
                document_type=document_type,
                requested_by=actor,
            )
            result.generated[document_type] = job_id
            produced.add(document_type)

    await record_audit_event(
        session,
        event_type=AuditEvent.COMPLETION_RUN,
        entity_type="trade_transaction",
        entity_id=transaction.id,
        actor_id=actor.id,
        actor_type=ActorType.USER,
        metadata={
            "batch_number": transaction.batch_number,
            "queued": {name: str(job) for name, job in result.generated.items()},
            "already_present": list(result.already_present),
            "loading_sheet_batch": result.loading_sheet_batch,
            "loading_sheet_created": result.loading_sheet_created,
            "loading_sheet_status": result.loading_sheet_status,
            "blocker": result.blocker,
        },
    )
    return result


def message(result: CompletionResult) -> str:
    """One sentence for the confirmation response, saying only what genuinely happened."""
    if not result.bundle_complete:
        return result.blocker or ""
    parts: list[str] = []
    if result.generated:
        parts.append(
            "Purchase contract and cost sheet are being generated."
            if len(result.generated) > 1
            else f"The {next(iter(result.generated)).replace('draft_', '').replace('_', ' ')} is "
            "being generated."
        )
    elif result.already_present:
        parts.append("Its drafts were already generated and have not been duplicated.")
    if result.loading_sheet_batch:
        parts.append(
            f"Loading Sheet row {'written' if result.loading_sheet_created else 'updated'} for "
            f"batch {result.loading_sheet_batch}."
        )
    if result.blocker and not result.generated:
        parts.append(result.blocker)
    return " ".join(parts)

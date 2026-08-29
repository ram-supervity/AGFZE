"""The integration monitor: what was posted where, what failed, and what a person still owes.

Admin only, and enforced here rather than by which screen renders the buttons. Reading a
transaction's own integration status is open to everybody through `GET /transactions/{id}`,
because a preparing desk needs to know whether their deal reached SAP; the queue across every
transaction, the retry and the manual confirmation are the integration-support function's.

The two write endpoints are deliberately not one endpoint with a mode. Retry re-attempts an
automated posting that genuinely failed. Manual completion records that a person finished a
posting this platform cannot make. They resolve different states, need different inputs and mean
different things, and collapsing them would invite an administrator to press "retry" on a job
that has nothing left to retry.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.dependencies import DbSession, require_roles
from app.core.errors import NotFoundError
from app.core.roles import PlatformRole
from app.models.enums import (
    INTEGRATION_JOB_STATUSES,
    INTEGRATION_TARGET_SYSTEMS,
    IntegrationJobStatus,
)
from app.models.identity import User
from app.models.integration import IntegrationJob
from app.models.transactions import TradeTransaction
from app.schemas.common import ResponseEnvelope
from app.schemas.intake import Page
from app.schemas.integration import (
    IntegrationJobDetail,
    IntegrationJobQueue,
    ManualCompletionRequest,
    job_detail,
)
from app.services.integration import integration_service

router = APIRouter(prefix="/integrations", tags=["integrations"])

# The integration-support function. One role, checked server-side on every call.
IntegrationAdmin = Annotated[User, Depends(require_roles(PlatformRole.ADMIN.value))]


async def _detail_for(session: DbSession, job: IntegrationJob) -> IntegrationJobDetail:
    return job_detail(job, await integration_service.load_transaction(session, job.transaction_id))


@router.get(
    "/jobs",
    response_model=ResponseEnvelope[IntegrationJobQueue],
    summary="Every integration job, filterable by target system and status",
)
async def list_jobs(
    user: IntegrationAdmin,
    session: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    target_system: str | None = Query(None),
    status: str | None = Query(None),
    # Not a filter the monitor's own controls offer: it is how a transaction workspace links
    # through to exactly its own three jobs rather than dropping the reader into the whole queue.
    transaction_id: UUID | None = Query(None),
) -> ResponseEnvelope[IntegrationJobQueue]:
    if target_system and target_system not in INTEGRATION_TARGET_SYSTEMS:
        target_system = None
    if status and status not in INTEGRATION_JOB_STATUSES:
        status = None

    statement = select(IntegrationJob)
    if target_system:
        statement = statement.where(IntegrationJob.target_system == target_system)
    if status:
        statement = statement.where(IntegrationJob.status == status)
    if transaction_id is not None:
        statement = statement.where(IntegrationJob.transaction_id == transaction_id)

    total = int(await session.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    rows = list(
        (
            await session.scalars(
                statement.options(selectinload(IntegrationJob.completed_manually_by))
                # The work that needs a person first, then the newest. A failed job and a job
                # waiting on somebody are the two rows an administrator opened this screen for.
                .order_by(IntegrationJob.updated_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )

    transactions = {
        transaction.id: transaction
        for transaction in (
            await session.scalars(
                select(TradeTransaction)
                .where(TradeTransaction.id.in_([row.transaction_id for row in rows] or [None]))
                .options(
                    selectinload(TradeTransaction.purchase_leg),
                    selectinload(TradeTransaction.sales_leg),
                    selectinload(TradeTransaction.fa_leg),
                )
            )
        ).all()
    }

    by_target = dict(
        (
            await session.execute(
                select(IntegrationJob.target_system, func.count(IntegrationJob.id)).group_by(
                    IntegrationJob.target_system
                )
            )
        ).all()
    )
    by_status = dict(
        (
            await session.execute(
                select(IntegrationJob.status, func.count(IntegrationJob.id)).group_by(
                    IntegrationJob.status
                )
            )
        ).all()
    )

    return ResponseEnvelope[IntegrationJobQueue](
        data=IntegrationJobQueue(
            items=[job_detail(row, transactions.get(row.transaction_id)) for row in rows],
            page=Page(
                page=page,
                page_size=page_size,
                total=total,
                total_pages=max(1, -(-total // page_size)),
            ),
            counts_by_target={
                target: int(by_target.get(target, 0)) for target in INTEGRATION_TARGET_SYSTEMS
            },
            counts_by_status={
                value: int(by_status.get(value, 0)) for value in INTEGRATION_JOB_STATUSES
            },
            configured_targets=integration_service.configured_targets(),
            max_attempts=settings.INTEGRATION_MAX_ATTEMPTS,
        )
    )


@router.post(
    "/jobs/{job_id}/retry",
    response_model=ResponseEnvelope[IntegrationJobDetail],
    summary="Re-queue a failed job now, outside its backoff schedule",
)
async def retry_job(
    job_id: UUID, user: IntegrationAdmin, session: DbSession
) -> ResponseEnvelope[IntegrationJobDetail]:
    """Only a genuinely failed job. The attempt is made immediately and reported honestly.

    A job waiting on manual action is refused here by name: there is nothing automated left to
    re-attempt on it, and the honest action is to confirm the completion instead.
    """
    job = await integration_service.get_job(session, job_id)
    await integration_service.retry(session, job, user=user)
    await session.commit()

    refreshed = await integration_service.get_job(session, job_id)
    detail = await _detail_for(session, refreshed)
    message = {
        IntegrationJobStatus.SUCCEEDED.value: (
            f"{detail.target_label} accepted the posting: {detail.external_reference}."
        ),
        IntegrationJobStatus.AWAITING_MANUAL_ACTION.value: (
            f"{detail.target_label} is not configured on this deployment, so nothing was posted. "
            "Everything needed to complete it by hand is on the job."
        ),
        IntegrationJobStatus.FAILED.value: (f"The attempt failed again: {detail.failure_reason}"),
    }.get(
        refreshed.status,
        "The job has been re-queued and will be attempted again shortly.",
    )
    return ResponseEnvelope[IntegrationJobDetail](data=detail, message=message)


@router.post(
    "/jobs/{job_id}/complete-manual",
    response_model=ResponseEnvelope[IntegrationJobDetail],
    summary="Confirm a job awaiting manual action was completed outside the platform",
)
async def complete_job_manually(
    job_id: UUID,
    payload: ManualCompletionRequest,
    user: IntegrationAdmin,
    session: DbSession,
) -> ResponseEnvelope[IntegrationJobDetail]:
    """Record a person's posting as a person's posting.

    The reference and the reason are both required, and the resulting `succeeded` job is marked
    `completed_manually` for the rest of its life. That mark is what stops this success from
    being read, later, as something the platform did.
    """
    job = await integration_service.get_job(session, job_id)
    await integration_service.complete_manually(
        session,
        job,
        user=user,
        external_reference=payload.external_reference,
        note=payload.note,
    )
    await session.commit()

    refreshed = await integration_service.get_job(session, job_id)
    detail = await _detail_for(session, refreshed)
    committed = detail.transaction_status == "committed"
    return ResponseEnvelope[IntegrationJobDetail](
        data=detail,
        message=(
            f"Recorded as completed by you, against {detail.external_reference}. It is marked as "
            "a manual completion and will always show as one."
            + (
                f" All three postings for {detail.batch_number} are now resolved, so the "
                "transaction is committed."
                if committed
                else ""
            )
        ),
    )


@router.get(
    "/jobs/{job_id}",
    response_model=ResponseEnvelope[IntegrationJobDetail],
    summary="One integration job, with whatever a person needs to finish it by hand",
)
async def read_job(
    job_id: UUID, user: IntegrationAdmin, session: DbSession
) -> ResponseEnvelope[IntegrationJobDetail]:
    job = await session.scalar(
        select(IntegrationJob)
        .where(IntegrationJob.id == job_id)
        .options(selectinload(IntegrationJob.completed_manually_by))
    )
    if job is None:
        raise NotFoundError("Integration job not found.")
    return ResponseEnvelope[IntegrationJobDetail](data=await _detail_for(session, job))

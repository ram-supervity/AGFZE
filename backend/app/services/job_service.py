from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.core.roles import PlatformRole
from app.models.identity import User
from app.models.jobs import BackgroundJob, JobStatus

READ_ANY_JOB_ROLES: frozenset[str] = frozenset(
    {PlatformRole.ADMIN.value, PlatformRole.AUDITOR.value}
)


async def create_job(
    session: AsyncSession,
    *,
    job_type: str,
    created_by_id: UUID | None = None,
    transaction_id: UUID | None = None,
) -> BackgroundJob:
    job = BackgroundJob(
        job_type=job_type,
        status=JobStatus.QUEUED.value,
        progress=0,
        created_by_id=created_by_id,
        transaction_id=transaction_id,
        # A job nobody asked for is the platform's own. Mailbox intake raises one per captured
        # message, and the desk the message is routed to has to be able to watch it.
        is_system=created_by_id is None,
    )
    session.add(job)
    await session.flush()
    return job


async def get_job(session: AsyncSession, job_id: UUID) -> BackgroundJob | None:
    return await session.get(BackgroundJob, job_id)


async def update_job_progress(
    session: AsyncSession,
    job_id: UUID,
    progress: int,
    *,
    status: str | None = None,
) -> BackgroundJob:
    job = await _require_job(session, job_id)
    job.progress = max(0, min(100, progress))
    if status is not None:
        job.status = status
    elif job.progress > 0 and job.status == JobStatus.QUEUED.value:
        job.status = JobStatus.PROCESSING.value
    await session.flush()
    return job


async def complete_job(
    session: AsyncSession,
    job_id: UUID,
    *,
    result_ref: str | None = None,
) -> BackgroundJob:
    job = await _require_job(session, job_id)
    job.status = JobStatus.COMPLETED.value
    job.progress = 100
    job.result_ref = result_ref
    await session.flush()
    return job


async def fail_job(session: AsyncSession, job_id: UUID, *, error_message: str) -> BackgroundJob:
    job = await _require_job(session, job_id)
    job.status = JobStatus.FAILED.value
    job.error_message = error_message
    await session.flush()
    return job


def user_may_read_job(user: User, job: BackgroundJob) -> bool:
    """Who may poll a job's status.

    A job a person started is theirs, plus the two roles that may read anything. A job the
    platform started for itself - mailbox intake, and nothing else today - is readable by any
    signed-in account, because otherwise the pipeline behind every email-originated request runs
    where no desk can see it: the Inbox would show a row appear and never show it progressing,
    and the platform's one polling convention would answer 404 to the people it exists for.
    Nothing counterparty-specific is exposed by that; a job row carries a state, a progress
    integer, a platform-authored error string and an opaque result reference.
    """
    if job.is_system:
        return True
    return job.created_by_id == user.id or bool(READ_ANY_JOB_ROLES.intersection(user.roles or ()))


async def _require_job(session: AsyncSession, job_id: UUID) -> BackgroundJob:
    job = await session.get(BackgroundJob, job_id)
    if job is None:
        raise NotFoundError("Job not found.")
    return job

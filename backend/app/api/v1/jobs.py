from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from app.core.dependencies import CurrentUser, DbSession
from app.core.errors import NotFoundError
from app.schemas.common import ResponseEnvelope
from app.schemas.job import JobStatusRead
from app.services import job_service

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get(
    "/{job_id}/status",
    response_model=ResponseEnvelope[JobStatusRead],
    summary="Poll a background job",
)
async def read_job_status(
    job_id: UUID,
    user: CurrentUser,
    session: DbSession,
) -> ResponseEnvelope[JobStatusRead]:
    job = await job_service.get_job(session, job_id)
    # A job the caller may not read answers exactly like a job that does not exist, so the
    # endpoint cannot be used to probe which job ids are real.
    if job is None or not job_service.user_may_read_job(user, job):
        raise NotFoundError("Job not found.")
    return ResponseEnvelope[JobStatusRead](data=JobStatusRead.model_validate(job))

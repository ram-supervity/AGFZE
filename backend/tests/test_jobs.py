"""Background job lifecycle, progress handling and read scoping."""

from __future__ import annotations

import json
import uuid
from datetime import datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.models import JobStatus, User
from app.services.job_service import (
    complete_job,
    create_job,
    fail_job,
    get_job,
    update_job_progress,
    user_may_read_job,
)
from tests.utils.tokens import auth_header, build_token

pytestmark = pytest.mark.usefixtures("patched_jwks")

ME_URL = "/api/v1/users/me"


def status_url(job_id: uuid.UUID) -> str:
    return f"/api/v1/jobs/{job_id}/status"


async def provision(
    client: AsyncClient,
    session: AsyncSession,
    *,
    subject_id: str,
    email: str,
    name: str,
    roles: list[str],
) -> tuple[User, dict[str, str]]:
    """Sign in once so the user exists, then hand back the row and its Authorization header."""
    token = build_token(sub=subject_id, email=email, name=name, realm_access={"roles": roles})
    response = await client.get(ME_URL, headers=auth_header(token))
    assert response.status_code == 200
    user = (await session.scalars(select(User).where(User.subject_id == subject_id))).one()
    await session.commit()
    return user, auth_header(token)


async def poll(client: AsyncClient, job_id: uuid.UUID, headers: dict[str, str]) -> dict:
    response = await client.get(status_url(job_id), headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    return payload["data"]


async def test_the_polling_endpoint_follows_the_job_to_completion(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    owner, owner_auth = await provision(
        client,
        db_session,
        subject_id="0a1b2c3d-0000-4000-8000-0000000000e1",
        email="purchase.user@agfze.ae",
        name="Marco Bellini",
        roles=["purchase_user"],
    )

    job = await create_job(db_session, job_type="transaction.ingest", created_by_id=owner.id)
    await db_session.commit()

    queued = await poll(client, job.id, owner_auth)
    assert queued["id"] == str(job.id)
    assert queued["job_type"] == "transaction.ingest"
    assert queued["status"] == JobStatus.QUEUED.value
    assert queued["progress"] == 0
    assert queued["result_ref"] is None
    assert queued["error_message"] is None
    assert queued["transaction_id"] is None

    await update_job_progress(db_session, job.id, 45)
    await db_session.commit()

    processing = await poll(client, job.id, owner_auth)
    assert processing["status"] == JobStatus.PROCESSING.value
    assert processing["progress"] == 45

    await complete_job(db_session, job.id, result_ref="local://exports/ingest-batch.json")
    await db_session.commit()

    completed = await poll(client, job.id, owner_auth)
    assert completed["status"] == JobStatus.COMPLETED.value
    assert completed["progress"] == 100
    assert completed["result_ref"] == "local://exports/ingest-batch.json"
    assert datetime.fromisoformat(completed["updated_at"]) >= datetime.fromisoformat(
        completed["created_at"]
    )


async def test_a_failed_job_reports_its_error(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    owner, owner_auth = await provision(
        client,
        db_session,
        subject_id="0a1b2c3d-0000-4000-8000-0000000000e2",
        email="fa.user@agfze.ae",
        name="Daniel Okafor",
        roles=["fa_user"],
    )

    job = await create_job(db_session, job_type="document.extract", created_by_id=owner.id)
    await update_job_progress(db_session, job.id, 20)
    await fail_job(db_session, job.id, error_message="Extraction returned no usable payload.")
    await db_session.commit()

    failed = await poll(client, job.id, owner_auth)
    assert failed["status"] == JobStatus.FAILED.value
    assert failed["error_message"] == "Extraction returned no usable payload."
    assert failed["result_ref"] is None


async def test_a_job_is_not_disclosed_to_an_unrelated_user(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    owner, _ = await provision(
        client,
        db_session,
        subject_id="0a1b2c3d-0000-4000-8000-0000000000e3",
        email="purchase.user@agfze.ae",
        name="Marco Bellini",
        roles=["purchase_user"],
    )
    stranger, stranger_auth = await provision(
        client,
        db_session,
        subject_id="0a1b2c3d-0000-4000-8000-0000000000e4",
        email="sales.user@agfze.ae",
        name="Aisha Rahman",
        roles=["sales_user"],
    )
    auditor, auditor_auth = await provision(
        client,
        db_session,
        subject_id="0a1b2c3d-0000-4000-8000-0000000000e5",
        email="auditor.user@agfze.ae",
        name="Kenji Watanabe",
        roles=["auditor"],
    )

    job = await create_job(db_session, job_type="transaction.ingest", created_by_id=owner.id)
    await db_session.commit()

    refused = await client.get(status_url(job.id), headers=stranger_auth)
    assert refused.status_code == 404
    refused_payload = refused.json()
    assert refused_payload["success"] is False
    assert "not_found" in json.dumps(refused_payload)

    unknown = await client.get(status_url(uuid.uuid4()), headers=stranger_auth)
    assert unknown.status_code == 404
    # A job that exists and a job that never did must be indistinguishable from the outside.
    assert unknown.json()["message"] == refused_payload["message"]

    assert (await poll(client, job.id, auditor_auth))["id"] == str(job.id)

    assert user_may_read_job(owner, job) is True
    assert user_may_read_job(auditor, job) is True
    assert user_may_read_job(stranger, job) is False


async def test_progress_is_clamped_and_promotes_a_queued_job(db_session: AsyncSession) -> None:
    job = await create_job(db_session, job_type="report.render")
    await db_session.commit()

    overshot = await update_job_progress(db_session, job.id, 150)
    assert overshot.progress == 100
    assert overshot.status == JobStatus.PROCESSING.value

    undershot = await update_job_progress(db_session, job.id, -20)
    assert undershot.progress == 0
    await db_session.commit()

    # The round-trip proves the clamped values also satisfy the progress_range check constraint.
    await db_session.refresh(job)
    assert job.progress == 0
    assert job.status == JobStatus.PROCESSING.value


async def test_an_unknown_job_is_reported_as_missing(db_session: AsyncSession) -> None:
    assert await get_job(db_session, uuid.uuid4()) is None
    with pytest.raises(NotFoundError):
        await update_job_progress(db_session, uuid.uuid4(), 10)

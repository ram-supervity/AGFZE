"""The integration hub: what genuinely happened to each posting, and nothing more.

One claim is under test more than any other, and it is tested from several directions because it
is the claim that would matter most if it were false: a job says `succeeded` only when an adapter
really succeeded or a person really confirmed they finished the posting themselves. With nothing
configured - which is every deployment that ships today - the jobs reach `awaiting_manual_action`,
which is neither a success nor a failure, and the tests assert that specific value rather than
merely "not succeeded".

The other claims: the tracker client writes rows and never files; the three jobs are genuinely
independent; a job waiting on a person is never picked up by the retry sweep; the exception on
final failure is a real, technical-support-owned case opened through Step 4's own function; and
`Committed` is reachable only when all three are resolved.
"""

from __future__ import annotations

from datetime import timedelta
from itertools import pairwise

import httpx
import pymupdf
import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.base import utcnow
from app.models.audit import AuditEvent as AuditEventRow
from app.models.enums import (
    DocumentPackType,
    DocumentSource,
    DocumentType,
    ExceptionCategory,
    ExtractionStatus,
    IntegrationTargetSystem,
    TransactionStatus,
)
from app.models.governance import ExceptionCase
from app.models.intake import Document
from app.models.integration import DocumentPack, IntegrationJob
from app.services.graph_service import GraphClient
from app.services.integration import document_packs, integration_service
from app.services.integration.adapters import IntegrationOutcome
from app.services.integration.dms import DmsAdapter
from app.services.integration.sap import SapAdapter
from app.services.integration.tracker import TrackerAdapter
from tests.utils.integration import (
    AWAITING,
    FAILED,
    QUEUED,
    SUCCEEDED,
    StubAdapter,
    all_stubbed,
    approved_transaction,
    job_for,
    statuses,
    use_adapter,
)
from tests.utils.sales import sales_transaction
from tests.utils.transactions import make_request, make_transaction

pytestmark = pytest.mark.usefixtures("patched_jwks")

BASE = "/api/v1/integrations"
TRACKER = IntegrationTargetSystem.TRACKER.value
SAP = IntegrationTargetSystem.SAP.value
DMS = IntegrationTargetSystem.DMS.value


async def admin_headers(signed_in):
    return await signed_in(
        "0a1b2c3d-0000-4000-8000-00000000e001",
        "integration.support@agfze.ae",
        "Ayesha Karim",
        ["admin"],
    )


async def purchase_headers(signed_in):
    return await signed_in(
        "0a1b2c3d-0000-4000-8000-00000000e002",
        "purchase.desk@agfze.ae",
        "Marco Bellini",
        ["purchase_user"],
    )


def pdf_bytes(text: str) -> bytes:
    """A real, readable one-page PDF. The pack tests merge these, not fixtures of merges."""
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), text, fontsize=12, fontname="helv")
    rendered = bytes(document.tobytes())
    document.close()
    return rendered


# --- job creation --------------------------------------------------------------------------------


async def test_an_approved_transaction_gets_exactly_three_independent_jobs(
    db_session: AsyncSession,
) -> None:
    transaction = await approved_transaction(db_session, batch_number="I2626-71")

    async with all_stubbed():
        await integration_service.create_jobs(db_session, transaction)
        await db_session.commit()

    jobs = await integration_service.jobs_for(db_session, transaction.id)
    assert [job.target_system for job in jobs] == [TRACKER, SAP, DMS]
    assert {job.status for job in jobs} == {QUEUED}
    assert {job.attempt_count for job in jobs} == {0}
    assert all(job.completed_manually is False for job in jobs)
    assert transaction.status == TransactionStatus.INTEGRATION_PENDING.value


async def test_creating_jobs_twice_does_not_produce_a_second_set(
    db_session: AsyncSession,
) -> None:
    transaction = await approved_transaction(db_session, batch_number="I2626-72")

    await integration_service.create_jobs(db_session, transaction)
    await integration_service.create_jobs(db_session, transaction)
    await db_session.commit()

    assert (
        await db_session.scalar(
            select(func.count(IntegrationJob.id)).where(
                IntegrationJob.transaction_id == transaction.id
            )
        )
        == 3
    )


async def test_one_target_failing_never_stops_the_other_two_being_attempted(
    db_session: AsyncSession,
) -> None:
    """The whole reason these are three rows rather than one status on the transaction."""
    transaction = await approved_transaction(db_session, batch_number="I2626-73")

    async with all_stubbed(
        tracker=IntegrationOutcome.succeeded("Tracker!row 12"),
        dms=IntegrationOutcome.succeeded("DMS-778"),
    ) as stubs:
        stubs[SAP].raises = RuntimeError("SAP fell over")
        await integration_service.create_jobs(db_session, transaction)
        await integration_service.dispatch(db_session, transaction)
        await db_session.commit()

        assert stubs[TRACKER].calls == 1
        assert stubs[DMS].calls == 1

    jobs = statuses(await integration_service.jobs_for(db_session, transaction.id))
    assert jobs[TRACKER] == SUCCEEDED
    assert jobs[DMS] == SUCCEEDED
    # An adapter that raised is a failing integration, retried rather than lost.
    assert jobs[SAP] == QUEUED
    assert transaction.status == TransactionStatus.INTEGRATION_PENDING.value


async def test_deciding_an_approval_raises_and_runs_the_three_jobs(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    from tests.utils.governance import seeded_transaction

    _, preparer = await purchase_headers(signed_in)
    _, approver = await signed_in(
        "0a1b2c3d-0000-4000-8000-00000000e003",
        "hod.desk@agfze.ae",
        "Priya Raghunathan",
        ["approver_hod"],
    )
    transaction = await seeded_transaction(db_session, batch_number="I2626-74")
    submitted = await client.post(f"/api/v1/transactions/{transaction.id}/submit", headers=preparer)
    assert submitted.status_code == 200, submitted.text

    from app.models.governance import ApprovalTask

    task = (
        await db_session.scalars(
            select(ApprovalTask).where(ApprovalTask.transaction_id == transaction.id)
        )
    ).one()

    response = await client.post(
        f"/api/v1/approvals/{task.id}/decide", headers=approver, json={"decision": "approved"}
    )
    assert response.status_code == 200, response.text
    # Nothing was configured, so nothing was posted - and the message says so rather than
    # implying the deal reached SAP.
    assert "complete by hand" in response.json()["message"]

    await db_session.refresh(transaction)
    jobs = await integration_service.jobs_for(db_session, transaction.id)
    assert len(jobs) == 3
    assert set(statuses(jobs).values()) == {AWAITING}
    assert transaction.status == TransactionStatus.INTEGRATION_PENDING.value


# --- the unconfigured deployment, which is every deployment today --------------------------------


async def test_with_no_sap_or_dms_url_both_jobs_reach_awaiting_manual_action(
    db_session: AsyncSession,
) -> None:
    """The single most important assertion in this module.

    Not "did not succeed" - the specific, honest fifth status, immediately, with the payload a
    person needs in front of them.
    """
    assert not settings.sap_configured
    assert not settings.dms_configured
    transaction = await sales_transaction(db_session, batch_number="I2626-75")
    transaction.status = TransactionStatus.APPROVED.value
    await db_session.commit()

    await integration_service.create_jobs(db_session, transaction)
    await integration_service.dispatch(db_session, transaction)
    await db_session.commit()

    sap = await job_for(db_session, transaction.id, SAP)
    dms = await job_for(db_session, transaction.id, DMS)
    for job in (sap, dms):
        assert job.status == AWAITING
        assert job.external_reference is None
        assert job.failure_reason is None
        assert job.completed_manually is False
        assert job.manual_instruction
    # The SAP payload is real, structured, and made of this transaction's own figures.
    assert sap.prepared_payload["trade_contract"]["batch_number"] == "I2626-75"
    assert sap.prepared_payload["deal_price_record"]["currency"] == "USD"
    # And the DMS one points at a pack that has genuinely been compiled and stored.
    assert dms.prepared_payload["packs"]


async def test_an_unconfigured_tracker_is_prepared_for_a_person_not_skipped(
    db_session: AsyncSession,
) -> None:
    assert not settings.tracker_configured
    transaction = await approved_transaction(db_session, batch_number="I2626-76")

    await integration_service.create_jobs(db_session, transaction)
    await integration_service.dispatch(db_session, transaction)
    await db_session.commit()

    job = await job_for(db_session, transaction.id, TRACKER)
    assert job.status == AWAITING
    assert job.prepared_payload["tracker_row"]["batch_number"] == "I2626-76"


async def test_nothing_reaches_committed_while_a_job_waits_on_a_person(
    db_session: AsyncSession,
) -> None:
    transaction = await approved_transaction(db_session, batch_number="I2626-77")

    async with all_stubbed(
        tracker=IntegrationOutcome.succeeded("Tracker!row 3"),
        sap=IntegrationOutcome.succeeded("SAP-4400010101"),
    ):
        await integration_service.create_jobs(db_session, transaction)
        await integration_service.dispatch(db_session, transaction)
        await db_session.commit()

    await db_session.refresh(transaction)
    assert statuses(await integration_service.jobs_for(db_session, transaction.id))[DMS] == AWAITING
    assert transaction.status == TransactionStatus.INTEGRATION_PENDING.value


# --- the tracker client ---------------------------------------------------------------------------


class FakeGraphResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def json(self) -> dict:
        return self._payload


@pytest.fixture
def tracker_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    """A confirmed workbook, sheet, table and column mapping - the one thing that is unknown."""
    monkeypatch.setattr(settings, "TRACKER_DRIVE_ID", "b!drive-id")
    monkeypatch.setattr(settings, "TRACKER_WORKBOOK_ITEM_ID", "01ITEMID")
    monkeypatch.setattr(settings, "TRACKER_WORKSHEET_NAME", "Tracker")
    monkeypatch.setattr(settings, "TRACKER_TABLE_NAME", "TrackerTable")
    monkeypatch.setattr(settings, "TRACKER_KEY_COLUMN", "Batch Number")
    monkeypatch.setattr(
        settings,
        "TRACKER_COLUMN_MAP",
        {
            "batch_number": "Batch Number",
            "counterparty": "Supplier",
            "quantity_mt": "Qty (MT)",
            "amount": "Value",
        },
    )


def graph_recorder(rows: list[dict]) -> tuple[list[tuple[str, str, dict | None]], object]:
    """Stand in for Graph itself, recording exactly which row-level calls were made."""
    calls: list[tuple[str, str, dict | None]] = []

    async def _request(self, method, url, *, json_body=None, accept="application/json"):
        calls.append((method, url, json_body))
        if "/columns" in url:
            return FakeGraphResponse(
                {
                    "value": [
                        {"index": 0, "name": "Batch Number"},
                        {"index": 1, "name": "Supplier"},
                        {"index": 2, "name": "Qty (MT)"},
                        {"index": 3, "name": "Value"},
                        {"index": 4, "name": "Desk notes"},
                    ]
                }
            )
        if "/rows?" in url:
            return FakeGraphResponse({"value": rows})
        if "/rows/add" in url:
            return FakeGraphResponse({"index": len(rows)})
        return FakeGraphResponse({})

    return calls, _request


async def test_the_tracker_client_patches_one_row_and_never_opens_the_workbook(
    monkeypatch: pytest.MonkeyPatch, tracker_configuration: None
) -> None:
    existing = [
        {"index": 0, "values": [["I2626-01", "Someone else", "10", "1000", "keep me"]]},
        {"index": 1, "values": [["I2626-80", "Old supplier", "1", "1", "do not lose this"]]},
    ]
    calls, request = graph_recorder(existing)
    monkeypatch.setattr(GraphClient, "_request", request)

    client = GraphClient()
    result = await client.upsert_tracker_row(
        {
            "batch_number": "I2626-80",
            "counterparty": "Emirates Metal Trading LLC",
            "quantity_mt": "24.5",
            "amount": "199062.50",
        }
    )

    assert result.created is False
    assert result.row_index == 1
    methods = [method for method, _url, _body in calls]
    assert "PATCH" in methods
    # The row-level guarantee, asserted rather than assumed: every call is a workbook table
    # operation, none is a file read or write, and nothing was uploaded back.
    for method, url, _body in calls:
        assert "/workbook/" in url
        assert "/content" not in url
        assert method in ("GET", "PATCH", "POST")
    assert "PUT" not in methods

    patched = next(body for method, _url, body in calls if method == "PATCH")
    assert patched["values"][0][0] == "I2626-80"
    assert patched["values"][0][1] == "Emirates Metal Trading LLC"
    # A column this platform does not own survives the write untouched.
    assert patched["values"][0][4] == "do not lose this"


async def test_the_tracker_client_appends_a_row_when_the_batch_is_not_there_yet(
    monkeypatch: pytest.MonkeyPatch, tracker_configuration: None
) -> None:
    calls, request = graph_recorder([])
    monkeypatch.setattr(GraphClient, "_request", request)

    result = await GraphClient().upsert_tracker_row({"batch_number": "I2626-81"})

    assert result.created is True
    assert any(url.endswith("/rows/add") for _method, url, _body in calls)


async def test_a_configured_tracker_job_records_the_row_it_wrote(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tracker_configuration: None
) -> None:
    _calls, request = graph_recorder([])
    monkeypatch.setattr(GraphClient, "_request", request)
    transaction = await approved_transaction(db_session, batch_number="I2626-82")

    with use_adapter(TRACKER, TrackerAdapter()):
        await integration_service.create_jobs(db_session, transaction)
        await integration_service.dispatch(db_session, transaction)
        await db_session.commit()

    job = await job_for(db_session, transaction.id, TRACKER)
    assert job.status == SUCCEEDED
    assert job.external_reference == "TrackerTable!row 0"
    assert job.completed_manually is False


# --- a configured SAP and DMS endpoint -------------------------------------------------------------


def mock_sap(handler) -> SapAdapter:
    return SapAdapter(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


@pytest.fixture
def sap_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SAP_API_BASE_URL", "https://sap.test")
    monkeypatch.setattr(settings, "SAP_POSTING_PATH", "api/trade-contracts")


async def test_a_configured_sap_endpoint_is_genuinely_called_and_its_reference_recorded(
    db_session: AsyncSession, sap_configuration: None
) -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen.append(json.loads(request.content))
        assert str(request.url) == "https://sap.test/api/trade-contracts"
        return httpx.Response(201, json={"document_number": "4400010101"})

    transaction = await approved_transaction(db_session, batch_number="I2626-83")
    with use_adapter(SAP, mock_sap(handler)):
        await integration_service.create_jobs(db_session, transaction)
        await integration_service.dispatch(db_session, transaction)
        await db_session.commit()

    job = await job_for(db_session, transaction.id, SAP)
    assert job.status == SUCCEEDED
    assert job.external_reference == "4400010101"
    assert job.completed_manually is False
    # What was posted is the transaction's own figures, under this platform's own field names.
    assert seen[0]["trade_contract"]["batch_number"] == "I2626-83"


async def test_a_sap_rejection_is_a_real_failure_and_never_a_quiet_success(
    db_session: AsyncSession, sap_configuration: None
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"error": "material unknown"})

    transaction = await approved_transaction(db_session, batch_number="I2626-84")
    with use_adapter(SAP, mock_sap(handler)):
        await integration_service.create_jobs(db_session, transaction)
        await integration_service.dispatch(db_session, transaction)
        await db_session.commit()

    job = await job_for(db_session, transaction.id, SAP)
    # 422 is not worth retrying, so the job is failed at once rather than four times over.
    assert job.status == FAILED
    assert "422" in job.failure_reason
    assert job.external_reference is None


async def test_a_sap_success_with_no_document_number_is_not_treated_as_a_posting(
    db_session: AsyncSession, sap_configuration: None
) -> None:
    """A 200 that evidences nothing is not evidence of anything."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ok"})

    transaction = await approved_transaction(db_session, batch_number="I2626-85")
    with use_adapter(SAP, mock_sap(handler)):
        await integration_service.create_jobs(db_session, transaction)
        await integration_service.dispatch(db_session, transaction)
        await db_session.commit()

    job = await job_for(db_session, transaction.id, SAP)
    assert job.status == FAILED
    assert job.external_reference is None


async def test_a_configured_dms_endpoint_uploads_the_compiled_pack(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, storage_root
) -> None:
    monkeypatch.setattr(settings, "DMS_API_BASE_URL", "https://dms.test")
    monkeypatch.setattr(settings, "DMS_UPLOAD_PATH", "documents")
    uploaded: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        uploaded.append(request.content)
        return httpx.Response(201, json={"document_id": "DMS-90001"})

    transaction = await approved_transaction(db_session, batch_number="I2626-86")
    adapter = DmsAdapter(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with use_adapter(DMS, adapter):
        await integration_service.create_jobs(db_session, transaction)
        await integration_service.dispatch(db_session, transaction)
        await db_session.commit()

    job = await job_for(db_session, transaction.id, DMS)
    assert job.status == SUCCEEDED
    assert job.external_reference == "DMS-90001"
    assert uploaded
    pack = await db_session.scalar(
        select(DocumentPack).where(DocumentPack.transaction_id == transaction.id)
    )
    assert pack.dms_document_id == "DMS-90001"
    assert pack.dms_uploaded_at is not None


# --- manual completion ------------------------------------------------------------------------------


async def _awaiting_job(db_session: AsyncSession, batch_number: str, target: str = SAP):
    transaction = await approved_transaction(db_session, batch_number=batch_number)
    await integration_service.create_jobs(db_session, transaction)
    await integration_service.dispatch(db_session, transaction)
    await db_session.commit()
    return transaction, await job_for(db_session, transaction.id, target)


async def test_manual_completion_succeeds_and_is_permanently_marked_as_manual(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    user, headers = await admin_headers(signed_in)
    _transaction, job = await _awaiting_job(db_session, "I2626-87")

    response = await client.post(
        f"{BASE}/jobs/{job.id}/complete-manual",
        headers=headers,
        json={
            "external_reference": "4400010199",
            "note": "Keyed into SAP by hand from the prepared payload; document number confirmed.",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert body["status"] == SUCCEEDED
    assert body["completed_manually"] is True
    assert body["external_reference"] == "4400010199"
    assert body["completed_manually_by_name"] == "Ayesha Karim"

    await db_session.refresh(job)
    assert job.completed_manually is True
    assert job.completed_manually_by_id == user.id
    assert job.manual_note.startswith("Keyed into SAP")

    # And the trail says, in as many words, that a person did this.
    events = list(
        (
            await db_session.scalars(
                select(AuditEventRow).where(
                    AuditEventRow.event_type
                    == integration_service.AuditEvent.JOB_COMPLETED_MANUALLY
                )
            )
        ).all()
    )
    assert len(events) == 1
    assert events[0].actor_id == user.id
    assert events[0].event_metadata["completed_manually"] is True
    assert events[0].event_metadata["note"]


@pytest.mark.parametrize(
    "payload",
    [
        {"external_reference": "", "note": "A perfectly good reason, at length."},
        {"external_reference": "4400010199", "note": ""},
        {"external_reference": "4400010199", "note": "too short"},
    ],
)
async def test_manual_completion_requires_both_a_reference_and_a_reason(
    client: AsyncClient, db_session: AsyncSession, signed_in, payload: dict
) -> None:
    _user, headers = await admin_headers(signed_in)
    _transaction, job = await _awaiting_job(db_session, f"I2626-88{len(payload['note'])}")

    response = await client.post(
        f"{BASE}/jobs/{job.id}/complete-manual", headers=headers, json=payload
    )
    assert response.status_code in (409, 422), response.text

    await db_session.refresh(job)
    assert job.status == AWAITING
    assert job.completed_manually is False


async def test_only_an_administrator_may_confirm_a_manual_completion(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    _user, headers = await purchase_headers(signed_in)
    _transaction, job = await _awaiting_job(db_session, "I2626-89")

    response = await client.post(
        f"{BASE}/jobs/{job.id}/complete-manual",
        headers=headers,
        json={"external_reference": "X", "note": "I would rather like this to be done."},
    )
    assert response.status_code == 403
    await db_session.refresh(job)
    assert job.status == AWAITING


async def test_a_job_awaiting_a_person_cannot_be_retried_instead(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    """Retry and manual completion are different actions because they mean different things."""
    _user, headers = await admin_headers(signed_in)
    _transaction, job = await _awaiting_job(db_session, "I2626-90")

    response = await client.post(f"{BASE}/jobs/{job.id}/retry", headers=headers)
    assert response.status_code == 409
    assert response.json()["errors"][0]["code"] == "not_retryable"


# --- retry, backoff and the exception at the end of it ----------------------------------------------


def test_the_backoff_starts_short_and_roughly_doubles_to_a_ceiling() -> None:
    delays = [integration_service.backoff_seconds(attempt) for attempt in range(1, 6)]
    assert delays[0] == settings.INTEGRATION_RETRY_BASE_SECONDS
    assert delays == sorted(delays)
    for earlier, later in pairwise(delays):
        assert later >= earlier * 2 or later == settings.INTEGRATION_RETRY_MAX_SECONDS
    assert integration_service.backoff_seconds(50) == settings.INTEGRATION_RETRY_MAX_SECONDS


async def test_a_transient_failure_is_retried_with_a_growing_delay_then_fails_for_good(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "INTEGRATION_MAX_ATTEMPTS", 3)
    transaction = await approved_transaction(db_session, batch_number="I2626-91")
    stub = StubAdapter(SAP, IntegrationOutcome.failed("SAP could not be reached.", retryable=True))

    with use_adapter(SAP, stub):
        await integration_service.create_jobs(db_session, transaction)
        await integration_service.dispatch(db_session, transaction)
        await db_session.commit()

        job = await job_for(db_session, transaction.id, SAP)
        assert job.status == QUEUED
        assert job.attempt_count == 1
        first_due = integration_service.next_attempt_at(job)

        # Not due yet, so the sweep leaves it exactly where it is.
        assert await integration_service.due_jobs(db_session, limit=10) == []

        delays: list[float] = []
        while job.status == QUEUED:
            previous_due = integration_service.next_attempt_at(job)
            # Pretend the wait has elapsed rather than actually waiting it out.
            job.last_attempted_at = utcnow() - timedelta(
                seconds=integration_service.backoff_seconds(job.attempt_count) + 1
            )
            await db_session.flush()
            assert job in await integration_service.due_jobs(db_session, limit=10)
            await integration_service.run_sweep(db_session, limit=10)
            delays.append(integration_service.backoff_seconds(max(1, job.attempt_count - 1)))
            assert previous_due is not None

        assert job.attempt_count == 3
        assert job.status == FAILED
        assert delays == sorted(delays)
        assert first_due is not None
        assert stub.calls == 3
        await db_session.commit()

    # A real, technical-support-owned case, in the category that has been registered and dormant
    # since Step 4 and is real from this step onwards.
    case = await db_session.scalar(
        select(ExceptionCase).where(ExceptionCase.transaction_id == transaction.id)
    )
    assert case is not None
    assert case.exception_type == ExceptionCategory.INTEGRATION_FAILURE.value
    assert case.owner_role == "admin"
    assert case.field_name == "integration.sap"
    assert case.resolved_at is None

    await db_session.refresh(transaction)
    assert transaction.status == TransactionStatus.INTEGRATION_PENDING.value


async def test_the_sweep_never_picks_up_a_job_that_is_waiting_on_a_person(
    db_session: AsyncSession,
) -> None:
    transaction = await approved_transaction(db_session, batch_number="I2626-92")
    await integration_service.create_jobs(db_session, transaction)
    await integration_service.dispatch(db_session, transaction)
    await db_session.commit()

    jobs = await integration_service.jobs_for(db_session, transaction.id)
    assert set(statuses(jobs).values()) == {AWAITING}
    attempts = {job.id: job.attempt_count for job in jobs}

    # Age every one of them well past any conceivable backoff, then sweep repeatedly.
    for job in jobs:
        job.last_attempted_at = utcnow() - timedelta(days=7)
    await db_session.flush()

    for _ in range(3):
        assert await integration_service.due_jobs(db_session, limit=50) == []
        result = await integration_service.run_sweep(db_session, limit=50)
        assert result.attempted == 0
    await db_session.commit()

    for job in await integration_service.jobs_for(db_session, transaction.id):
        assert job.status == AWAITING
        assert job.attempt_count == attempts[job.id]


async def test_an_administrator_can_retry_a_failed_job_outside_its_backoff(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    _user, headers = await admin_headers(signed_in)
    transaction = await approved_transaction(db_session, batch_number="I2626-93")
    failing = StubAdapter(SAP, IntegrationOutcome.failed("SAP said no.", retryable=False))

    with use_adapter(SAP, failing):
        await integration_service.create_jobs(db_session, transaction)
        await integration_service.dispatch(db_session, transaction)
        await db_session.commit()
    job = await job_for(db_session, transaction.id, SAP)
    assert job.status == FAILED

    with use_adapter(SAP, StubAdapter(SAP, IntegrationOutcome.succeeded("4400010200"))):
        response = await client.post(f"{BASE}/jobs/{job.id}/retry", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert body["status"] == SUCCEEDED
    assert body["external_reference"] == "4400010200"
    # An automated success, and marked as one.
    assert body["completed_manually"] is False


# --- document packs -----------------------------------------------------------------------------------


async def _stored(db_session: AsyncSession, storage, document: Document, text: str) -> None:
    await storage.upload(document.storage_ref, pdf_bytes(text), "application/pdf")


async def test_the_purchase_pack_merges_the_invoice_and_contract_it_is_meant_to(
    db_session: AsyncSession, storage_root
) -> None:
    from tests.utils.transactions import contract_values, invoice_values, make_document

    request = await make_request(db_session)
    transaction = await make_transaction(
        db_session,
        request=request,
        batch_number="I2626-94",
        status=TransactionStatus.APPROVED.value,
    )
    invoice = await make_document(
        db_session,
        request,
        values=invoice_values(),
        document_type=DocumentType.INVOICE.value,
        filename="supplier-invoice.pdf",
        transaction_id=transaction.id,
    )
    contract = await make_document(
        db_session,
        request,
        values=contract_values(),
        document_type=DocumentType.CONTRACT.value,
        filename="purchase-contract.pdf",
        transaction_id=transaction.id,
    )
    await _stored(db_session, storage_root, invoice, "SUPPLIER INVOICE")
    await _stored(db_session, storage_root, contract, "PURCHASE CONTRACT")
    await db_session.commit()

    results = await document_packs.compile_packs(db_session, transaction)
    await db_session.commit()

    assert [result.pack.pack_type for result in results] == [DocumentPackType.PURCHASE_FILE.value]
    pack = results[0].pack
    assert pack.filename.startswith("ADV-")
    assert pack.filename.endswith(".pdf")
    assert set(pack.source_document_ids) == {str(invoice.id), str(contract.id)}
    assert results[0].merged_ids == [str(invoice.id), str(contract.id)]

    merged = await storage_root.download(pack.storage_ref)
    with pymupdf.open(stream=merged, filetype="pdf") as opened:
        # The contents page, plus one page from each source document.
        assert opened.page_count == 3
        text = "\n".join(opened.load_page(index).get_text() for index in range(3))
    assert "SUPPLIER INVOICE" in text
    assert "PURCHASE CONTRACT" in text


async def test_a_step_five_draft_is_an_input_to_the_sales_pack_not_a_second_copy_of_it(
    db_session: AsyncSession, storage_root
) -> None:
    """`DocumentPack` compiles what Step 5 produced; it never re-produces it."""
    transaction = await sales_transaction(db_session, batch_number="I2626-95")
    draft = Document(
        request_id=None,
        transaction_id=transaction.id,
        filename="SO-I2626-95-24.5-Prov-contract.docx",
        content_type=("application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        byte_size=2048,
        document_type=DocumentType.DRAFT_CONTRACT.value,
        original_document_type=DocumentType.DRAFT_CONTRACT.value,
        storage_ref=f"documents/generated/{transaction.id}/draft.docx",
        page_image_refs=[],
        content_hash="d" * 64,
        extraction_status=ExtractionStatus.NOT_APPLICABLE.value,
        source=DocumentSource.GENERATED.value,
    )
    db_session.add(draft)
    await db_session.flush()
    await db_session.commit()

    drafts_before = await db_session.scalar(
        select(func.count(Document.id)).where(
            Document.source == DocumentSource.GENERATED.value,
            Document.transaction_id == transaction.id,
        )
    )

    results = await document_packs.compile_packs(db_session, transaction)
    await db_session.commit()

    sales = next(
        result
        for result in results
        if result.pack.pack_type == DocumentPackType.SALES_BANK_DOCS.value
    )
    assert sales.pack.filename.startswith("SO-I2626-95-")
    # The draft went in as a source, by its own document id.
    assert str(draft.id) in sales.pack.source_document_ids
    # A DOCX cannot be merged into a PDF, so it is listed honestly rather than dropped.
    assert draft.filename in sales.attached_separately
    # And nothing generated a second draft to put in the pack.
    assert (
        await db_session.scalar(
            select(func.count(Document.id)).where(
                Document.source == DocumentSource.GENERATED.value,
                Document.transaction_id == transaction.id,
            )
        )
        == drafts_before
    )

    merged = await storage_root.download(sales.pack.storage_ref)
    with pymupdf.open(stream=merged, filetype="pdf") as opened:
        contents = opened.load_page(0).get_text()
    assert draft.filename in contents
    assert "attached separately" in contents


async def test_recompiling_replaces_the_pack_rather_than_leaving_two(
    db_session: AsyncSession, storage_root
) -> None:
    transaction = await approved_transaction(db_session, batch_number="I2626-96")

    await document_packs.compile_packs(db_session, transaction)
    await document_packs.compile_packs(db_session, transaction)
    await db_session.commit()

    assert (
        await db_session.scalar(
            select(func.count(DocumentPack.id)).where(DocumentPack.transaction_id == transaction.id)
        )
        == 1
    )


# --- reaching Committed --------------------------------------------------------------------------------


async def test_committed_is_reached_only_once_all_three_jobs_are_resolved(
    db_session: AsyncSession,
) -> None:
    transaction = await approved_transaction(db_session, batch_number="I2626-97")

    async with all_stubbed(
        tracker=IntegrationOutcome.succeeded("Tracker!row 9"),
        sap=IntegrationOutcome.succeeded("4400010300"),
        dms=IntegrationOutcome.succeeded("DMS-1234"),
    ):
        await integration_service.create_jobs(db_session, transaction)
        await integration_service.dispatch(db_session, transaction)
        await db_session.commit()

    await db_session.refresh(transaction)
    assert transaction.status == TransactionStatus.COMMITTED.value
    # And never past it. `Closed` is a declared state with no code path that sets it.
    assert transaction.closed_at is None

    committed = await db_session.scalar(
        select(func.count(AuditEventRow.id)).where(
            AuditEventRow.event_type == integration_service.AuditEvent.TRANSACTION_COMMITTED
        )
    )
    assert committed == 1


async def test_a_failed_job_keeps_the_transaction_out_of_committed(
    db_session: AsyncSession,
) -> None:
    transaction = await approved_transaction(db_session, batch_number="I2626-98")

    async with all_stubbed(
        tracker=IntegrationOutcome.succeeded("Tracker!row 10"),
        sap=IntegrationOutcome.failed("SAP said no.", retryable=False),
        dms=IntegrationOutcome.succeeded("DMS-1235"),
    ):
        await integration_service.create_jobs(db_session, transaction)
        await integration_service.dispatch(db_session, transaction)
        await db_session.commit()

    await db_session.refresh(transaction)
    assert transaction.status == TransactionStatus.INTEGRATION_PENDING.value


async def test_a_manual_completion_reaches_committed_and_stays_visibly_manual(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    """The distinction never affects whether Committed is reached, and never stops being visible."""
    _user, headers = await admin_headers(signed_in)
    transaction = await approved_transaction(db_session, batch_number="I2626-99")

    async with all_stubbed(
        tracker=IntegrationOutcome.succeeded("Tracker!row 11"),
        dms=IntegrationOutcome.succeeded("DMS-1236"),
    ):
        await integration_service.create_jobs(db_session, transaction)
        await integration_service.dispatch(db_session, transaction)
        await db_session.commit()

    job = await job_for(db_session, transaction.id, SAP)
    response = await client.post(
        f"{BASE}/jobs/{job.id}/complete-manual",
        headers=headers,
        json={
            "external_reference": "4400010400",
            "note": "Posted through the assisted flow and confirmed against SAP directly.",
        },
    )
    assert response.status_code == 200, response.text

    # This session watched the API write through a connection of its own, so what it holds is a
    # snapshot from before the call.
    db_session.expire_all()
    await db_session.refresh(transaction)
    assert transaction.status == TransactionStatus.COMMITTED.value

    jobs = await integration_service.jobs_for(db_session, transaction.id)
    manual = [job.target_system for job in jobs if job.completed_manually]
    assert manual == [SAP]


# --- the monitor and the workspace panel --------------------------------------------------------------


async def test_the_monitor_lists_and_filters_jobs_for_an_administrator(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    _user, headers = await admin_headers(signed_in)
    transaction = await approved_transaction(db_session, batch_number="I2626-A1")
    await integration_service.create_jobs(db_session, transaction)
    await integration_service.dispatch(db_session, transaction)
    await db_session.commit()

    response = await client.get(f"{BASE}/jobs", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert body["page"]["total"] == 3
    assert body["counts_by_target"] == {"tracker": 1, "sap": 1, "dms": 1}
    assert body["counts_by_status"][AWAITING] == 3
    # The screen is told plainly which targets this deployment can post to at all, so a job
    # waiting on a person never reads as a fault.
    assert body["configured_targets"] == {"tracker": False, "sap": False, "dms": False}
    assert all(row["batch_number"] == "I2626-A1" for row in body["items"])

    filtered = await client.get(f"{BASE}/jobs?target_system=sap", headers=headers)
    assert [row["target_system"] for row in filtered.json()["data"]["items"]] == ["sap"]

    by_status = await client.get(f"{BASE}/jobs?status={SUCCEEDED}", headers=headers)
    assert by_status.json()["data"]["items"] == []


async def test_the_monitor_can_be_narrowed_to_one_transaction_s_jobs(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    """How a workspace links through: the three jobs of one deal, not the whole queue."""
    _user, headers = await admin_headers(signed_in)
    wanted = await approved_transaction(db_session, batch_number="I2626-A4")
    other = await approved_transaction(db_session, batch_number="I2626-A5")
    for transaction in (wanted, other):
        await integration_service.create_jobs(db_session, transaction)
        await integration_service.dispatch(db_session, transaction)
    await db_session.commit()

    response = await client.get(f"{BASE}/jobs?transaction_id={wanted.id}", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert body["page"]["total"] == 3
    assert {row["batch_number"] for row in body["items"]} == {"I2626-A4"}


async def test_the_monitor_is_closed_to_everybody_but_an_administrator(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    _user, headers = await purchase_headers(signed_in)
    response = await client.get(f"{BASE}/jobs", headers=headers)
    assert response.status_code == 403


async def test_a_transaction_carries_its_three_job_statuses_for_any_signed_in_reader(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    _user, headers = await purchase_headers(signed_in)
    transaction = await approved_transaction(db_session, batch_number="I2626-A2")
    await integration_service.create_jobs(db_session, transaction)
    await integration_service.dispatch(db_session, transaction)
    await db_session.commit()

    response = await client.get(f"/api/v1/transactions/{transaction.id}", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()["data"]
    jobs = body["integration_jobs"]
    assert [job["target_system"] for job in jobs] == ["tracker", "sap", "dms"]
    assert {job["status"] for job in jobs} == {AWAITING}
    assert all(job["completed_manually"] is False for job in jobs)
    # The preparing desk may read the status; only Admin may act on it.
    assert body["can_manage_integrations"] is False


async def test_a_credential_never_appears_in_a_prepared_payload_or_a_response(
    client: AsyncClient, db_session: AsyncSession, signed_in, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "SAP_API_USERNAME", "sap-service-account")
    monkeypatch.setattr(settings, "SAP_API_PASSWORD", "super-secret-password")
    monkeypatch.setattr(settings, "DMS_API_KEY", "dms-secret-key")
    _user, headers = await admin_headers(signed_in)
    transaction = await approved_transaction(db_session, batch_number="I2626-A3")
    await integration_service.create_jobs(db_session, transaction)
    await integration_service.dispatch(db_session, transaction)
    await db_session.commit()

    response = await client.get(f"{BASE}/jobs", headers=headers)
    body = response.text
    for secret in ("super-secret-password", "dms-secret-key", "sap-service-account"):
        assert secret not in body


async def test_the_transaction_status_vocabulary_has_no_reachable_closed_state() -> None:
    """`Closed` is declared, and this step contains no path that sets it."""
    assert TransactionStatus.CLOSED.value == "closed"
    sources = [
        integration_service.__file__,
        document_packs.__file__,
    ]
    for path in sources:
        with open(path, encoding="utf-8") as handle:
            body = handle.read()
        assert "TransactionStatus.CLOSED" not in body

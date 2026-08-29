"""The sales endpoints, over HTTP, with the real role gates in front of them.

`POST /transactions/{id}/sales-leg` and `POST /transactions/{id}/generate-draft` are the two this
step adds. Everything else it touches - the field correction, the submission, the detail read -
is an existing endpoint whose behaviour widened without its contract changing, and that is what
most of these tests are actually about.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditEvent
from app.models.enums import DocumentSource, DocumentType, FixationStatus, Territory
from app.models.intake import Document
from app.models.jobs import BackgroundJob, JobStatus
from app.services import sales_service
from app.services.rules.catalog import CheckKey, RuleId
from tests.utils.sales import (
    CUSTOMER,
    SALES_CONTRACT,
    VALID_CONTRACT_PLAN,
    draft_plan_response,
    sales_transaction,
)
from tests.utils.transactions import make_transaction

BASE = "/api/v1/transactions"

LEG_BODY = {
    "customer_name": CUSTOMER,
    "territory": Territory.INDIA.value,
    "sales_contract_no": SALES_CONTRACT,
    "payment_condition": "CAD",
    "contracted_quantity_mt": "100.000",
    "bl_reference": "MAEU-2026-77812",
    "port_of_discharge": "Nhava Sheva",
}


@pytest.fixture
def model_reply(monkeypatch: pytest.MonkeyPatch):
    def _install(payload: str | Exception):
        async def _raw(prompt, response_schema, images):
            if isinstance(payload, Exception):
                raise payload
            return payload

        monkeypatch.setattr("app.services.gemini_service._generate_raw", _raw)

    return _install


async def _sales_user(signed_in):
    return await signed_in("sales-api", "sales.api@agfze.test", "Sales User", ["sales_user"])


async def _purchase_user(signed_in):
    return await signed_in(
        "purchase-api", "purchase.api@agfze.test", "Purchase User", ["purchase_user"]
    )


# --- attaching the leg ----------------------------------------------------------------------


async def test_a_sales_user_attaches_a_leg_to_an_existing_purchase_transaction(
    patched_jwks, client, db_session: AsyncSession, signed_in
) -> None:
    transaction = await make_transaction(db_session, batch_number="I2626-200")
    await db_session.commit()
    _, headers = await _sales_user(signed_in)

    response = await client.post(
        f"{BASE}/{transaction.id}/sales-leg", headers=headers, json=LEG_BODY
    )

    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["attachment"] == sales_service.Attachment.USER_SELECTED
    assert data["commodity_code_mismatch"] is False

    detail = data["transaction"]
    # `sales_leg` was always a declared field of this response. It simply populates now.
    assert detail["sales_leg"]["customer_name"] == CUSTOMER
    assert detail["sales_leg"]["sales_contract_no"] == SALES_CONTRACT
    assert detail["sales_leg"]["customer_fixation_status"] == FixationStatus.UNFIXED.value
    assert detail["purchase_leg"] is not None
    assert detail["fa_leg"] is None

    # The three sales-specific panels the workspace renders are all served by this one read.
    assert detail["linked_purchase"]["present"] is True
    assert detail["contract_coverage"]["sales_contract_no"] == SALES_CONTRACT
    assert detail["contract_coverage"]["state"] == "partial"
    assert detail["generated_drafts"] == []


async def test_a_purchase_user_may_not_attach_a_sales_leg(
    patched_jwks, client, db_session: AsyncSession, signed_in
) -> None:
    transaction = await make_transaction(db_session, batch_number="I2626-201")
    await db_session.commit()
    _, headers = await _purchase_user(signed_in)

    response = await client.post(
        f"{BASE}/{transaction.id}/sales-leg", headers=headers, json=LEG_BODY
    )

    assert response.status_code == 403


async def test_attaching_twice_is_refused(
    patched_jwks, client, db_session: AsyncSession, signed_in
) -> None:
    transaction = await make_transaction(db_session, batch_number="I2626-202")
    await db_session.commit()
    _, headers = await _sales_user(signed_in)

    first = await client.post(f"{BASE}/{transaction.id}/sales-leg", headers=headers, json=LEG_BODY)
    assert first.status_code == 201

    second = await client.post(f"{BASE}/{transaction.id}/sales-leg", headers=headers, json=LEG_BODY)
    assert second.status_code == 409


async def test_the_attachment_is_audited_with_how_it_was_decided(
    patched_jwks, client, db_session: AsyncSession, signed_in
) -> None:
    transaction = await make_transaction(db_session, batch_number="I2626-203")
    await db_session.commit()
    _, headers = await _sales_user(signed_in)

    await client.post(f"{BASE}/{transaction.id}/sales-leg", headers=headers, json=LEG_BODY)

    event = await db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.event_type == sales_service.AuditEvent.SALES_LEG_ATTACHED
        )
    )
    assert event is not None
    assert event.event_metadata["attachment"] == sales_service.Attachment.USER_SELECTED
    assert event.event_metadata["customer_name"] == CUSTOMER
    assert event.event_metadata["no_purchase_acknowledged"] is False


# --- price fixation through the existing correction endpoint ---------------------------------


async def test_recording_a_fixation_goes_through_the_existing_fields_endpoint(
    patched_jwks, client, db_session: AsyncSession, signed_in
) -> None:
    """No second endpoint. A fixation is a correction, with the same gate and re-validation."""
    transaction = await sales_transaction(db_session, batch_number="I2626-210")
    _, headers = await _sales_user(signed_in)

    response = await client.patch(
        f"{BASE}/{transaction.id}/fields",
        headers=headers,
        json={
            "changes": [
                {"name": "fixation_rate", "value": "8420.00"},
                {"name": "fixation_date", "value": "2026-08-25"},
            ]
        },
    )

    assert response.status_code == 200, response.text
    leg = response.json()["data"]["sales_leg"]
    assert leg["customer_fixation_status"] == FixationStatus.FIXED.value
    assert Decimal(leg["fixation_rate"]) == Decimal("8420.00")

    event = await db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.event_type == sales_service.AuditEvent.PRICE_FIXATION_RECORDED
        )
    )
    assert event is not None
    assert event.event_metadata["status"] == FixationStatus.FIXED.value


async def test_a_sales_user_cannot_correct_the_purchase_leg_through_the_same_endpoint(
    patched_jwks, client, db_session: AsyncSession, signed_in
) -> None:
    transaction = await sales_transaction(db_session, batch_number="I2626-211")
    _, headers = await _sales_user(signed_in)

    response = await client.patch(
        f"{BASE}/{transaction.id}/fields",
        headers=headers,
        json={"changes": [{"name": "supplier_name", "value": "Somebody Else"}]},
    )

    assert response.status_code == 403


# --- BR-07 at the submission gate --------------------------------------------------------------


async def test_submission_is_blocked_until_a_final_bill_of_lading_exists(
    patched_jwks, client, db_session: AsyncSession, signed_in
) -> None:
    """The endpoint did not change. A real BR-07 evaluator is what now stops it."""
    transaction = await sales_transaction(
        db_session, batch_number="I2626-220", with_final_bl=False, with_draft_bl=True
    )
    _, headers = await _sales_user(signed_in)

    response = await client.post(f"{BASE}/{transaction.id}/submit", headers=headers)

    assert response.status_code == 409
    body = response.json()
    assert "BR-07" in body["message"]
    assert "final bill of lading is required before submission" in body["message"]


async def test_submission_succeeds_once_the_original_bill_of_lading_is_attached(
    patched_jwks, client, db_session: AsyncSession, signed_in
) -> None:
    transaction = await sales_transaction(
        db_session, batch_number="I2626-221", with_final_bl=True, with_draft_bl=True
    )
    _, headers = await _sales_user(signed_in)

    response = await client.post(f"{BASE}/{transaction.id}/submit", headers=headers)

    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "approval_pending"


# --- draft generation over the wire --------------------------------------------------------------


async def test_generating_a_draft_returns_a_job_and_lands_a_document(
    patched_jwks, client, db_session: AsyncSession, signed_in, model_reply, storage_root
) -> None:
    model_reply(VALID_CONTRACT_PLAN)
    transaction = await sales_transaction(
        db_session, batch_number="I2626-230", with_final_bl=False, with_draft_bl=True
    )
    # Read once, up front. Polling the job rolls this session back between attempts, which
    # expires every object it holds, and an expired attribute read outside a greenlet is an
    # error rather than a query.
    transaction_id = transaction.id
    _, headers = await _sales_user(signed_in)

    response = await client.post(
        f"{BASE}/{transaction.id}/generate-draft",
        headers=headers,
        json={"document_type": DocumentType.DRAFT_CONTRACT.value},
    )

    assert response.status_code == 202, response.text
    job_id = response.json()["data"]["job_id"]

    # Polled through the job endpoint Step 2 already established; no second mechanism.
    status = await client.get(f"/api/v1/jobs/{job_id}/status", headers=headers)
    assert status.status_code == 200

    job = await _await_job(db_session, job_id)
    assert job.status == JobStatus.COMPLETED.value
    assert job.transaction_id == transaction_id

    document = await db_session.scalar(
        select(Document).where(Document.source == DocumentSource.GENERATED.value)
    )
    assert document is not None
    assert document.request_id is None
    assert document.document_type == DocumentType.DRAFT_CONTRACT.value

    # The draft appears in the transaction's own documents, downloadable through the ordinary
    # signed-URL mechanism and subject to the same access control as any other document.
    detail = await client.get(f"{BASE}/{transaction_id}", headers=headers)
    drafts = detail.json()["data"]["generated_drafts"]
    assert len(drafts) == 1
    assert drafts[0]["version"] == 1
    assert drafts[0]["download_url"]
    assert drafts[0]["generated_by_name"] == "Sales User"


async def test_a_malformed_model_answer_fails_the_job_and_produces_no_document(
    patched_jwks, client, db_session: AsyncSession, signed_in, model_reply, storage_root
) -> None:
    model_reply(draft_plan_response(remove=["parties"]))
    transaction = await sales_transaction(db_session, batch_number="I2626-231")
    transaction_id = transaction.id
    _, headers = await _sales_user(signed_in)

    response = await client.post(
        f"{BASE}/{transaction_id}/generate-draft",
        headers=headers,
        json={"document_type": DocumentType.DRAFT_CONTRACT.value},
    )
    assert response.status_code == 202

    job = await _await_job(db_session, response.json()["data"]["job_id"])
    assert job.status == JobStatus.FAILED.value
    assert job.error_message

    generated = (
        await db_session.scalars(
            select(Document).where(Document.source == DocumentSource.GENERATED.value)
        )
    ).all()
    assert generated == [], "a failed generation must leave nothing behind"

    failure = await db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.event_type == sales_service.AuditEvent.DRAFT_GENERATION_FAILED
        )
    )
    assert failure is not None


async def test_regenerating_over_the_wire_versions_rather_than_overwrites(
    patched_jwks, client, db_session: AsyncSession, signed_in, model_reply, storage_root
) -> None:
    model_reply(VALID_CONTRACT_PLAN)
    transaction = await sales_transaction(db_session, batch_number="I2626-232")
    transaction_id = transaction.id
    _, headers = await _sales_user(signed_in)

    for _ in range(2):
        response = await client.post(
            f"{BASE}/{transaction_id}/generate-draft",
            headers=headers,
            json={"document_type": DocumentType.DRAFT_CONTRACT.value},
        )
        assert response.status_code == 202
        await _await_job(db_session, response.json()["data"]["job_id"])

    detail = await client.get(f"{BASE}/{transaction_id}", headers=headers)
    drafts = detail.json()["data"]["generated_drafts"]

    assert [row["version"] for row in drafts] == [1, 2]
    assert drafts[0]["id"] != drafts[1]["id"]


async def test_a_purchase_user_may_not_generate_a_sales_draft(
    patched_jwks, client, db_session: AsyncSession, signed_in
) -> None:
    transaction = await sales_transaction(db_session, batch_number="I2626-233")
    _, headers = await _purchase_user(signed_in)

    response = await client.post(
        f"{BASE}/{transaction.id}/generate-draft",
        headers=headers,
        json={"document_type": DocumentType.DRAFT_CONTRACT.value},
    )

    assert response.status_code == 403


async def test_only_the_two_documents_this_platform_writes_can_be_asked_for(
    patched_jwks, client, db_session: AsyncSession, signed_in
) -> None:
    transaction = await sales_transaction(db_session, batch_number="I2626-234")
    _, headers = await _sales_user(signed_in)

    response = await client.post(
        f"{BASE}/{transaction.id}/generate-draft",
        headers=headers,
        json={"document_type": DocumentType.BL.value},
    )

    assert response.status_code == 422


# --- the read the workspace is built on ---------------------------------------------------------


async def test_the_detail_reports_the_quantity_meter_across_the_whole_contract(
    patched_jwks, client, db_session: AsyncSession, signed_in
) -> None:
    await sales_transaction(
        db_session, batch_number="I2626-240", quantity="60.000", contracted_quantity="100.000"
    )
    second = await sales_transaction(
        db_session, batch_number="I2626-241", quantity="30.000", contracted_quantity="100.000"
    )
    _, headers = await _sales_user(signed_in)

    detail = await client.get(f"{BASE}/{second.id}", headers=headers)
    coverage = detail.json()["data"]["contract_coverage"]

    assert Decimal(coverage["invoiced_quantity_mt"]) == Decimal("90.000")
    assert Decimal(coverage["contracted_quantity_mt"]) == Decimal("100.000")
    assert Decimal(coverage["remaining_quantity_mt"]) == Decimal("10.000")
    assert coverage["shipment_count"] == 2
    assert coverage["state"] == "partial"


async def test_the_detail_flags_a_genuine_code_disagreement_and_nothing_else(
    patched_jwks, client, db_session: AsyncSession, signed_in
) -> None:
    agreeing = await sales_transaction(
        db_session,
        batch_number="I2626-250",
        # The same underlying grade, described the way a destination's customs paperwork needs
        # it rather than as the bare code. A raw string comparison would call this a mismatch;
        # resolving the grade first is what makes it the pass it should be.
        extracted_commodity_value="Recovered copper wire scrap (GB/T 38470)",
    )
    disagreeing = await sales_transaction(
        db_session,
        batch_number="I2626-251",
        sales_contract_no="AGF-SC-2026-OTHER",
        extracted_commodity_value="AL",
    )
    _, headers = await _sales_user(signed_in)

    clean = await client.get(f"{BASE}/{agreeing.id}", headers=headers)
    clean_linked = clean.json()["data"]["linked_purchase"]
    assert clean_linked["commodity_code_mismatch"] is False, (
        "a differently-worded description of the same grade must never be flagged"
    )
    assert "may legitimately differ" in (clean_linked["message"] or "")

    flagged = await client.get(f"{BASE}/{disagreeing.id}", headers=headers)
    linked = flagged.json()["data"]["linked_purchase"]
    assert linked["commodity_code_mismatch"] is True
    assert linked["commodity_code"] == "CU"
    assert linked["sales_document_commodity_value"] == "AL"


async def test_the_detail_names_br_07_as_the_specific_reason_submission_is_blocked(
    patched_jwks, client, db_session: AsyncSession, signed_in
) -> None:
    transaction = await sales_transaction(
        db_session, batch_number="I2626-260", with_final_bl=False, with_draft_bl=True
    )
    _, headers = await _sales_user(signed_in)

    detail = await client.get(f"{BASE}/{transaction.id}", headers=headers)
    data = detail.json()["data"]

    assert data["can_submit"] is False
    assert any("BR-07" in reason for reason in data["blocking_rules"])
    # A draft B/L is enough to generate a draft, and the same read says so.
    assert data["can_generate_draft"] is True
    assert data["draft_blocker"] is None


async def test_an_auditor_reads_a_sales_transaction_but_writes_nothing(
    patched_jwks, client, db_session: AsyncSession, signed_in
) -> None:
    transaction = await sales_transaction(db_session, batch_number="I2626-270")
    _, headers = await signed_in("aud-sales", "auditor.sales@agfze.test", "Auditor", ["auditor"])

    detail = await client.get(f"{BASE}/{transaction.id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["data"]["can_edit"] is False
    assert detail.json()["data"]["can_generate_draft"] is False

    refused = await client.post(
        f"{BASE}/{transaction.id}/sales-leg", headers=headers, json=LEG_BODY
    )
    assert refused.status_code == 403


async def test_the_sl_01_result_is_visible_on_the_validation_panel(
    patched_jwks, client, db_session: AsyncSession, signed_in
) -> None:
    transaction = await sales_transaction(db_session, batch_number="I2626-280")
    _, headers = await _sales_user(signed_in)

    detail = await client.get(f"{BASE}/{transaction.id}", headers=headers)
    rules = detail.json()["data"]["rule_evaluations"]

    coverage = [
        row
        for row in rules
        if row["rule_id"] == RuleId.SL_01
        and row["check_key"] == CheckKey.CONTRACT_QUANTITY_COVERAGE
    ]
    assert coverage, "SL-01 must reach the workspace like any other evaluated rule"
    assert coverage[0]["title"] == "Sales contract quantity coverage"
    assert coverage[0]["statement"]


async def _await_job(session: AsyncSession, job_id: str) -> BackgroundJob:
    """Let the tracked background task finish, then read its row back.

    The generation runs as a real `asyncio` task exactly as extraction does, so the test yields
    to the loop rather than reaching inside the service to run it synchronously.
    """
    import asyncio
    from uuid import UUID

    for _ in range(200):
        await asyncio.sleep(0.01)
        # `populate_existing` rather than `expire_all`: expiring the whole identity map would
        # leave every other object the test is holding needing a lazy refresh, and a lazy load in
        # an async test is an error rather than a query.
        await session.rollback()
        job = await session.get(BackgroundJob, UUID(str(job_id)), populate_existing=True)
        if job is not None and job.status in (
            JobStatus.COMPLETED.value,
            JobStatus.FAILED.value,
        ):
            return job
    raise AssertionError("the draft generation job never reached a terminal state")

"""The `/requests` and `/documents` surfaces: upload admission, corrections, confirmation, roles."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.enums import DocumentSource, ExtractionStatus, RequestSource, RequestStatus
from app.models.intake import Document, ExtractedField, Request
from app.services import request_service
from tests.utils.fixtures import PNG_1PX, text_layer_pdf

pytestmark = pytest.mark.usefixtures("patched_jwks")

UPLOAD_URL = "/api/v1/documents/upload"


@pytest.fixture(autouse=True)
def no_live_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Upload queues real work. The API contract is under test here, not the model."""

    async def _noop(request_id, job_id, **_kwargs) -> None:
        return None

    monkeypatch.setattr("app.services.document_service._run_in_background", _noop)


async def purchase_user(signed_in):
    return await signed_in(
        "0a1b2c3d-0000-4000-8000-00000000a001",
        "purchase.user@agfze.ae",
        "Marco Bellini",
        ["purchase_user"],
    )


async def approver(signed_in):
    return await signed_in(
        "0a1b2c3d-0000-4000-8000-00000000a002",
        "hod.approver@agfze.ae",
        "Priya Raghunathan",
        ["approver_hod"],
    )


async def auditor(signed_in):
    return await signed_in(
        "0a1b2c3d-0000-4000-8000-00000000a003",
        "auditor.user@agfze.ae",
        "Kenji Watanabe",
        ["auditor"],
    )


# --- upload admission -----------------------------------------------------------------------


async def test_an_accepted_upload_creates_a_request_and_a_tracked_job(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    _, headers = await purchase_user(signed_in)

    response = await client.post(
        UPLOAD_URL,
        headers=headers,
        files=[("files", ("invoice.pdf", text_layer_pdf(), "application/pdf"))],
        data={"stream": "scrap", "document_type_hint": "invoice"},
    )

    assert response.status_code == 202, response.text
    data = response.json()["data"]
    assert data["request_code"].startswith("REQ-")
    assert len(data["document_ids"]) == 1
    assert data["rejected"] == []

    request = await db_session.get(Request, uuid.UUID(data["request_id"]))
    assert request is not None
    assert request.source == RequestSource.PORTAL.value
    assert request.stream == "scrap"
    assert request.status == RequestStatus.RECEIVED.value

    document = await db_session.get(Document, uuid.UUID(data["document_ids"][0]))
    assert document is not None
    assert document.content_type == "application/pdf"
    assert document.document_type_hint == "invoice"
    assert document.extraction_status == ExtractionStatus.PENDING.value
    # An opaque, UUID-derived key: the caller's filename never becomes part of the path.
    assert document.storage_ref.startswith("documents/source/")
    assert "invoice" not in document.storage_ref

    status = await client.get(f"/api/v1/jobs/{data['job_id']}/status", headers=headers)
    assert status.status_code == 200


async def test_a_file_whose_bytes_contradict_its_extension_is_refused(
    client: AsyncClient, signed_in
) -> None:
    _, headers = await purchase_user(signed_in)

    response = await client.post(
        UPLOAD_URL,
        headers=headers,
        # Named and declared as a PDF; the bytes are a Windows executable.
        files=[("files", ("statement.pdf", b"MZ\x90\x00" + b"\x00" * 1024, "application/pdf"))],
        data={"stream": "scrap"},
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert payload["errors"][0]["field"] == "statement.pdf"


async def test_an_oversized_file_is_refused(
    client: AsyncClient, signed_in, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, headers = await purchase_user(signed_in)
    monkeypatch.setattr("app.services.file_intake.settings.MAX_UPLOAD_BYTES", 2048)

    oversized = text_layer_pdf(["padding " * 400 for _ in range(40)])
    assert len(oversized) > 2048

    response = await client.post(
        UPLOAD_URL,
        headers=headers,
        files=[("files", ("huge.pdf", oversized, "application/pdf"))],
        data={"stream": "scrap"},
    )

    assert response.status_code == 400
    assert "25 MB" in response.json()["errors"][0]["message"]


async def test_a_mixed_batch_keeps_the_good_files_and_reports_the_rest(
    client: AsyncClient, signed_in
) -> None:
    _, headers = await purchase_user(signed_in)

    response = await client.post(
        UPLOAD_URL,
        headers=headers,
        files=[
            ("files", ("invoice.pdf", text_layer_pdf(), "application/pdf")),
            ("files", ("photo.png", PNG_1PX, "image/png")),
            ("files", ("payload.docx", b"\x7fELF\x02\x01\x01" + b"\x00" * 128, "text/plain")),
        ],
        data={"stream": "fa"},
    )

    assert response.status_code == 202
    data = response.json()["data"]
    assert len(data["document_ids"]) == 2
    assert [item["filename"] for item in data["rejected"]] == ["payload.docx"]


async def test_upload_is_closed_to_the_approver_and_the_auditor(
    client: AsyncClient, signed_in
) -> None:
    for provision in (approver, auditor):
        _, headers = await provision(signed_in)
        response = await client.post(
            UPLOAD_URL,
            headers=headers,
            files=[("files", ("invoice.pdf", text_layer_pdf(), "application/pdf"))],
            data={"stream": "scrap"},
        )
        assert response.status_code == 403


async def test_an_unknown_stream_is_rejected(client: AsyncClient, signed_in) -> None:
    _, headers = await purchase_user(signed_in)
    response = await client.post(
        UPLOAD_URL,
        headers=headers,
        files=[("files", ("invoice.pdf", text_layer_pdf(), "application/pdf"))],
        data={"stream": "not_a_stream"},
    )
    assert response.status_code == 400
    assert response.json()["errors"][0]["code"] == "invalid_stream"


# --- queue and detail -----------------------------------------------------------------------


async def seed_request(session: AsyncSession, **overrides) -> Request:
    request = await request_service.create_request(session, source=RequestSource.PORTAL)
    request.category = overrides.get("category", "purchase")
    request.original_category = request.category
    request.category_confidence = overrides.get("confidence", 0.92)
    request.category_rationale = "Synthetic fixture row."
    request.stream = overrides.get("stream", "scrap")
    request.status = overrides.get("status", RequestStatus.CLASSIFIED.value)
    request.needs_review = overrides.get("needs_review", False)
    await session.commit()
    return request


async def test_every_authenticated_role_may_read_the_queue(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    await seed_request(db_session)

    for provision in (purchase_user, approver, auditor):
        _, headers = await provision(signed_in)
        response = await client.get("/api/v1/requests", headers=headers)
        assert response.status_code == 200
        assert response.json()["data"]["page"]["total"] == 1


async def test_the_queue_filters_on_category_stream_and_review_state(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    await seed_request(db_session, category="purchase", stream="scrap", needs_review=False)
    await seed_request(
        db_session, category="logistics", stream="fa", needs_review=True, confidence=0.41
    )
    _, headers = await purchase_user(signed_in)

    async def total(query: str) -> int:
        response = await client.get(f"/api/v1/requests?{query}", headers=headers)
        assert response.status_code == 200
        return response.json()["data"]["page"]["total"]

    assert await total("category=purchase") == 1
    assert await total("stream=fa") == 1
    assert await total("needs_review=true") == 1
    assert await total("min_confidence=0.9") == 1
    assert await total("category=sales") == 0


async def test_a_category_override_keeps_the_original_ai_value(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    request = await seed_request(
        db_session, category="informational", confidence=0.42, needs_review=True
    )
    _, headers = await purchase_user(signed_in)

    response = await client.patch(
        f"/api/v1/requests/{request.id}/category",
        headers=headers,
        json={"category": "purchase", "stream": "scrap", "reason": "Broker deal confirmation."},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["category"] == "purchase"
    assert data["category_overridden"] is True
    # The machine's first answer survives the correction, permanently.
    assert data["original_category"] == "informational"
    assert data["needs_review"] is False

    await db_session.refresh(request)
    assert request.category_override_reason == "Broker deal confirmation."
    assert request.category_overridden_by_id is not None


async def test_a_category_override_without_a_reason_is_rejected(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    request = await seed_request(db_session)
    _, headers = await purchase_user(signed_in)

    response = await client.patch(
        f"/api/v1/requests/{request.id}/category",
        headers=headers,
        json={"category": "sales", "reason": ""},
    )
    assert response.status_code == 422


async def test_the_approver_may_read_a_request_but_not_correct_it(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    request = await seed_request(db_session)
    _, headers = await approver(signed_in)

    assert (await client.get(f"/api/v1/requests/{request.id}", headers=headers)).status_code == 200

    refused = await client.patch(
        f"/api/v1/requests/{request.id}/category",
        headers=headers,
        json={"category": "sales", "reason": "Should not be permitted."},
    )
    assert refused.status_code == 403


# --- field corrections ----------------------------------------------------------------------


async def seed_extracted_invoice(
    session: AsyncSession, *, confidences: dict[str, float]
) -> Document:
    request = await request_service.create_request(session, source=RequestSource.PORTAL)
    request.status = RequestStatus.EXTRACTED.value
    document = Document(
        request_id=request.id,
        filename="invoice.pdf",
        content_type="application/pdf",
        byte_size=2048,
        storage_ref="documents/source/fixture.pdf",
        content_hash="0" * 64,
        document_type="invoice",
        territory="india",
        page_count=1,
        extraction_status=ExtractionStatus.COMPLETED.value,
        classification_confidence=0.96,
    )
    session.add(document)
    await session.flush()
    for name, confidence in confidences.items():
        session.add(
            ExtractedField(
                document_id=document.id,
                field_name=name,
                field_value=f"ai-{name}",
                confidence=confidence,
                original_ai_value=f"ai-{name}",
                original_confidence=confidence,
            )
        )
    await session.commit()
    return document


async def test_a_low_confidence_field_is_flagged_and_needs_a_reason(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    low = settings.CONFIDENCE_THRESHOLD_DEFAULT - 0.2
    document = await seed_extracted_invoice(
        db_session, confidences={"invoice_number": 0.97, "batch_number": low}
    )
    _, headers = await purchase_user(signed_in)

    detail = await client.get(f"/api/v1/documents/{document.id}", headers=headers)
    assert detail.status_code == 200
    by_name = {row["field_name"]: row for row in detail.json()["data"]["fields"]}
    assert by_name["batch_number"]["reason_required"] is True
    assert by_name["invoice_number"]["reason_required"] is False

    refused = await client.patch(
        f"/api/v1/documents/{document.id}/fields",
        headers=headers,
        json={"corrections": [{"field_name": "batch_number", "value": "B-2026-091"}]},
    )
    assert refused.status_code == 400
    assert refused.json()["errors"][0]["code"] == "reason_required"

    accepted = await client.patch(
        f"/api/v1/documents/{document.id}/fields",
        headers=headers,
        json={
            "corrections": [
                {
                    "field_name": "batch_number",
                    "value": "B-2026-091",
                    "reason": "Read from the packing list.",
                }
            ]
        },
    )
    assert accepted.status_code == 200


async def test_a_confident_field_may_be_corrected_without_a_reason(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    document = await seed_extracted_invoice(db_session, confidences={"invoice_number": 0.97})
    _, headers = await purchase_user(signed_in)

    response = await client.patch(
        f"/api/v1/documents/{document.id}/fields",
        headers=headers,
        json={"corrections": [{"field_name": "invoice_number", "value": "INV-2026-0451"}]},
    )

    assert response.status_code == 200
    row = next(
        item for item in response.json()["data"]["fields"] if item["field_name"] == "invoice_number"
    )
    assert row["field_value"] == "INV-2026-0451"
    assert row["is_overridden"] is True


async def test_an_override_always_retains_the_original_ai_value(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    document = await seed_extracted_invoice(db_session, confidences={"invoice_number": 0.97})
    _, headers = await purchase_user(signed_in)

    for value in ("INV-first-correction", "INV-second-correction"):
        response = await client.patch(
            f"/api/v1/documents/{document.id}/fields",
            headers=headers,
            json={"corrections": [{"field_name": "invoice_number", "value": value}]},
        )
        assert response.status_code == 200

    row = (
        await db_session.scalars(
            select(ExtractedField).where(
                ExtractedField.document_id == document.id,
                ExtractedField.field_name == "invoice_number",
            )
        )
    ).one()
    await db_session.refresh(row)

    assert row.field_value == "INV-second-correction"
    # Two overrides later, the machine's original reading is still on the record untouched.
    assert row.original_ai_value == "ai-invoice_number"
    assert row.original_confidence == pytest.approx(0.97)


async def test_a_correction_is_validated_against_the_field_s_configured_type(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    document = await seed_extracted_invoice(db_session, confidences={"amount": 0.95})
    _, headers = await purchase_user(signed_in)

    refused = await client.patch(
        f"/api/v1/documents/{document.id}/fields",
        headers=headers,
        json={"corrections": [{"field_name": "amount", "value": "about two hundred thousand"}]},
    )
    assert refused.status_code == 422

    accepted = await client.patch(
        f"/api/v1/documents/{document.id}/fields",
        headers=headers,
        json={"corrections": [{"field_name": "amount", "value": "199,062.50"}]},
    )
    assert accepted.status_code == 200
    row = next(item for item in accepted.json()["data"]["fields"] if item["field_name"] == "amount")
    assert row["field_value"] == "199062.50"


async def test_a_field_outside_the_configured_schema_is_refused(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    document = await seed_extracted_invoice(db_session, confidences={"invoice_number": 0.9})
    _, headers = await purchase_user(signed_in)

    response = await client.patch(
        f"/api/v1/documents/{document.id}/fields",
        headers=headers,
        json={"corrections": [{"field_name": "smuggled_field", "value": "x"}]},
    )
    assert response.status_code == 400
    assert response.json()["errors"][0]["code"] == "unknown_field"


# --- confirmation ---------------------------------------------------------------------------


async def test_confirming_an_extraction_records_it_and_does_not_start_matching(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    document = await seed_extracted_invoice(db_session, confidences={"invoice_number": 0.95})
    _, headers = await purchase_user(signed_in)

    response = await client.post(f"/api/v1/documents/{document.id}/confirm", headers=headers)

    assert response.status_code == 200
    assert response.json()["data"]["confirmed_at"]

    await db_session.refresh(document)
    request = await db_session.get(Request, document.request_id)
    assert document.confirmed_by_id is not None
    assert request is not None
    assert request.status == RequestStatus.EXTRACTED.value
    # Nothing downstream exists yet: no transaction is created and none is linked.
    assert document.transaction_id is None


async def test_an_incomplete_extraction_cannot_be_confirmed(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    document = await seed_extracted_invoice(db_session, confidences={"invoice_number": 0.95})
    document.extraction_status = ExtractionStatus.FAILED.value
    await db_session.commit()
    _, headers = await purchase_user(signed_in)

    response = await client.post(f"/api/v1/documents/{document.id}/confirm", headers=headers)
    assert response.status_code == 409


async def test_the_auditor_reads_a_document_but_cannot_confirm_it(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    document = await seed_extracted_invoice(db_session, confidences={"invoice_number": 0.95})
    _, headers = await auditor(signed_in)

    assert (
        await client.get(f"/api/v1/documents/{document.id}", headers=headers)
    ).status_code == 200
    assert (
        await client.post(f"/api/v1/documents/{document.id}/confirm", headers=headers)
    ).status_code == 403


async def test_the_document_index_searches_names_codes_and_extracted_values(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    document = await seed_extracted_invoice(db_session, confidences={"invoice_number": 0.95})
    _, headers = await purchase_user(signed_in)

    async def total(query: str) -> int:
        response = await client.get(f"/api/v1/documents?{query}", headers=headers)
        assert response.status_code == 200
        return response.json()["data"]["page"]["total"]

    assert await total("search=invoice") == 1
    assert await total("search=ai-invoice_number") == 1
    assert await total("document_type=invoice") == 1
    assert await total("document_type=contract") == 0
    assert await total("search=nothing-matches-this") == 0

    listing = await client.get("/api/v1/documents", headers=headers)
    row = listing.json()["data"]["items"][0]
    assert row["id"] == str(document.id)
    # Forward-compatible column, honestly empty until Step 3 creates something to link to.
    assert row["transaction_id"] is None


async def test_a_generated_draft_does_not_break_the_document_index(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    """A draft this platform wrote has no request behind it, and the index has to survive it.

    `documents.request_id` became nullable when generated drafts arrived, so a document with no
    request is a normal row - not a broken one. A non-optional `request_id` on the response schema
    fails serialisation for the whole page, and every reader loses the index over one draft.
    """
    received = await seed_extracted_invoice(db_session, confidences={"invoice_number": 0.95})
    generated = Document(
        request_id=None,
        source=DocumentSource.GENERATED.value,
        filename="SO-I2626-1-500-Final-contract.docx",
        content_type=("application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        content_hash="a" * 64,
        byte_size=2048,
        storage_ref="documents/generated/x/SO-I2626-1-500-Final-contract.docx",
        extraction_status=ExtractionStatus.NOT_APPLICABLE.value,
    )
    db_session.add(generated)
    await db_session.commit()

    _, headers = await purchase_user(signed_in)

    listing = await client.get("/api/v1/documents", headers=headers)
    assert listing.status_code == 200, listing.text
    rows = {row["id"]: row for row in listing.json()["data"]["items"]}
    assert str(received.id) in rows
    assert rows[str(generated.id)]["request_id"] is None
    assert rows[str(generated.id)]["request_code"] is None

    detail = await client.get(f"/api/v1/documents/{generated.id}", headers=headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["data"]["request_id"] is None


async def test_an_unauthenticated_caller_reaches_nothing(client: AsyncClient) -> None:
    for url in ("/api/v1/requests", "/api/v1/documents", UPLOAD_URL):
        assert (await client.get(url)).status_code in (401, 405)

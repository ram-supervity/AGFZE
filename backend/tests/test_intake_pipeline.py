"""The whole intake pipeline, end to end, against synthetic model responses.

Real bytes, a real migration-built database, real storage, real background-job rows - only the
two external systems are replaced, each at its own boundary.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.audit import AuditEvent
from app.models.enums import ExtractionStatus, RequestSource, RequestStatus
from app.models.intake import Document, ExtractedField
from app.models.jobs import JobStatus
from app.services import document_service, job_service, request_service
from app.services.storage.local import LocalFileSystemStorage
from tests.utils.fixtures import (
    classification_response,
    document_classification_response,
    extraction_response,
    text_layer_pdf,
)

pytestmark = pytest.mark.usefixtures("patched_jwks")

INVOICE_VALUES = {
    "invoice_number": ("INV-2026-0451", 0.97),
    "contract_reference": ("AGF-CT-2026-118", 0.94),
    "batch_number": (None, 0.15),
    "commodity_code": ("Copper Millberry", 0.88),
    "quantity": ("24.500 MT", 0.96),
    "rate": ("8125.00", 0.93),
    "currency": ("USD", 0.99),
    "amount": ("199062.50", 0.95),
    "container_or_bl_reference": ("MSKU7781234", 0.61),
    "invoice_date": ("2026-08-14", 0.92),
}


@pytest.fixture
def scripted_model(monkeypatch: pytest.MonkeyPatch):
    """Answer each call in the pipeline's order: request, document type, then fields."""
    replies = [
        classification_response("purchase", 0.93, "scrap"),
        document_classification_response("invoice", 0.96, "india"),
        extraction_response(INVOICE_VALUES),
    ]
    sent: list[str] = []

    async def _raw(prompt, response_schema, images):
        sent.append(prompt)
        return replies[min(len(sent) - 1, len(replies) - 1)]

    monkeypatch.setattr("app.services.gemini_service._generate_raw", _raw)
    return sent


async def seed_uploaded_pdf(
    session: AsyncSession, storage: LocalFileSystemStorage
) -> tuple[Document, str]:
    request = await request_service.create_request(session, source=RequestSource.PORTAL)
    data = text_layer_pdf()
    key = document_service.new_document_storage_key("invoice.pdf")
    await storage.upload(key, data, "application/pdf")
    document = Document(
        request_id=request.id,
        filename="invoice.pdf",
        content_type="application/pdf",
        byte_size=len(data),
        storage_ref=key,
        content_hash="a" * 64,
    )
    session.add(document)
    await session.commit()
    return document, key


async def test_the_pipeline_classifies_extracts_and_reports_through_the_job_row(
    db_session: AsyncSession, scripted_model, storage_root: LocalFileSystemStorage
) -> None:
    document, _ = await seed_uploaded_pdf(db_session, storage_root)
    job = await job_service.create_job(db_session, job_type=document_service.JOB_TYPE_INTAKE)
    await db_session.commit()

    await document_service.process_request(db_session, document.request_id, job.id)

    await db_session.refresh(document)
    request = await request_service.get_request(db_session, document.request_id)

    assert request.category == "purchase"
    assert request.stream == "scrap"
    assert request.original_category == "purchase"
    assert request.status == RequestStatus.EXTRACTED.value

    assert document.document_type == "invoice"
    assert document.territory == "india"
    assert document.extraction_status == ExtractionStatus.COMPLETED.value
    assert document.page_count == 1
    # The pages rendered during extraction are kept and reused as the viewer's images.
    assert document.page_image_refs
    assert await storage_root.download(document.page_image_refs[0])

    fields = {
        row.field_name: row
        for row in (
            await db_session.scalars(
                select(ExtractedField).where(ExtractedField.document_id == document.id)
            )
        ).all()
    }
    assert fields["invoice_number"].field_value == "INV-2026-0451"
    assert fields["invoice_number"].original_ai_value == "INV-2026-0451"
    assert fields["batch_number"].field_value is None
    assert fields["container_or_bl_reference"].confidence == pytest.approx(0.61)
    # A field the model was unsure about drags the document into the review queue.
    assert document.needs_review is True

    refreshed_job = await job_service.get_job(db_session, job.id)
    assert refreshed_job.status == JobStatus.COMPLETED.value
    assert refreshed_job.progress == 100
    assert refreshed_job.result_ref == f"request:{document.request_id}"

    events = {row.event_type for row in (await db_session.scalars(select(AuditEvent))).all()}
    assert {"request.classified", "document.classified", "document.extracted"} <= events


async def test_an_extraction_failure_becomes_a_visible_review_state_not_a_500(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    storage_root: LocalFileSystemStorage,
) -> None:
    document, _ = await seed_uploaded_pdf(db_session, storage_root)

    replies = [
        classification_response("purchase", 0.93, "scrap"),
        document_classification_response("invoice", 0.96, "india"),
    ]
    calls = {"n": 0}

    async def _raw(prompt, response_schema, images):
        calls["n"] += 1
        if calls["n"] <= len(replies):
            return replies[calls["n"] - 1]
        raise RuntimeError("429 RESOURCE_EXHAUSTED for key AIzaSyLEAKEDKEY")

    monkeypatch.setattr("app.services.gemini_service._generate_raw", _raw)

    await document_service.process_request(db_session, document.request_id, None)

    await db_session.refresh(document)
    assert document.extraction_status == ExtractionStatus.FAILED.value
    assert document.needs_review is True
    # The provider's own text, key fragment and all, never becomes a user-visible message.
    assert "AIza" not in (document.extraction_error or "")
    assert "429" not in (document.extraction_error or "")


async def test_a_signed_page_image_url_serves_the_bytes_and_a_tampered_one_does_not(
    client: AsyncClient,
    db_session: AsyncSession,
    scripted_model,
    signed_in,
    storage_root: LocalFileSystemStorage,
) -> None:
    document, _ = await seed_uploaded_pdf(db_session, storage_root)
    await document_service.process_request(db_session, document.request_id, None)
    _, headers = await signed_in(
        "0a1b2c3d-0000-4000-8000-00000000b001",
        "purchase.user@agfze.ae",
        "Marco Bellini",
        ["purchase_user"],
    )

    detail = await client.get(f"/api/v1/documents/{document.id}", headers=headers)
    assert detail.status_code == 200
    data = detail.json()["data"]
    assert data["page_image_urls"]
    assert data["source_url"]
    assert data["confidence_threshold"] == pytest.approx(settings.CONFIDENCE_THRESHOLD_DEFAULT)
    # The schema drives the review screen's field list, straight off the configured row.
    assert next(item["name"] for item in data["schema_fields"]) == "invoice_number"
    assert data["mandatory_documents"][:2] == ["invoice", "packing_list"]

    page_url = data["page_image_urls"][0]
    assert "/internal/files/" in page_url
    # A signed link, not a path and not a permanent public URL.
    assert "expires=" in page_url and "signature=" in page_url

    served = await client.get(page_url.replace("http://testserver", ""))
    assert served.status_code == 200
    assert served.content.startswith(b"\x89PNG")
    assert served.headers["x-content-type-options"] == "nosniff"

    # Flip the last signature character to one it definitely was not, so the tamper is real
    # whatever hex digit the HMAC happened to end on.
    path = page_url.replace("http://testserver", "")
    tampered = path[:-1] + ("a" if path[-1] != "a" else "b")
    assert (await client.get(tampered)).status_code == 404


async def test_reclassifying_re_runs_extraction_against_the_new_type_s_schema(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    signed_in,
    storage_root: LocalFileSystemStorage,
) -> None:
    document, _ = await seed_uploaded_pdf(db_session, storage_root)
    document.document_type = "invoice"
    document.territory = "india"
    document.original_document_type = "invoice"
    document.extraction_status = ExtractionStatus.COMPLETED.value
    await db_session.commit()

    prompts: list[str] = []

    async def _raw(prompt, response_schema, images):
        prompts.append(prompt)
        return extraction_response(
            {
                "contract_number": ("AGF-CT-2026-118", 0.95),
                "buyer": ("AGFZE Trading FZE", 0.93),
                "seller": ("Nordic Metals AB", 0.91),
                "commodity": ("Copper Millberry", 0.9),
                "quantity": ("500 MT", 0.92),
                "quantity_tolerance": ("+/- 10%", 0.88),
                "price_basis": ("97% of LME cash settlement", 0.86),
                "incoterm": ("CIF Nhava Sheva", 0.94),
                "port_of_loading": ("Gothenburg", 0.9),
                "port_of_discharge": ("Nhava Sheva", 0.93),
                "payment_terms": ("LC at sight", 0.9),
            }
        )

    monkeypatch.setattr("app.services.gemini_service._generate_raw", _raw)
    # The background task runs on its own session; drive it inline so the assertion is real.
    monkeypatch.setattr(
        "app.services.document_service.queue_reextraction",
        _inline_reextraction(db_session),
    )

    _, headers = await signed_in(
        "0a1b2c3d-0000-4000-8000-00000000b002",
        "sales.user@agfze.ae",
        "Aisha Rahman",
        ["sales_user"],
    )

    response = await client.post(
        f"/api/v1/documents/{document.id}/reclassify",
        headers=headers,
        json={
            "document_type": "contract",
            "reason": "This is the deal confirmation, not the invoice.",
        },
    )
    assert response.status_code == 202

    await db_session.refresh(document)
    assert document.document_type == "contract"
    # The AI's original type is kept even after a person reclassifies the document.
    assert document.original_document_type == "invoice"

    names = {
        row.field_name
        for row in (
            await db_session.scalars(
                select(ExtractedField).where(ExtractedField.document_id == document.id)
            )
        ).all()
    }
    assert "contract_number" in names
    assert "invoice_number" not in names
    assert any("contract_number" in prompt for prompt in prompts)


def _inline_reextraction(session: AsyncSession):
    async def _run(_session, document_id, *, created_by_id=None):
        job = await job_service.create_job(
            session, job_type=document_service.JOB_TYPE_REEXTRACT, created_by_id=created_by_id
        )
        await session.commit()
        document = await session.get(Document, document_id)
        # The route committed the new type on its own session; this one still holds the row as
        # it was, so it is re-read before the schema is selected from it.
        await session.refresh(document)
        await document_service.process_document(session, document, classify=False)
        await job_service.complete_job(session, job.id)
        await session.commit()
        return job.id

    return _run

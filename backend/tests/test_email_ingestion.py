"""One inbound email becomes exactly one request, whichever path carries it.

The webhook and the delta poll are two different callers of the same ingestion function. Running
both against the same provider message id is the case that must never produce two rows.
"""

from __future__ import annotations

import base64

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.intake import Document, EmailMessage, Request
from app.services.email_ingestion import ingest_message
from app.services.graph_service import GraphClient
from tests.utils.fixtures import graph_message_payload, text_layer_pdf

MESSAGE_ID = "AAMkAGI2THVSAAA="


def mailbox(attachments: list[dict] | None = None) -> GraphClient:
    """A Graph client wired to a synthetic mailbox holding one message."""
    attachment_list = attachments or []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/token"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        if url.endswith("/$value"):
            return httpx.Response(200, content=b"From: desk@broker.example\r\n\r\nbody")
        if "/attachments/" in url:
            wanted = url.rsplit("/", 1)[-1]
            match = next(item for item in attachment_list if item["id"] == wanted)
            return httpx.Response(200, json=match)
        if url.endswith("/attachments") or "/attachments?" in url:
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": item["id"],
                            "name": item["name"],
                            "contentType": item.get("contentType", "application/pdf"),
                            "size": len(base64.b64decode(item["contentBytes"])),
                            "isInline": False,
                            "@odata.type": "#microsoft.graph.fileAttachment",
                        }
                        for item in attachment_list
                    ]
                },
            )
        return httpx.Response(
            200,
            json=graph_message_payload(MESSAGE_ID, hasAttachments=bool(attachment_list)),
        )

    return GraphClient(httpx.AsyncClient(transport=httpx.MockTransport(handler)))


async def counts(session: AsyncSession) -> tuple[int, int]:
    emails = await session.scalar(select(func.count()).select_from(EmailMessage))
    requests = await session.scalar(select(func.count()).select_from(Request))
    return int(emails or 0), int(requests or 0)


async def test_a_message_becomes_one_email_row_and_one_request(
    db_session: AsyncSession,
) -> None:
    client = mailbox()
    try:
        result = await ingest_message(db_session, MESSAGE_ID, client=client, process=False)
    finally:
        await client.aclose()

    assert result.created is True
    assert (await counts(db_session)) == (1, 1)

    request = await db_session.get(Request, result.request_id)
    assert request is not None
    assert request.source == "email"
    assert request.status == "received"
    assert request.request_code.startswith("REQ-")
    assert request.created_by_id is None

    email = await db_session.get(EmailMessage, result.email_message_id)
    assert email is not None
    assert email.provider_message_id == MESSAGE_ID
    assert email.sender_address == "desk@broker.example"
    # The untouched original is kept behind an opaque storage key, never a path.
    assert email.raw_storage_ref and not email.raw_storage_ref.startswith("/")


async def test_the_same_message_through_both_capture_paths_creates_one_request(
    db_session: AsyncSession,
) -> None:
    # First delivery: the webhook.
    client = mailbox()
    try:
        webhook = await ingest_message(db_session, MESSAGE_ID, client=client, process=False)
        await db_session.commit()
        # Second delivery: the fallback delta poll, same provider message id.
        poll = await ingest_message(db_session, MESSAGE_ID, client=client, process=False)
        await db_session.commit()
    finally:
        await client.aclose()

    assert webhook.created is True
    assert poll.created is False
    assert poll.reason == "already_ingested"
    assert poll.request_id == webhook.request_id
    assert poll.email_message_id == webhook.email_message_id
    assert (await counts(db_session)) == (1, 1)


async def test_attachments_are_admitted_by_their_bytes_not_their_names(
    db_session: AsyncSession,
) -> None:
    client = mailbox(
        [
            {
                "id": "att-good",
                "name": "invoice.pdf",
                "contentBytes": base64.b64encode(text_layer_pdf()).decode(),
            },
            {
                "id": "att-spoofed",
                "name": "malware.pdf",
                # Named .pdf, actually a Windows executable. Refused server-side.
                "contentBytes": base64.b64encode(b"MZ\x90\x00" + b"\x00" * 512).decode(),
            },
        ]
    )
    try:
        result = await ingest_message(db_session, MESSAGE_ID, client=client, process=False)
        await db_session.commit()
    finally:
        await client.aclose()

    documents = (
        await db_session.scalars(select(Document).where(Document.request_id == result.request_id))
    ).all()

    assert result.document_count == 1
    assert [document.filename for document in documents] == ["invoice.pdf"]
    assert documents[0].content_type == "application/pdf"
    assert len(documents[0].content_hash) == 64
    assert documents[0].uploaded_by_id is None
    assert documents[0].storage_ref.startswith("documents/source/")


async def test_an_empty_message_id_is_refused(db_session: AsyncSession) -> None:
    result = await ingest_message(db_session, "", process=False)
    assert result.created is False
    assert result.reason == "missing_message_id"
    assert (await counts(db_session)) == (0, 0)


async def test_the_webhook_route_answers_the_graph_validation_handshake(client) -> None:
    response = await client.post(
        "/api/v1/graph/notifications?validationToken=abc123", json={"value": []}
    )
    assert response.status_code == 200
    assert response.text == "abc123"
    assert response.headers["content-type"].startswith("text/plain")


async def test_a_notification_without_the_shared_client_state_is_discarded(
    client, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    ingested: list[str] = []

    async def _record(message_id: str) -> None:
        ingested.append(message_id)

    monkeypatch.setattr("app.api.v1.graph_notifications._ingest", _record)

    response = await client.post(
        "/api/v1/graph/notifications",
        json={
            "value": [
                {
                    "subscriptionId": "sub-1",
                    "clientState": "not-the-configured-secret",
                    "resource": f"Users/x/Messages/{MESSAGE_ID}",
                }
            ]
        },
    )

    assert response.status_code == 202
    assert ingested == []
    assert (await counts(db_session)) == (0, 0)

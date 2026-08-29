"""Replying to a broker or a supplier on the thread their message arrived on.

The capability discovery asks for - answer in-thread, with the standing disclaimer, "initially via
human-approved draft" - and the two properties that keep it safe to have at all.

**Nothing sends itself.** Composing a reply reaches no mailbox on any deployment. A message leaves
only inside a request a signed-in person made, and their account is what the trail records.

**A failed send is never recorded as a sent one.** The row says failed, carries the provider's own
reason, and the endpoint raises rather than reporting a delivery that did not happen.
"""

from __future__ import annotations

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.disclaimer import AI_DISCLAIMER_TEXT
from app.core.errors import BadRequestError
from app.models.audit import AuditEvent
from app.models.intake import EmailMessage, EmailReplyDraft, Request
from app.services import email_reply_service, graph_service
from app.services.email_reply_service import ReplyStatus
from app.services.graph_service import GraphClient
from tests.utils.admin import admin_user, approver_user, purchase_user

pytestmark = pytest.mark.usefixtures("patched_jwks")

PROVIDER_MESSAGE_ID = "AAMkAGRkNjQ-reply-thread"
DRAFT_ID = "AAMkAGRkNjQ-draft-001"
MESSAGE = "Confirming 125 MT copper against your reference BRK-4471. Contract to follow today."


def graph_client(*, send_status: int = 202) -> tuple[GraphClient, list[httpx.Request]]:
    """A Graph that answers exactly the two calls a reply makes, and records both."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/token"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        seen.append(request)
        if url.endswith("/createReply"):
            return httpx.Response(201, json={"id": DRAFT_ID})
        if url.endswith("/send"):
            return httpx.Response(send_status, json={})
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(404, json={})

    return GraphClient(httpx.AsyncClient(transport=httpx.MockTransport(handler))), seen


@pytest.fixture(autouse=True)
def _outbound_enabled(monkeypatch: pytest.MonkeyPatch):
    """Every test here runs with sending switched on, except the one that proves the switch."""
    monkeypatch.setattr("app.core.config.settings.GRAPH_REPLY_ENABLED", True)
    monkeypatch.setattr("app.services.graph_service.settings.GRAPH_REPLY_ENABLED", True)


@pytest.fixture
def _installed_graph(monkeypatch: pytest.MonkeyPatch):
    def _install(client: GraphClient) -> None:
        monkeypatch.setattr(graph_service, "get_graph_client", lambda: client)

    return _install


async def seed_thread(session: AsyncSession, *, from_email: bool = True) -> Request:
    email = None
    if from_email:
        email = EmailMessage(
            provider_message_id=PROVIDER_MESSAGE_ID,
            mailbox_address="trade.docs@agfze.test",
            sender_address="desk@broker.example",
            sender_name="Broker desk",
            subject="Copper 125 MT — deal confirmation",
            body_text="Please confirm the 125 MT copper booking.",
            received_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        )
        session.add(email)
        await session.flush()

    request = Request(
        request_code="REQ-20260401-0001",
        source="email" if from_email else "portal",
        email_message_id=email.id if email else None,
        category="purchase",
        stream="scrap",
        status="classified",
    )
    session.add(request)
    await session.flush()
    await session.commit()
    return request


# --- composing -----------------------------------------------------------------------------------


async def test_composing_writes_a_draft_and_contacts_no_mailbox(
    client: AsyncClient, signed_in, db_session: AsyncSession, _installed_graph
):
    graph, seen = graph_client()
    _installed_graph(graph)
    request = await seed_thread(db_session)
    _, headers = await purchase_user(signed_in)

    response = await client.post(
        f"/api/v1/requests/{request.id}/replies",
        headers=headers,
        json={"message": MESSAGE},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == ReplyStatus.DRAFT
    assert data["sent_at"] is None

    # The whole point: not one call went out to compose it.
    assert seen == []

    await graph.aclose()


async def test_every_composed_reply_carries_the_disclaimer_and_the_reference(
    client: AsyncClient, signed_in, db_session: AsyncSession
):
    request = await seed_thread(db_session)
    _, headers = await purchase_user(signed_in)

    response = await client.post(
        f"/api/v1/requests/{request.id}/replies",
        headers=headers,
        json={"message": MESSAGE},
    )
    body = response.json()["data"]["body_text"]

    assert MESSAGE in body
    assert request.request_code in body
    # The same wording the screens and the notification emails carry, imported rather than
    # retyped, so the three can never drift apart.
    assert AI_DISCLAIMER_TEXT in body
    assert "AGFZE Command Centre" in body


def test_the_composer_has_no_route_to_a_body_without_the_disclaimer():
    """There is no argument that omits it, and no branch that skips it."""
    body = email_reply_service.compose_body(reference="REQ-1", message="Anything at all here.")
    assert AI_DISCLAIMER_TEXT in body

    with pytest.raises(BadRequestError):
        email_reply_service.compose_body(reference="REQ-1", message="   ")


async def test_a_portal_upload_has_no_thread_to_reply_on(
    client: AsyncClient, signed_in, db_session: AsyncSession
):
    request = await seed_thread(db_session, from_email=False)
    _, headers = await purchase_user(signed_in)

    response = await client.post(
        f"/api/v1/requests/{request.id}/replies",
        headers=headers,
        json={"message": MESSAGE},
    )
    assert response.status_code == 400
    assert "no thread" in response.text.lower() or "portal upload" in response.text.lower()


async def test_a_reply_cannot_be_addressed_anywhere_but_the_thread_it_answers(
    client: AsyncClient, signed_in, db_session: AsyncSession
):
    """The write schema has no recipient, no subject and no attachment field at all.

    A rejected recipient would not be enough: the address a reply reaches has to be the one the
    captured message came from, which is a property of the data rather than of a validator.
    """
    from app.schemas.intake import ReplyComposeRequest

    assert set(ReplyComposeRequest.model_fields) == {"message"}

    request = await seed_thread(db_session)
    _, headers = await purchase_user(signed_in)
    response = await client.post(
        f"/api/v1/requests/{request.id}/replies",
        headers=headers,
        json={"message": MESSAGE, "to": "someone.else@example.com"},
    )
    assert response.status_code == 200
    listing = await client.get(f"/api/v1/requests/{request.id}/replies", headers=headers)
    assert listing.json()["data"]["recipient_address"] == "desk@broker.example"


# --- sending -------------------------------------------------------------------------------------


async def test_sending_is_a_separate_deliberate_call_and_is_recorded_against_the_sender(
    client: AsyncClient, signed_in, db_session: AsyncSession, _installed_graph
):
    graph, seen = graph_client()
    _installed_graph(graph)
    request = await seed_thread(db_session)
    user, headers = await purchase_user(signed_in)

    composed = await client.post(
        f"/api/v1/requests/{request.id}/replies", headers=headers, json={"message": MESSAGE}
    )
    draft_id = composed.json()["data"]["id"]

    sent = await client.post(
        f"/api/v1/requests/{request.id}/replies/{draft_id}/send", headers=headers
    )
    assert sent.status_code == 200, sent.text
    data = sent.json()["data"]
    assert data["status"] == ReplyStatus.SENT
    assert data["sent_by_name"] == user.display_name
    assert data["sent_at"] is not None

    # Threaded by the provider, from the original message, and then sent. Two calls, in order.
    assert [str(item.url).rsplit("/", 1)[-1] for item in seen] == ["createReply", "send"]
    assert PROVIDER_MESSAGE_ID in str(seen[0].url)
    # Plain text on the wire. Nothing this platform composes needs markup, and a text body cannot
    # carry a link, a beacon or a script into a counterparty's client on our behalf.
    assert b'"contentType": "text"' in seen[0].content or b'"contentType":"text"' in seen[0].content

    event = await db_session.scalar(
        select(AuditEvent).where(AuditEvent.event_type == "request.reply.sent")
    )
    assert event is not None
    assert event.actor_id == user.id
    assert event.event_metadata["sent"] is True
    assert event.event_metadata["recipient"] == "desk@broker.example"
    # The body itself never reaches the trail; its length does.
    assert "body_text" not in event.event_metadata

    await graph.aclose()


async def test_a_refused_send_is_recorded_as_failed_and_never_as_sent(
    client: AsyncClient, signed_in, db_session: AsyncSession, _installed_graph
):
    graph, _ = graph_client(send_status=403)
    _installed_graph(graph)
    request = await seed_thread(db_session)
    _, headers = await purchase_user(signed_in)

    composed = await client.post(
        f"/api/v1/requests/{request.id}/replies", headers=headers, json={"message": MESSAGE}
    )
    draft_id = composed.json()["data"]["id"]

    refused = await client.post(
        f"/api/v1/requests/{request.id}/replies/{draft_id}/send", headers=headers
    )
    assert refused.status_code == 502

    row = await db_session.get(EmailReplyDraft, __import__("uuid").UUID(draft_id))
    await db_session.refresh(row)
    assert row.status == ReplyStatus.FAILED
    assert row.failure_reason == "http_403"
    assert row.sent_at is None and row.sent_by_id is None

    event = await db_session.scalar(
        select(AuditEvent).where(AuditEvent.event_type == "request.reply.send_failed")
    )
    assert event is not None
    assert event.event_metadata["sent"] is False

    await graph.aclose()


async def test_the_same_reply_cannot_be_sent_twice(
    client: AsyncClient, signed_in, db_session: AsyncSession, _installed_graph
):
    graph, seen = graph_client()
    _installed_graph(graph)
    request = await seed_thread(db_session)
    _, headers = await purchase_user(signed_in)

    composed = await client.post(
        f"/api/v1/requests/{request.id}/replies", headers=headers, json={"message": MESSAGE}
    )
    draft_id = composed.json()["data"]["id"]
    first = await client.post(
        f"/api/v1/requests/{request.id}/replies/{draft_id}/send", headers=headers
    )
    assert first.status_code == 200
    second = await client.post(
        f"/api/v1/requests/{request.id}/replies/{draft_id}/send", headers=headers
    )
    assert second.status_code == 409
    # Refused before it reached the provider, so the counterparty gets one message and not two.
    assert len([item for item in seen if str(item.url).endswith("/send")]) == 1

    await graph.aclose()


async def test_a_withdrawn_reply_cannot_be_sent_and_a_sent_one_cannot_be_withdrawn(
    client: AsyncClient, signed_in, db_session: AsyncSession, _installed_graph
):
    graph, _ = graph_client()
    _installed_graph(graph)
    request = await seed_thread(db_session)
    _, headers = await purchase_user(signed_in)

    first = (
        await client.post(
            f"/api/v1/requests/{request.id}/replies", headers=headers, json={"message": MESSAGE}
        )
    ).json()["data"]["id"]
    assert (
        await client.post(
            f"/api/v1/requests/{request.id}/replies/{first}/withdraw", headers=headers
        )
    ).status_code == 200
    assert (
        await client.post(f"/api/v1/requests/{request.id}/replies/{first}/send", headers=headers)
    ).status_code == 409

    second = (
        await client.post(
            f"/api/v1/requests/{request.id}/replies", headers=headers, json={"message": MESSAGE}
        )
    ).json()["data"]["id"]
    assert (
        await client.post(f"/api/v1/requests/{request.id}/replies/{second}/send", headers=headers)
    ).status_code == 200
    assert (
        await client.post(
            f"/api/v1/requests/{request.id}/replies/{second}/withdraw", headers=headers
        )
    ).status_code == 409

    await graph.aclose()


async def test_a_reply_belonging_to_another_request_is_not_reachable_through_this_one(
    client: AsyncClient, signed_in, db_session: AsyncSession
):
    request = await seed_thread(db_session)
    other = Request(request_code="REQ-20260401-0002", source="portal", status="classified")
    db_session.add(other)
    await db_session.commit()
    _, headers = await purchase_user(signed_in)

    draft_id = (
        await client.post(
            f"/api/v1/requests/{request.id}/replies", headers=headers, json={"message": MESSAGE}
        )
    ).json()["data"]["id"]

    response = await client.post(
        f"/api/v1/requests/{other.id}/replies/{draft_id}/send", headers=headers
    )
    assert response.status_code == 404


# --- who may do it, and whether this deployment may at all ----------------------------------------


async def test_only_a_desk_composes_and_sends_while_everybody_signed_in_can_read(
    client: AsyncClient, signed_in, db_session: AsyncSession
):
    request = await seed_thread(db_session)

    _, approver_headers = await approver_user(signed_in)
    # The approver reviews and signs off; they are not the correcting or corresponding party, and
    # this is the same separation the category override already holds to.
    refused = await client.post(
        f"/api/v1/requests/{request.id}/replies",
        headers=approver_headers,
        json={"message": MESSAGE},
    )
    assert refused.status_code == 403
    assert (
        await client.get(f"/api/v1/requests/{request.id}/replies", headers=approver_headers)
    ).status_code == 200

    _, admin_headers = await admin_user(signed_in)
    assert (
        await client.post(
            f"/api/v1/requests/{request.id}/replies",
            headers=admin_headers,
            json={"message": MESSAGE},
        )
    ).status_code == 200


async def test_with_outbound_switched_off_a_reply_is_composed_and_still_cannot_leave(
    client: AsyncClient,
    signed_in,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    _installed_graph,
):
    """The honest degraded state, and it is not a failure.

    Reading a shared mailbox and writing from AGFZE's own address are different decisions. With
    the second one not taken, the desk can still draft a reply and read it back; the send says so
    plainly instead of reporting a delivery that did not happen.
    """
    graph, seen = graph_client()
    _installed_graph(graph)
    monkeypatch.setattr("app.core.config.settings.GRAPH_REPLY_ENABLED", False)
    monkeypatch.setattr("app.services.graph_service.settings.GRAPH_REPLY_ENABLED", False)

    request = await seed_thread(db_session)
    _, headers = await purchase_user(signed_in)

    composed = await client.post(
        f"/api/v1/requests/{request.id}/replies", headers=headers, json={"message": MESSAGE}
    )
    assert composed.status_code == 200
    draft_id = composed.json()["data"]["id"]

    listing = await client.get(f"/api/v1/requests/{request.id}/replies", headers=headers)
    assert listing.json()["data"]["outbound_enabled"] is False

    refused = await client.post(
        f"/api/v1/requests/{request.id}/replies/{draft_id}/send", headers=headers
    )
    assert refused.status_code == 409
    assert "not enabled" in refused.text.lower()
    # Nothing was attempted against the mailbox at all.
    assert seen == []

    await graph.aclose()

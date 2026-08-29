"""Graph token acquisition, caching and message parsing, against a mocked HTTP boundary.

Nothing here reaches Microsoft. `httpx.MockTransport` answers every call with a response the test
writes itself, which is what lets the token cache, the 401 retry, the delta paging and the
attachment decode all be asserted with no tenant and no credentials present.
"""

from __future__ import annotations

import base64

import httpx
import pytest

from app.services.graph_service import (
    GraphClient,
    GraphError,
    GraphNotConfiguredError,
    resource_message_id,
    to_message,
)
from tests.utils.fixtures import graph_message_payload


def build_client(handler) -> GraphClient:
    transport = httpx.MockTransport(handler)
    return GraphClient(httpx.AsyncClient(transport=transport, base_url="https://graph.test"))


async def test_a_token_is_acquired_once_and_reused_until_it_nears_expiry() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"access_token": "token-one", "expires_in": 3600})

    client = build_client(handler)
    try:
        assert await client.access_token() == "token-one"
        assert await client.access_token() == "token-one"
        assert await client.access_token() == "token-one"
    finally:
        await client.aclose()

    # One network round trip for three callers: the cache, not the endpoint, answered twice.
    assert len(calls) == 1
    body = dict(pair.split("=", 1) for pair in calls[0].content.decode().split("&"))
    assert body["grant_type"] == "client_credentials"
    assert "scope" in body


async def test_a_short_lived_token_is_refreshed_rather_than_used_to_expiry() -> None:
    issued: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        issued.append(f"token-{len(issued) + 1}")
        # A lifetime inside the refresh margin must never be cached.
        return httpx.Response(200, json={"access_token": issued[-1], "expires_in": 120})

    client = build_client(handler)
    try:
        first = await client.access_token()
        second = await client.access_token()
    finally:
        await client.aclose()

    assert first == "token-1"
    assert second == "token-2"


async def test_a_rejected_credential_raises_and_never_reports_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401, json={"error": "invalid_client", "error_description": "secret is invalid"}
        )

    client = build_client(handler)
    try:
        with pytest.raises(GraphError) as caught:
            await client.access_token()
    finally:
        await client.aclose()

    assert caught.value.reason == "authentication"
    # The provider's own wording, which can echo the client id, never reaches the caller.
    assert "invalid_client" not in caught.value.message
    assert "secret" not in caught.value.message


async def test_missing_credentials_fail_loudly_instead_of_being_faked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.services.graph_service.settings.AZURE_AD_CLIENT_SECRET", "")
    client = GraphClient()
    with pytest.raises(GraphNotConfiguredError):
        await client.access_token()


async def test_a_revoked_token_is_dropped_and_the_call_retried_once() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(
                200, json={"access_token": f"token-{len(seen) + 1}", "expires_in": 3600}
            )
        seen.append(request.headers["Authorization"])
        if len(seen) == 1:
            return httpx.Response(401, json={"error": {"code": "InvalidAuthenticationToken"}})
        return httpx.Response(200, json=graph_message_payload("AAMk-1"))

    client = build_client(handler)
    try:
        message = await client.get_message("AAMk-1")
    finally:
        await client.aclose()

    assert message.message_id == "AAMk-1"
    assert seen == ["Bearer token-1", "Bearer token-2"]


async def test_delta_follows_every_page_and_returns_the_next_delta_link() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        if "page2" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "value": [graph_message_payload("AAMk-2"), {"id": "AAMk-3", "@removed": {}}],
                    "@odata.deltaLink": "https://graph.test/delta?token=next",
                },
            )
        return httpx.Response(
            200,
            json={
                "value": [graph_message_payload("AAMk-1")],
                "@odata.nextLink": "https://graph.test/page2",
            },
        )

    client = build_client(handler)
    try:
        page = await client.delta()
    finally:
        await client.aclose()

    assert [message.message_id for message in page.messages] == ["AAMk-1", "AAMk-2"]
    assert page.delta_link == "https://graph.test/delta?token=next"


async def test_attachment_bytes_are_base64_decoded() -> None:
    payload = b"%PDF-1.7 synthetic"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        return httpx.Response(
            200,
            json={
                "id": "att-1",
                "name": "invoice.pdf",
                "contentBytes": base64.b64encode(payload).decode(),
            },
        )

    client = build_client(handler)
    try:
        assert await client.get_attachment_bytes("AAMk-1", "att-1") == payload
    finally:
        await client.aclose()


def test_an_html_body_is_flattened_to_text_and_never_kept_as_markup() -> None:
    message = to_message(
        graph_message_payload(
            "AAMk-9",
            body={
                "contentType": "html",
                "content": "<html><script>alert(1)</script><p>Rate <b>8125.00</b></p></html>",
            },
        )
    )
    assert "<script>" not in message.body_text
    assert "alert(1)" not in message.body_text
    assert "8125.00" in message.body_text


@pytest.mark.parametrize(
    ("resource", "expected"),
    [
        ("Users/abc/Messages/AAMk-1", "AAMk-1"),
        ("users/abc/mailFolders('inbox')/messages/AAMk-2", "AAMk-2"),
        ("", None),
    ],
)
def test_the_message_id_is_read_out_of_the_notification_resource(
    resource: str, expected: str | None
) -> None:
    assert resource_message_id(resource) == expected

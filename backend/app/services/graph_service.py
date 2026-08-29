"""Microsoft Graph mailbox access.

A dedicated Azure AD app registration authenticates with the OAuth2 client-credentials flow.
This is a machine identity: it has no interactive login and is entirely separate from the
Keycloak/Entra broker staff sign in through.

Three capabilities live on this one client, and they are deliberately not three clients. 
gave it Mail.Read, narrowed by an application access policy to the one approved shared mailbox.
 adds the Excel writes the tracker synchronisation needs, and the grant behind them is
`Files.ReadWrite.Selected` (or `Sites.Selected` on the site holding the workbooks) - the specific
tracker workbooks and nothing else. A tenant-wide Files.ReadWrite.All would let this process
rewrite every document in the organisation to update one row of one spreadsheet, and nothing here
needs that.

The third is the thread reply, and it is the only one that puts something *out* of this platform.
It needs `Mail.ReadWrite` and `Mail.Send` on the same mailbox, narrowed by the same application
access policy, and it stays off until `GRAPH_REPLY_ENABLED` is set - because a capability that can
email a supplier should be switched on deliberately rather than acquired by upgrading a grant. A
reply is composed as a *draft* on the original conversation and is sent only by an explicit,
recorded human action; nothing in this module sends anything on its own.

The Excel operations below are row-level throughout. A row is located, patched or appended
through the workbook API; the workbook file itself is never downloaded, opened or re-saved, so
somebody editing the same tracker at the same moment is never clobbered by this platform.

Two capture paths exist, and both funnel into the same ingestion function:

* a change-notification subscription for near-real-time delivery, renewed before its ~3 day
  expiry;
* a delta-query poll on a timer, so a dropped webhook delivery costs latency, not a message.

Credentials live only in settings. They are never logged, never returned, and a missing or
invalid one raises a real, visible failure - no call is ever faked.
"""

from __future__ import annotations

import asyncio
import base64
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import settings
from app.core.errors import AppError
from app.core.logging import get_logger

logger = get_logger(__name__)

# Refreshed this far ahead of expiry so an in-flight call never races the token running out.
TOKEN_REFRESH_MARGIN_SECONDS = 300
MESSAGE_SELECT = "id,subject,from,receivedDateTime,hasAttachments,internetMessageId,body"


class GraphError(AppError):
    """A Graph call failed. The caller-facing message never carries the provider's own text."""

    status_code = 502
    code = "mailbox_unavailable"
    message = "The mailbox service could not be reached."

    def __init__(self, message: str | None = None, *, reason: str = "unknown") -> None:
        super().__init__(message)
        self.reason = reason


class GraphNotConfiguredError(GraphError):
    code = "mailbox_not_configured"
    message = "Mailbox intake is not configured."


class ReplyNotEnabledError(GraphError):
    """Outbound replies are not switched on for this deployment.

    Its own type, and not a failure. The client below is complete; what is absent is AGFZE's
    decision to let this platform put a message into a supplier's inbox, plus the two Graph grants
    that decision implies. A composed reply is still stored and still readable - it simply cannot
    leave, and the caller says so rather than reporting a send that did not happen.
    """

    status_code = 409
    code = "mailbox_reply_not_enabled"
    message = "Sending a reply from the shared mailbox is not enabled on this deployment."


class TrackerNotConfiguredError(GraphError):
    """No tracker workbook, table or column mapping has been confirmed for this deployment.

    Deliberately its own type. The client below is complete and correct; what is missing is which
    workbook AGFZE wants written to, which is a business decision rather than a fault. The caller
    turns this into an honest `awaiting_manual_action`, never into a failure and never into a
    silently skipped job.
    """

    status_code = 409
    code = "tracker_not_configured"
    message = "No tracker workbook has been configured for this deployment."


@dataclass(frozen=True)
class GraphAttachment:
    attachment_id: str
    name: str
    content_type: str
    size: int
    is_inline: bool


@dataclass(frozen=True)
class GraphMessage:
    message_id: str
    subject: str | None
    sender_address: str | None
    sender_name: str | None
    body_text: str
    received_at: datetime
    has_attachments: bool


@dataclass(frozen=True)
class ExcelTableRow:
    """One row of the tracker table, as Graph addresses it: by index, with its cell values."""

    index: int
    values: list[Any]


@dataclass(frozen=True)
class TrackerWriteResult:
    """What a tracker write actually did to the workbook."""

    row_index: int
    created: bool
    columns_written: list[str]

    @property
    def action(self) -> str:
        return "appended" if self.created else "updated"


@dataclass(frozen=True)
class DeltaPage:
    messages: list[GraphMessage]
    delta_link: str | None


def _parse_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)


def _html_to_text(html: str) -> str:
    """Flatten an HTML body to text without ever rendering or executing any of it."""
    import re

    without_blocks = re.sub(
        r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.IGNORECASE | re.DOTALL
    )
    with_breaks = re.sub(r"<br\s*/?>|</p>|</div>|</tr>", "\n", without_blocks, flags=re.IGNORECASE)
    stripped = re.sub(r"<[^>]+>", " ", with_breaks)
    unescaped = (
        stripped.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    return re.sub(r"[ \t]+\n", "\n", re.sub(r"\n{3,}", "\n\n", unescaped)).strip()


def to_message(payload: dict[str, Any]) -> GraphMessage:
    sender = (payload.get("from") or {}).get("emailAddress") or {}
    body = payload.get("body") or {}
    raw_body = str(body.get("content") or "")
    text = (
        _html_to_text(raw_body)
        if str(body.get("contentType") or "").lower() == "html"
        else raw_body.strip()
    )
    return GraphMessage(
        message_id=str(payload.get("id") or ""),
        subject=payload.get("subject"),
        sender_address=sender.get("address"),
        sender_name=sender.get("name"),
        body_text=text,
        received_at=_parse_datetime(payload.get("receivedDateTime")),
        has_attachments=bool(payload.get("hasAttachments")),
    )


class GraphClient:
    """One pooled HTTP client and one cached application token per process."""

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        self._http = http_client
        self._owns_http = http_client is None
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._token_lock = asyncio.Lock()

    # --- plumbing -------------------------------------------------------------------------

    @property
    def http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                timeout=httpx.Timeout(settings.GRAPH_TIMEOUT_SECONDS),
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            )
        return self._http

    async def aclose(self) -> None:
        if self._http is not None and self._owns_http:
            await self._http.aclose()
        self._http = None

    def _require_configuration(self) -> None:
        if not settings.graph_configured:
            raise GraphNotConfiguredError(reason="missing_credentials")

    def clear_token(self) -> None:
        self._token = None
        self._token_expires_at = 0.0

    # --- authentication -------------------------------------------------------------------

    async def access_token(self) -> str:
        """Return a cached application token, acquiring a new one before the old one expires."""
        self._require_configuration()
        if self._token and time.monotonic() < self._token_expires_at:
            return self._token

        async with self._token_lock:
            if self._token and time.monotonic() < self._token_expires_at:
                return self._token

            url = (
                f"{settings.GRAPH_LOGIN_BASE_URL.rstrip('/')}"
                f"/{settings.AZURE_AD_TENANT_ID}/oauth2/v2.0/token"
            )
            try:
                response = await self.http.post(
                    url,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": settings.AZURE_AD_CLIENT_ID,
                        "client_secret": settings.AZURE_AD_CLIENT_SECRET,
                        "scope": settings.GRAPH_SCOPE,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
            except httpx.HTTPError as exc:
                logger.warning("graph_token_transport_error", extra={"reason": type(exc).__name__})
                raise GraphError(reason="transport") from exc

            if response.status_code != 200:
                # The body can echo the client id and tenant; only the status reaches the log.
                logger.warning("graph_token_rejected", extra={"status_code": response.status_code})
                raise GraphError(reason="authentication")

            payload = response.json()
            token = payload.get("access_token")
            if not isinstance(token, str) or not token:
                raise GraphError(reason="malformed_token_response")

            expires_in = payload.get("expires_in")
            lifetime = int(expires_in) if isinstance(expires_in, int | float | str) else 3600
            self._token = token
            # Held until a margin short of expiry, and never past the token's own lifetime: a
            # token too short-lived to leave that margin is simply not cached.
            self._token_expires_at = time.monotonic() + max(
                0, lifetime - TOKEN_REFRESH_MARGIN_SECONDS
            )
            logger.info("graph_token_acquired", extra={"expires_in": int(lifetime)})
            return token

    async def _request(
        self,
        method: str,
        url: str,
        *,
        json_body: dict[str, Any] | None = None,
        accept: str = "application/json",
    ) -> httpx.Response:
        token = await self.access_token()
        headers = {"Authorization": f"Bearer {token}", "Accept": accept}
        try:
            response = await self.http.request(method, url, headers=headers, json=json_body)
        except httpx.HTTPError as exc:
            logger.warning(
                "graph_request_transport_error",
                extra={"method": method, "reason": type(exc).__name__},
            )
            raise GraphError(reason="transport") from exc

        if response.status_code == 401:
            # The cached token was revoked or rotated early; drop it and try exactly once more.
            self.clear_token()
            token = await self.access_token()
            headers["Authorization"] = f"Bearer {token}"
            try:
                response = await self.http.request(method, url, headers=headers, json=json_body)
            except httpx.HTTPError as exc:
                raise GraphError(reason="transport") from exc

        if response.status_code >= 400:
            logger.warning(
                "graph_request_failed",
                extra={"method": method, "status_code": response.status_code},
            )
            raise GraphError(reason=f"http_{response.status_code}")
        return response

    def _mailbox_url(self, suffix: str) -> str:
        base = settings.GRAPH_BASE_URL.rstrip("/")
        mailbox = settings.GRAPH_MAILBOX_ADDRESS
        return f"{base}/users/{mailbox}{suffix}"

    # --- mail -----------------------------------------------------------------------------

    async def get_message(self, message_id: str) -> GraphMessage:
        response = await self._request(
            "GET", self._mailbox_url(f"/messages/{message_id}?$select={MESSAGE_SELECT}")
        )
        return to_message(response.json())

    async def get_raw_message(self, message_id: str) -> bytes:
        """The untouched MIME source, stored as the immutable original."""
        response = await self._request(
            "GET", self._mailbox_url(f"/messages/{message_id}/$value"), accept="text/plain"
        )
        return response.content

    async def list_attachments(self, message_id: str) -> list[GraphAttachment]:
        response = await self._request(
            "GET",
            self._mailbox_url(
                f"/messages/{message_id}/attachments"
                "?$select=id,name,contentType,size,isInline,@odata.type"
            ),
        )
        attachments: list[GraphAttachment] = []
        for item in response.json().get("value", [])[: settings.GRAPH_MAX_ATTACHMENTS_PER_MESSAGE]:
            if not isinstance(item, dict):
                continue
            # Only file attachments carry bytes; item and reference attachments do not.
            if item.get("@odata.type") not in (None, "#microsoft.graph.fileAttachment"):
                continue
            attachments.append(
                GraphAttachment(
                    attachment_id=str(item.get("id") or ""),
                    name=str(item.get("name") or "attachment"),
                    # Recorded for the audit trail only. The real type is decided by magic bytes.
                    content_type=str(item.get("contentType") or "application/octet-stream"),
                    size=int(item.get("size") or 0),
                    is_inline=bool(item.get("isInline")),
                )
            )
        return attachments

    async def get_attachment_bytes(self, message_id: str, attachment_id: str) -> bytes:
        """Fetched one attachment at a time, as each is processed, never all up front."""
        response = await self._request(
            "GET", self._mailbox_url(f"/messages/{message_id}/attachments/{attachment_id}")
        )
        payload = response.json()
        encoded = payload.get("contentBytes")
        if not isinstance(encoded, str):
            raise GraphError(reason="attachment_without_content")
        try:
            return base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError) as exc:
            raise GraphError(reason="attachment_not_base64") from exc

    async def delta(self, delta_link: str | None = None) -> DeltaPage:
        """One delta page. The returned link is persisted and replayed on the next poll."""
        url = delta_link or self._mailbox_url(
            f"/mailFolders/inbox/messages/delta?$select={MESSAGE_SELECT}"
        )
        messages: list[GraphMessage] = []
        next_delta: str | None = None

        while True:
            response = await self._request("GET", url)
            payload = response.json()
            for item in payload.get("value", []):
                if isinstance(item, dict) and item.get("id") and "@removed" not in item:
                    messages.append(to_message(item))
            next_link = payload.get("@odata.nextLink")
            if isinstance(next_link, str) and next_link:
                url = next_link
                continue
            candidate = payload.get("@odata.deltaLink")
            next_delta = candidate if isinstance(candidate, str) else None
            break

        return DeltaPage(messages=messages, delta_link=next_delta)

    # --- workbook (the tracker, from ) ------------------------------------------------

    def _require_tracker(self) -> None:
        if not settings.tracker_configured:
            raise TrackerNotConfiguredError(reason="missing_tracker_configuration")

    def _table_url(self, suffix: str = "") -> str:
        """The tracker table's address, scoped to its worksheet where one is configured.

        Everything below hangs off this one URL, and every one of them addresses rows and columns
        rather than the file. There is no code path in this client that fetches the workbook's
        bytes.
        """
        base = settings.GRAPH_BASE_URL.rstrip("/")
        item = (
            f"/drives/{settings.TRACKER_DRIVE_ID}"
            f"/items/{settings.TRACKER_WORKBOOK_ITEM_ID}/workbook"
        )
        sheet = settings.TRACKER_WORKSHEET_NAME.strip()
        scope = f"/worksheets('{quote(sheet)}')" if sheet else ""
        return f"{base}{item}{scope}/tables('{quote(settings.TRACKER_TABLE_NAME)}'){suffix}"

    async def table_columns(self) -> list[str]:
        """The tracker table's column headers, in workbook order.

        Read every time rather than cached: a tracker is a live spreadsheet that people reorder,
        and writing a value into the column that used to be there is worse than failing.
        """
        self._require_tracker()
        response = await self._request("GET", self._table_url("/columns?$select=name,index"))
        columns = [
            (int(item.get("index", position)), str(item.get("name") or ""))
            for position, item in enumerate(response.json().get("value", []))
            if isinstance(item, dict)
        ]
        return [name for _index, name in sorted(columns)]

    async def find_table_row(self, key_column_index: int, key_value: str) -> ExcelTableRow | None:
        """The row whose key cell equals `key_value`, or None.

        Paged through with $top/$skip so a tracker with thousands of rows is read in bounded
        chunks. Comparison is on the trimmed string form, because a batch number typed into a
        spreadsheet arrives with whatever spacing the typist used.
        """
        self._require_tracker()
        wanted = key_value.strip().casefold()
        page_size = 200
        skip = 0
        while True:
            response = await self._request(
                "GET", self._table_url(f"/rows?$select=index,values&$top={page_size}&$skip={skip}")
            )
            rows = response.json().get("value", [])
            if not rows:
                return None
            for item in rows:
                if not isinstance(item, dict):
                    continue
                values = item.get("values") or [[]]
                cells = values[0] if values else []
                if key_column_index >= len(cells):
                    continue
                cell = cells[key_column_index]
                if str("" if cell is None else cell).strip().casefold() == wanted:
                    return ExcelTableRow(index=int(item.get("index", 0)), values=list(cells))
            if len(rows) < page_size:
                return None
            skip += page_size

    async def update_table_row(self, row_index: int, values: list[Any]) -> None:
        """Patch one row in place, addressed by its index within the table."""
        self._require_tracker()
        await self._request(
            "PATCH",
            self._table_url(f"/rows/itemAt(index={int(row_index)})"),
            json_body={"values": [values]},
        )

    async def add_table_row(self, values: list[Any]) -> int:
        """Append one row to the end of the table and return the index it landed at."""
        self._require_tracker()
        response = await self._request(
            "POST", self._table_url("/rows/add"), json_body={"index": None, "values": [values]}
        )
        payload = response.json()
        index = payload.get("index")
        return int(index) if isinstance(index, int | float | str) else 0

    async def upsert_tracker_row(self, fields: dict[str, Any]) -> TrackerWriteResult:
        """Write one transaction's figures into the tracker: update its row, or append one.

        The whole operation is three row-level calls at most - read the headers, find the row,
        patch or append it. `fields` is keyed by the platform's own field names and translated
        through the configured column mapping here, so nothing above this client knows or cares
        what the workbook's columns are called.

        A configured column that the workbook does not actually have is a real failure, not
        something to write into the nearest column that looks similar.
        """
        self._require_tracker()
        mapping = settings.TRACKER_COLUMN_MAP
        headers = await self.table_columns()
        position = {name.strip().casefold(): index for index, name in enumerate(headers)}

        key_column = settings.TRACKER_KEY_COLUMN.strip()
        key_index = position.get(key_column.casefold())
        if key_index is None:
            raise GraphError(reason="tracker_key_column_missing")

        missing = [
            column
            for field, column in mapping.items()
            if field in fields and column.strip().casefold() not in position
        ]
        if missing:
            logger.warning("tracker_columns_missing", extra={"columns": missing})
            raise GraphError(reason="tracker_columns_missing")

        wanted_key = key_column.casefold()
        key_field = next(
            (field for field, column in mapping.items() if column.strip().casefold() == wanted_key),
            None,
        )
        key_value = str(fields.get(key_field, "") if key_field else "").strip()
        if not key_value:
            raise GraphError(reason="tracker_key_value_missing")

        existing = await self.find_table_row(key_index, key_value)
        # Start from the row that is already there, so a column this platform does not own - a
        # note somebody typed, a formula - survives the write untouched.
        row: list[Any] = (
            list(existing.values) + [None] * max(0, len(headers) - len(existing.values))
            if existing is not None
            else [None] * len(headers)
        )
        written: list[str] = []
        for field, column in mapping.items():
            if field not in fields:
                continue
            index = position[column.strip().casefold()]
            row[index] = fields[field]
            written.append(column)

        if existing is not None:
            await self.update_table_row(existing.index, row)
            return TrackerWriteResult(
                row_index=existing.index, created=False, columns_written=written
            )
        index = await self.add_table_row(row)
        return TrackerWriteResult(row_index=index, created=True, columns_written=written)

    # --- outbound: a reply on the original thread ---------------------------------------------
    #
    # Two calls, never one. `createReply` makes a draft that Graph has already threaded onto the
    # original conversation - correct References and In-Reply-To headers, quoted original, the
    # sender addressed - and `send` posts it. Keeping them apart is what makes a human approval
    # possible at all: the draft exists, is readable, and goes nowhere until somebody sends it.

    def _require_reply_enabled(self) -> None:
        if not settings.reply_configured:
            raise ReplyNotEnabledError(reason="not_enabled")

    async def create_reply_draft(self, message_id: str, body_text: str) -> str:
        """Draft a reply on `message_id`'s own thread. Returns the draft's id. Sends nothing.

        The body is posted as `text`, never as HTML. Nothing this platform composes needs markup,
        and a text body cannot carry a link, an image beacon or a script into a counterparty's
        mail client on our behalf.
        """
        self._require_reply_enabled()
        response = await self._request(
            "POST",
            self._mailbox_url(f"/messages/{message_id}/createReply"),
            json_body={"message": {"body": {"contentType": "text", "content": body_text}}},
        )
        draft_id = str((response.json() or {}).get("id") or "")
        if not draft_id:
            raise GraphError(reason="malformed_draft_response")
        return draft_id

    async def send_draft(self, draft_id: str) -> None:
        """Send a draft this platform created. The one call in this module that reaches outward."""
        self._require_reply_enabled()
        await self._request("POST", self._mailbox_url(f"/messages/{draft_id}/send"))

    async def delete_draft(self, draft_id: str) -> None:
        """Discard an unsent draft, so a withdrawn reply does not sit in the mailbox forever."""
        self._require_reply_enabled()
        await self._request("DELETE", self._mailbox_url(f"/messages/{draft_id}"))

    # --- change notifications ---------------------------------------------------------------

    async def create_subscription(self) -> dict[str, Any]:
        expires = datetime.now(timezone.utc) + timedelta(
            minutes=settings.GRAPH_SUBSCRIPTION_TTL_MINUTES
        )
        body = {
            "changeType": "created",
            "notificationUrl": settings.GRAPH_WEBHOOK_NOTIFICATION_URL,
            "resource": f"users/{settings.GRAPH_MAILBOX_ADDRESS}/mailFolders('inbox')/messages",
            "expirationDateTime": expires.strftime("%Y-%m-%dT%H:%M:%S.0000000Z"),
            "clientState": settings.GRAPH_WEBHOOK_CLIENT_STATE,
        }
        response = await self._request(
            "POST", f"{settings.GRAPH_BASE_URL.rstrip('/')}/subscriptions", json_body=body
        )
        return response.json()

    async def renew_subscription(self, subscription_id: str) -> dict[str, Any]:
        expires = datetime.now(timezone.utc) + timedelta(
            minutes=settings.GRAPH_SUBSCRIPTION_TTL_MINUTES
        )
        response = await self._request(
            "PATCH",
            f"{settings.GRAPH_BASE_URL.rstrip('/')}/subscriptions/{subscription_id}",
            json_body={"expirationDateTime": expires.strftime("%Y-%m-%dT%H:%M:%S.0000000Z")},
        )
        return response.json()

    async def delete_subscription(self, subscription_id: str) -> None:
        await self._request(
            "DELETE", f"{settings.GRAPH_BASE_URL.rstrip('/')}/subscriptions/{subscription_id}"
        )


_client: GraphClient | None = None


def get_graph_client() -> GraphClient:
    global _client
    if _client is None:
        _client = GraphClient()
    return _client


async def close_graph_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def resource_message_id(resource: str) -> str | None:
    """Pull the message id out of a change notification's resource path.

    Graph sends `Users/{id}/Messages/{messageId}` (casing varies by tenant), and for a folder
    subscription the trailing segment is always the message.
    """
    if not resource:
        return None
    segments = [segment for segment in resource.strip("/").split("/") if segment]
    if not segments:
        return None
    tail = segments[-1]
    if "(" in tail and tail.endswith(")"):
        tail = tail[tail.index("(") + 1 : -1].strip("'\"")
    return tail or None

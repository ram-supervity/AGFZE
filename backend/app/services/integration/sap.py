"""The SAP posting: a real adapter, and an honest, fully-working manual path behind it.

There is no confirmed SAP API, BAPI or OData endpoint for AGFZE anywhere in this platform's
governing material - not a missing detail, a genuinely open business question - so this module
ships no concrete client against a guessed contract. Writing one would produce code that looks
like an integration, fails on first contact with the real system, and meanwhile lets everybody
believe the platform posts to SAP.

What ships instead is both halves of the real answer:

* where a deployment has configured a base URL, a genuine HTTP posting is attempted against it,
  with the response handled properly - a reference on success, a real failure otherwise;
* where none is configured, which is the normal state today, the job reaches
  `awaiting_manual_action` carrying the complete, structured payload a person keys into SAP
  themselves.

The second path is the one AGFZE's own process describes: a human-supervised posting, assisted by
a Power Automate flow that a person runs. This platform prepares the data for it and stops there.
Nothing here triggers, calls or orchestrates that flow, and there is no code path that could.
"""

from __future__ import annotations

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.enums import IntegrationTargetSystem
from app.models.integration import IntegrationJob
from app.models.transactions import TradeTransaction
from app.services.integration.adapters import IntegrationOutcome
from app.services.integration.payloads import dms_document_reference, sap_payload

logger = get_logger(__name__)

MANUAL_INSTRUCTION = (
    "No SAP endpoint is configured on this deployment, so nothing has been posted. The trade "
    "contract and deal price record below are complete and taken straight from this "
    "transaction's own figures - key them into SAP, or run the assisted flow against them, and "
    "then confirm completion here with the SAP document number you get back."
)

# Status codes worth another automatic attempt. Anything SAP rejected on its merits - a 400, a
# 409, a 422 - will be rejected identically four more times, and turning that into a slow
# failure instead of an immediate one helps nobody.
RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({408, 425, 429, 500, 502, 503, 504})

# Where a real SAP posting's identifier is looked for in the response. Several spellings because
# the field name is exactly what is unconfirmed; a response carrying none of them is a success
# this platform cannot evidence, and is treated as a failure rather than invented around.
REFERENCE_KEYS: tuple[str, ...] = (
    "document_number",
    "documentNumber",
    "sap_document_number",
    "reference",
    "id",
    "objectId",
)


def _reference_from(payload: object) -> str | None:
    if isinstance(payload, dict):
        for key in REFERENCE_KEYS:
            value = payload.get(key)
            if isinstance(value, str | int) and str(value).strip():
                return str(value).strip()
        nested = payload.get("d") if isinstance(payload.get("d"), dict) else None
        if nested is not None:
            return _reference_from(nested)
    return None


def _auth() -> tuple[dict[str, str], httpx.BasicAuth | None]:
    """Credentials, read from configuration only, and never logged or returned anywhere."""
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if settings.SAP_API_KEY.strip():
        headers["APIKey"] = settings.SAP_API_KEY.strip()
    auth = (
        httpx.BasicAuth(settings.SAP_API_USERNAME, settings.SAP_API_PASSWORD)
        if settings.SAP_API_USERNAME.strip()
        else None
    )
    return headers, auth


class SapAdapter:
    target_system = IntegrationTargetSystem.SAP.value

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    @property
    def configured(self) -> bool:
        return settings.sap_configured

    def endpoint(self) -> str:
        base = settings.SAP_API_BASE_URL.rstrip("/")
        path = settings.SAP_POSTING_PATH.strip().lstrip("/")
        return f"{base}/{path}" if path else base

    async def run(
        self, session: AsyncSession, job: IntegrationJob, transaction: TradeTransaction
    ) -> IntegrationOutcome:
        # Read opportunistically and never waited on: if the DMS filing has not resolved yet, the
        # posting goes without its reference rather than the SAP job blocking on another target
        # system. See `payloads.dms_document_reference`.
        payload = sap_payload(
            transaction,
            dms_document_number=await dms_document_reference(session, transaction),
        )
        if not self.configured:
            return IntegrationOutcome.awaiting_manual_action(
                MANUAL_INSTRUCTION, payload=payload, reason="sap_not_configured"
            )

        headers, auth = _auth()
        try:
            if self._client is not None:
                response = await self._client.post(
                    self.endpoint(), json=payload, headers=headers, auth=auth
                )
            else:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(settings.SAP_TIMEOUT_SECONDS)
                ) as client:
                    response = await client.post(
                        self.endpoint(), json=payload, headers=headers, auth=auth
                    )
        except httpx.HTTPError as exc:
            # The provider's own message never reaches the caller or the job row; it can carry
            # the endpoint and, in some configurations, credentials in a URL.
            logger.warning("sap_post_transport_error", extra={"reason": type(exc).__name__})
            return IntegrationOutcome.failed(
                "SAP could not be reached.", retryable=True, reason="transport"
            )

        if response.status_code >= 400:
            logger.warning("sap_post_rejected", extra={"status_code": response.status_code})
            return IntegrationOutcome.failed(
                f"SAP rejected the posting with HTTP {response.status_code}.",
                retryable=response.status_code in RETRYABLE_STATUS_CODES,
                status_code=response.status_code,
            )

        try:
            body = response.json()
        except ValueError:
            body = None
        reference = _reference_from(body)
        if not reference:
            # A 200 with nothing identifying the posting is not evidence that anything was
            # created. Reported as a failure a person can look at, never as a success.
            logger.warning(
                "sap_post_without_reference", extra={"status_code": response.status_code}
            )
            return IntegrationOutcome.failed(
                "SAP accepted the request but returned no document number, so there is nothing "
                "to record as evidence of the posting.",
                retryable=False,
                status_code=response.status_code,
            )
        return IntegrationOutcome.succeeded(reference, status_code=response.status_code)

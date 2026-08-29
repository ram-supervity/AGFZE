"""The document-management upload: the same discipline as SAP, for the same reason.

The DMS exposes a REST API for upload. That is the whole of what is known about it - its endpoint
contract and its metadata schema are not specified anywhere in this platform's material - so this
adapter posts what a REST upload with metadata universally looks like against a configured base
URL, and prepares the compiled pack for a person to file when no base URL is configured.

The pack itself is real either way. It is compiled, stored and downloadable before this adapter
decides which path it is on, so the manual path is not "we did nothing": it is the finished
document pack, in the platform, ready to be dragged into the DMS.
"""

from __future__ import annotations

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.enums import IntegrationTargetSystem
from app.models.integration import IntegrationJob
from app.models.transactions import TradeTransaction
from app.services.integration import document_packs
from app.services.integration.adapters import IntegrationOutcome
from app.services.integration.payloads import dms_metadata
from app.services.storage import ObjectNotFoundError, get_storage_service

logger = get_logger(__name__)

MANUAL_INSTRUCTION = (
    "No document-management endpoint is configured on this deployment, so nothing has been "
    "uploaded. The document pack below has been compiled and stored, and can be downloaded from "
    "this transaction - file it in the DMS and confirm completion here with the document id it "
    "was filed under."
)

RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({408, 425, 429, 500, 502, 503, 504})

REFERENCE_KEYS: tuple[str, ...] = ("document_id", "documentId", "id", "reference", "objectId")


def _reference_from(payload: object) -> str | None:
    if isinstance(payload, dict):
        for key in REFERENCE_KEYS:
            value = payload.get(key)
            if isinstance(value, str | int) and str(value).strip():
                return str(value).strip()
    return None


class DmsAdapter:
    target_system = IntegrationTargetSystem.DMS.value

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    @property
    def configured(self) -> bool:
        return settings.dms_configured

    def endpoint(self) -> str:
        base = settings.DMS_API_BASE_URL.rstrip("/")
        path = settings.DMS_UPLOAD_PATH.strip().lstrip("/")
        return f"{base}/{path}" if path else base

    async def run(
        self, session: AsyncSession, job: IntegrationJob, transaction: TradeTransaction
    ) -> IntegrationOutcome:
        # Compiled first, whichever path this run takes. The pack is the deliverable; the upload
        # is only how it travels.
        compiled = await document_packs.compile_packs(session, transaction)
        packs = [result.pack for result in compiled]
        summary = [
            {
                "pack_type": result.pack.pack_type,
                "filename": result.pack.filename,
                "storage_ref": result.pack.storage_ref,
                "byte_size": result.pack.byte_size,
                "documents_merged": len(result.merged_ids),
                "attached_separately": result.attached_separately,
            }
            for result in compiled
        ]

        if not packs:
            # Nothing to file is not a failure and is not a fabricated success: this transaction
            # carries no leg that defines a pack, and a person needs to know that rather than see
            # a green tick.
            return IntegrationOutcome.awaiting_manual_action(
                "This transaction has no document pack to file - it carries no purchase, sales "
                "or FA leg to compile one from. File whatever paperwork exists in the DMS by "
                "hand and confirm completion here.",
                payload={"packs": summary},
                reason="no_pack",
            )

        if not self.configured:
            return IntegrationOutcome.awaiting_manual_action(
                MANUAL_INSTRUCTION,
                payload={
                    "packs": summary,
                    "metadata": [dms_metadata(transaction, pack) for pack in packs],
                },
                reason="dms_not_configured",
            )

        storage = get_storage_service()
        headers = {"Accept": "application/json"}
        if settings.DMS_API_KEY.strip():
            headers["Authorization"] = f"Bearer {settings.DMS_API_KEY.strip()}"
        auth = (
            httpx.BasicAuth(settings.DMS_API_USERNAME, settings.DMS_API_PASSWORD)
            if settings.DMS_API_USERNAME.strip()
            else None
        )

        references: list[str] = []
        for pack in packs:
            try:
                content = await storage.download(pack.storage_ref)
            except ObjectNotFoundError:
                return IntegrationOutcome.failed(
                    f"The compiled pack {pack.filename} could not be read from storage.",
                    retryable=False,
                    pack_type=pack.pack_type,
                )

            metadata = dms_metadata(transaction, pack)
            try:
                if self._client is not None:
                    response = await self._client.post(
                        self.endpoint(),
                        files={"file": (pack.filename, content, document_packs.PDF_CONTENT_TYPE)},
                        data={key: str(value) for key, value in metadata.items()},
                        headers=headers,
                        auth=auth,
                    )
                else:
                    async with httpx.AsyncClient(
                        timeout=httpx.Timeout(settings.DMS_TIMEOUT_SECONDS)
                    ) as client:
                        response = await client.post(
                            self.endpoint(),
                            files={
                                "file": (
                                    pack.filename,
                                    content,
                                    document_packs.PDF_CONTENT_TYPE,
                                )
                            },
                            data={key: str(value) for key, value in metadata.items()},
                            headers=headers,
                            auth=auth,
                        )
            except httpx.HTTPError as exc:
                logger.warning("dms_upload_transport_error", extra={"reason": type(exc).__name__})
                return IntegrationOutcome.failed(
                    "The document-management system could not be reached.",
                    retryable=True,
                    reason="transport",
                )

            if response.status_code >= 400:
                logger.warning("dms_upload_rejected", extra={"status_code": response.status_code})
                return IntegrationOutcome.failed(
                    f"The document-management system rejected {pack.filename} with HTTP "
                    f"{response.status_code}.",
                    retryable=response.status_code in RETRYABLE_STATUS_CODES,
                    status_code=response.status_code,
                )

            try:
                body = response.json()
            except ValueError:
                body = None
            reference = _reference_from(body)
            if not reference:
                return IntegrationOutcome.failed(
                    f"The document-management system accepted {pack.filename} but returned no "
                    "document id, so there is nothing to record as evidence of the upload.",
                    retryable=False,
                    status_code=response.status_code,
                )
            references.append(reference)
            await document_packs.mark_filed(session, [pack], dms_document_id=reference)

        return IntegrationOutcome.succeeded(
            ", ".join(references), packs=[pack.filename for pack in packs]
        )

"""Resolution of the short-lived signed URLs the document API hands out.

The authenticated endpoints (`GET /documents/{id}`) mint these links; this route only verifies
the HMAC and the expiry the storage service issued. No raw filesystem path is ever accepted, no
link outlives its TTL, and there is no permanent public URL for any document or page image.
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import Response
from starlette.requests import Request

from app.core.config import settings
from app.core.errors import NotFoundError
from app.core.logging import get_logger
from app.services.storage import ObjectNotFoundError, StorageError, get_storage_service

logger = get_logger(__name__)

router = APIRouter(prefix="/internal/files", tags=["files"], include_in_schema=False)

# Guessed from the key's suffix, never from anything a client sent.
_CONTENT_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "pdf": "application/pdf",
    "csv": "text/csv",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xls": "application/vnd.ms-excel",
    "eml": "message/rfc822",
}


def _content_type(key: str) -> str:
    suffix = key.rsplit(".", 1)[-1].lower() if "." in key else ""
    return _CONTENT_TYPES.get(suffix, "application/octet-stream")


@router.get("/{key:path}")
async def serve_signed_object(
    request: Request,
    key: str,
    expires: int = Query(...),
    signature: str = Query(..., min_length=16, max_length=256),
) -> Response:
    try:
        data = await get_storage_service().resolve_signed_request(key, expires, signature)
    except ObjectNotFoundError as exc:
        raise NotFoundError("File not found.") from exc
    except StorageError as exc:
        # An invalid signature, an expired link and a missing object are indistinguishable from
        # the outside, so a stale link cannot be used to probe which keys exist.
        logger.info("signed_url_rejected", extra={"reason": type(exc).__name__})
        raise NotFoundError("File not found.") from exc

    return Response(
        content=data,
        media_type=_content_type(key),
        headers={
            "Cache-Control": f"private, max-age={settings.STORAGE_SIGNED_URL_TTL_SECONDS}",
            "Content-Disposition": "inline",
            "X-Content-Type-Options": "nosniff",
            # A document page is never a same-origin script's business and never framed.
            "Content-Security-Policy": "default-src 'none'; img-src 'self'; sandbox",
        },
    )

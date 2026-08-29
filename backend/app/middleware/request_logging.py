from __future__ import annotations

import time
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import get_logger

logger = get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """One structured line per request. Carries the user id when the request was authenticated,
    never the email address and never any part of the token."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid4().hex
        request.state.request_id = request_id
        started = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "request_failed", extra=self._fields(request, request_id, None, started)
            )
            raise

        logger.info(
            "request_completed",
            extra=self._fields(request, request_id, response.status_code, started),
        )
        response.headers[REQUEST_ID_HEADER] = request_id
        return response

    @staticmethod
    def _fields(
        request: Request, request_id: str, status_code: int | None, started: float
    ) -> dict[str, object]:
        fields: dict[str, object] = {
            "method": request.method,
            "path": request.url.path,
            "status_code": status_code,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "request_id": request_id,
        }
        user_id = getattr(request.state, "user_id", None)
        if user_id:
            fields["user_id"] = user_id
        return fields

"""Rate limiting: a default ceiling for everything, and real per-category limits on top of it.

`slowapi` has been installed since  as a switch with a single default limit behind it, and
that was honest for a foundation - there was nothing worth protecting individually yet. There is
now, and this  names the four categories this platform's specification identifies as the ones
most exposed to abuse or accidental overload, gives each a specific value, and enforces them in
running code rather than describing them in a document.

Two layers, in this order:

1. **Category limits**, matched on method and path, evaluated first because they are tighter.
   A request that exhausts its category's window is refused with 429 before the default ceiling
   is ever consulted.
2. **The default ceiling**, applied by `slowapi`'s own middleware to everything else.

Both read from the same `limits` storage, so pointing `RATE_LIMIT_STORAGE_URI` at Redis makes
every limit count across a fleet rather than per process.

Health probes are exempt from both. An orchestrator polls them continuously by design, and a
readiness probe that starts answering 429 would take a healthy instance out of rotation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from limits import RateLimitItem, parse
from limits.storage import storage_from_string
from limits.strategies import MovingWindowRateLimiter
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from starlette.middleware.base import RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

PREFIX = settings.API_V1_PREFIX

EXEMPT_PATH_PREFIXES = ("/health", f"{PREFIX}/health")


def client_key(request: Request) -> str:
    """Who this request is counted against.

    The forwarded address is used only where a proxy this deployment controls is known to set it.
    Anywhere else the header is client-supplied, and honouring it would let one caller present a
    fresh identity per request and never hit a limit at all.
    """
    if settings.RATE_LIMIT_TRUST_FORWARDED_FOR:
        forwarded = request.headers.get("x-forwarded-for", "")
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return get_remote_address(request)


limiter = Limiter(
    key_func=client_key,
    default_limits=[settings.RATE_LIMIT_DEFAULT],
    enabled=settings.RATE_LIMIT_ENABLED,
    storage_uri=settings.RATE_LIMIT_STORAGE_URI,
)


@dataclass(frozen=True)
class LimitCategory:
    """One named category, its configured limit, and the requests it covers."""

    name: str
    limit: str
    methods: frozenset[str]
    pattern: re.Pattern[str]

    def covers(self, method: str, path: str) -> bool:
        return method.upper() in self.methods and self.pattern.fullmatch(path) is not None


UUID_SEGMENT = r"[0-9a-fA-F-]{8,36}"


def categories() -> tuple[LimitCategory, ...]:
    """The four categories the specification names, plus the unauthenticated webhook.

    Ordered most specific first: bulk approval is matched before anything broader could claim it.
    Read from settings on every call rather than captured at import, so a test can move a limit
    without reimporting the module.
    """
    return (
        LimitCategory(
            "bulk_approval",
            settings.RATE_LIMIT_BULK_APPROVAL,
            frozenset({"POST"}),
            re.compile(rf"{re.escape(PREFIX)}/approvals/bulk-decide/?"),
        ),
        LimitCategory(
            "upload",
            settings.RATE_LIMIT_UPLOAD,
            frozenset({"POST"}),
            re.compile(rf"{re.escape(PREFIX)}/documents/upload/?"),
        ),
        LimitCategory(
            # Every write that can reach the model: reclassification and confirmation on
            # correction, draft generation, and a report whose narrative paragraph is generated.
            "ai",
            settings.RATE_LIMIT_AI,
            frozenset({"POST"}),
            re.compile(
                rf"{re.escape(PREFIX)}/(?:"
                rf"documents/{UUID_SEGMENT}/(?:reclassify|confirm)"
                rf"|transactions/{UUID_SEGMENT}/generate-draft"
                rf"|reports"
                rf")/?"
            ),
        ),
        LimitCategory(
            # The one *read* that can reach the model. Opening an approval generates its summary
            # on first view, so it costs a model call however innocuous the verb looks. It shares
            # the AI category's window, because it shares the AI category's bill.
            "ai",
            settings.RATE_LIMIT_AI,
            frozenset({"GET"}),
            re.compile(rf"{re.escape(PREFIX)}/approvals/{UUID_SEGMENT}/?"),
        ),
        LimitCategory(
            # Authentication-adjacent: the profile call every sign-in makes, which is also the
            # endpoint that provisions an account the first time a token is seen, and the
            # preference write beside it.
            "auth",
            settings.RATE_LIMIT_AUTH,
            frozenset({"GET", "PATCH"}),
            re.compile(rf"{re.escape(PREFIX)}/users/me(?:/preferences)?/?"),
        ),
        LimitCategory(
            "webhook",
            settings.RATE_LIMIT_WEBHOOK,
            frozenset({"POST"}),
            re.compile(rf"{re.escape(PREFIX)}/graph/notifications/?"),
        ),
    )


def category_for(method: str, path: str) -> LimitCategory | None:
    for category in categories():
        if category.covers(method, path):
            return category
    return None


_storage = storage_from_string(settings.RATE_LIMIT_STORAGE_URI)
_strategy = MovingWindowRateLimiter(_storage)
_parsed: dict[str, RateLimitItem] = {}


def _item(limit: str) -> RateLimitItem | None:
    if limit not in _parsed:
        try:
            _parsed[limit] = parse(limit)
        except ValueError:
            logger.error("rate_limit_unparseable", extra={"limit": limit})
            return None
    return _parsed[limit]


def within_category_limit(category: LimitCategory, key: str) -> bool:
    """Consume one unit of this category's window for this caller. False means refuse."""
    item = _item(category.limit)
    if item is None:
        # An unparseable limit must not become an open door *or* a closed one. It is a
        # configuration error, already logged; the default ceiling still applies underneath.
        return True
    return bool(_strategy.hit(item, category.name, key))


def is_exempt(path: str) -> bool:
    return path.startswith(EXEMPT_PATH_PREFIXES)


class HealthExemptSlowAPIMiddleware(SlowAPIMiddleware):
    """Category limits first, then the default ceiling, and neither on a probe."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if is_exempt(request.url.path):
            return await call_next(request)

        if settings.RATE_LIMIT_ENABLED:
            category = category_for(request.method, request.url.path)
            if category is not None and not within_category_limit(category, client_key(request)):
                logger.warning(
                    "rate_limited",
                    extra={"category": category.name, "path": request.url.path},
                )
                return _refusal(request, category)

        try:
            return await super().dispatch(request, call_next)
        except RateLimitExceeded as exc:
            # Middleware sits outside Starlette's exception middleware, so the registered handler
            # would never see this one; per-route limits still reach it normally.
            return await _handle_rate_limit_exceeded(request, exc)


def _envelope(message: str) -> dict[str, Any]:
    return {
        "success": False,
        "data": None,
        "message": message,
        "errors": [{"code": "rate_limited", "message": message, "field": None}],
    }


def _headers(request: Request) -> dict[str, str] | None:
    request_id = getattr(request.state, "request_id", None)
    return {"X-Request-ID": request_id} if request_id else None


def _refusal(request: Request, category: LimitCategory) -> JSONResponse:
    # The category is named and its limit is not. Telling a caller which bucket they are in helps
    # a legitimate integration back off; telling them exactly how many they have left tells
    # somebody probing how fast they may probe.
    message = f"Too many {category.name.replace('_', ' ')} requests. Please retry in a moment."
    return JSONResponse(status_code=429, content=_envelope(message), headers=_headers(request))


async def _handle_rate_limit_exceeded(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    message = "Too many requests. Please retry in a moment."
    return JSONResponse(status_code=429, content=_envelope(message), headers=_headers(request))


def install_rate_limiting(app: FastAPI) -> None:
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _handle_rate_limit_exceeded)
    app.add_middleware(HealthExemptSlowAPIMiddleware)

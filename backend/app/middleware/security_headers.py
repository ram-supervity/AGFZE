"""The response headers that are the same on every API response, whatever produced it.

Nothing here is a substitute for the checks the endpoints themselves make; these are the headers a
browser needs in order not to undo them. The frontend carries the Content-Security-Policy that
governs the application's own pages - this API serves no pages, so its policy is the strictest one
there is: nothing may load, nothing may frame it, and nothing may be inferred from a guessed
content type.

HSTS is emitted only over HTTPS and only in production. Pinning a browser to HTTPS from a local
plain-HTTP stack would make that stack unreachable in the same browser afterwards, which is a real
cost for no security gain on a laptop.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import settings

# An API that returns JSON needs no script, style, image, font, frame or connection of its own.
# `frame-ancestors 'none'` is what actually stops this origin being framed in a modern browser;
# `X-Frame-Options` is kept beside it for the ones that do not read the CSP.
API_CONTENT_SECURITY_POLICY = (
    "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
)

STATIC_HEADERS: dict[str, str] = {
    "Content-Security-Policy": API_CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    # No page here asks for a device capability, so every one of them is denied outright.
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    # A signed document link and an audit export are per-caller answers; no shared cache may keep
    # either of them.
    "Cache-Control": "no-store",
}


def is_secure(request: Request) -> bool:
    """Whether this request genuinely arrived over TLS, including through the load balancer."""
    forwarded = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    return forwarded == "https" or request.url.scheme == "https"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        for header, value in STATIC_HEADERS.items():
            response.headers.setdefault(header, value)
        if settings.is_production and is_secure(request):
            response.headers.setdefault(
                "Strict-Transport-Security",
                f"max-age={settings.HSTS_MAX_AGE_SECONDS}; includeSubDomains; preload",
            )
        return response

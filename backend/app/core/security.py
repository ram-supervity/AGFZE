from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

import httpx
from jose import jwt
from jose.exceptions import JOSEError, JWTClaimsError

from app.core.config import settings
from app.core.logging import get_logger
from app.core.roles import normalise_roles

logger = get_logger(__name__)

JWKS_TIMEOUT_SECONDS = 5.0


class TokenError(Exception):
    """Access token could not be verified. Never carries the token or any part of it."""


def _default_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=httpx.Timeout(JWKS_TIMEOUT_SECONDS))


class JWKSClient:
    """Caches the identity provider's signing keys by `kid` for the lifetime of the process."""

    def __init__(
        self,
        jwks_url: str,
        http_client_factory: Callable[[], httpx.AsyncClient] = _default_http_client,
        ttl_seconds: int = 3600,
    ) -> None:
        self._jwks_url = jwks_url
        self._http_client_factory = http_client_factory
        self._ttl_seconds = ttl_seconds
        self._keys: dict[str, dict[str, Any]] = {}
        self._fetched_at = 0.0
        self._lock = asyncio.Lock()

    async def get_key(self, kid: str) -> dict[str, Any]:
        cached = self._cached_key(kid)
        if cached is not None:
            return cached
        await self.refresh()
        key = self._keys.get(kid)
        if key is None:
            raise TokenError("Token was signed with a key the identity provider does not publish.")
        return key

    async def refresh(self) -> None:
        generation = self._fetched_at
        async with self._lock:
            # A concurrent miss may have refreshed while this call waited for the lock.
            if self._fetched_at != generation:
                return
            if not self._jwks_url:
                raise TokenError("No JWKS endpoint is configured for token verification.")
            try:
                async with self._http_client_factory() as client:
                    response = await client.get(self._jwks_url)
                    response.raise_for_status()
                    document = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning(
                    "jwks_fetch_failed",
                    extra={"jwks_url": self._jwks_url, "reason": type(exc).__name__},
                )
                raise TokenError("Signing keys could not be retrieved.") from exc
            keys = {
                key["kid"]: key
                for key in document.get("keys", [])
                if isinstance(key, dict) and key.get("kid")
            }
            if not keys:
                raise TokenError("The identity provider published no usable signing keys.")
            self._keys = keys
            self._fetched_at = time.monotonic()

    def clear(self) -> None:
        self._keys = {}
        self._fetched_at = 0.0

    def _cached_key(self, kid: str) -> dict[str, Any] | None:
        if not self._keys or time.monotonic() - self._fetched_at > self._ttl_seconds:
            return None
        return self._keys.get(kid)


jwks_client = JWKSClient(settings.KEYCLOAK_JWKS_URL)


async def decode_access_token(token: str) -> dict:
    try:
        header = jwt.get_unverified_header(token)
    except JOSEError as exc:
        raise TokenError("Access token header could not be read.") from exc

    kid = header.get("kid")
    if not kid:
        raise TokenError("Access token does not name a signing key.")

    key = await jwks_client.get_key(kid)
    try:
        return jwt.decode(
            token,
            key,
            algorithms=settings.JWT_ALGORITHMS,
            audience=settings.KEYCLOAK_AUDIENCE,
            issuer=settings.KEYCLOAK_ISSUER,
            options={"leeway": settings.JWT_LEEWAY_SECONDS},
        )
    except JWTClaimsError:
        return _decode_with_azp_audience(token, key)
    except JOSEError as exc:
        raise TokenError("Access token could not be verified.") from exc


def _decode_with_azp_audience(token: str, key: dict[str, Any]) -> dict:
    # Keycloak identifies the requesting client in `azp` and often leaves it out of `aud`, so a
    # claims failure is retried once with the audience checked here instead of by the library.
    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=settings.JWT_ALGORITHMS,
            issuer=settings.KEYCLOAK_ISSUER,
            options={"leeway": settings.JWT_LEEWAY_SECONDS, "verify_aud": False},
        )
    except JOSEError as exc:
        raise TokenError("Access token could not be verified.") from exc

    expected = settings.KEYCLOAK_AUDIENCE
    audience = claims.get("aud")
    accepted = (
        claims.get("azp") == expected
        or audience == expected
        or (isinstance(audience, list | tuple) and expected in audience)
    )
    if not accepted:
        raise TokenError("Access token was not issued for this application.")
    return claims


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list | tuple):
        return [item for item in value if isinstance(item, str)]
    return []


def extract_roles(claims: dict) -> list[str]:
    realm_access = claims.get("realm_access")
    resource_access = claims.get("resource_access")
    client_access = (
        resource_access.get(settings.KEYCLOAK_AUDIENCE)
        if isinstance(resource_access, dict)
        else None
    )
    raw = (
        _string_list(realm_access.get("roles") if isinstance(realm_access, dict) else None)
        + _string_list(client_access.get("roles") if isinstance(client_access, dict) else None)
        + _string_list(claims.get("roles"))
    )
    return normalise_roles(raw)


def extract_identity(claims: dict) -> tuple[str, str, str, str | None]:
    subject_id = claims.get("sub") or ""
    if not isinstance(subject_id, str) or not subject_id:
        raise TokenError("Access token does not carry a subject.")

    username = claims.get("preferred_username") or ""
    email = claims.get("email") or username
    if not isinstance(email, str) or not email:
        raise TokenError("Access token does not carry an email address or username.")

    display_name = claims.get("name") or username or email.split("@")[0]
    entra_object_id = claims.get("oid") or claims.get("entra_oid") or None
    if entra_object_id is not None and not isinstance(entra_object_id, str):
        entra_object_id = str(entra_object_id)

    return subject_id, email, str(display_name), entra_object_id

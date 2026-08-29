"""Keycloak's Admin REST API, for the one thing this platform ever asks of it.

Roles reach this platform through the token, mapped from Entra ID groups by the identity broker,
and that is how they should reach it. This client exists for the exception AGFZE asked for: a
person whose group membership is wrong, or not yet propagated, and who needs their role corrected
today rather than after the next directory sync.

The credential behind it is a third machine identity, separate from both the human-login OIDC
client and the Graph app registration, and it holds one grant - `manage-users` on the realm. It
is read from configuration only. It is never logged, never returned by any endpoint, and no
response body from Keycloak is ever echoed to a caller: the error a caller sees says what failed,
not what the identity provider said about its own internals.

Every call here is synchronous with respect to the request that made it. The admin endpoint waits
for a confirmed success from Keycloak before it touches a single local row - see
`app.api.v1.admin.update_user_roles` - because a local role change Keycloak never accepted is a
lie the next sign-in would silently overwrite.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from app.core.config import settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.core.roles import ALL_ROLES, normalise_roles

logger = get_logger(__name__)

# Refreshed this far ahead of expiry so an in-flight call never races the token running out.
TOKEN_REFRESH_MARGIN_SECONDS = 30


class KeycloakAdminError(AppError):
    """The identity provider could not be reached, or refused the change.

    502 rather than 500: nothing local is wrong, and nothing local has been changed.
    """

    status_code = 502
    code = "identity_provider_unavailable"
    message = (
        "The identity provider could not be reached, so no role was changed. "
        "Nothing on this platform was altered."
    )

    def __init__(self, message: str | None = None, *, reason: str = "unknown") -> None:
        super().__init__(message)
        self.reason = reason


class KeycloakAdminNotConfiguredError(KeycloakAdminError):
    status_code = 503
    code = "identity_admin_not_configured"
    message = (
        "This deployment has no Keycloak Admin API credential configured, so role assignment "
        "cannot be changed from here. Roles continue to arrive from the identity provider on "
        "every sign-in."
    )


class KeycloakUserNotFoundError(KeycloakAdminError):
    status_code = 404
    code = "identity_user_not_found"
    message = "The identity provider has no account matching this user."


class KeycloakAdminClient:
    """One pooled HTTP client and one cached service-account token per process."""

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        self._http = http_client
        self._owns_http = http_client is None
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._token_lock = asyncio.Lock()

    # --- plumbing -----------------------------------------------------------------------------

    @property
    def http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                timeout=httpx.Timeout(settings.KEYCLOAK_ADMIN_TIMEOUT_SECONDS),
                limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
            )
        return self._http

    async def aclose(self) -> None:
        if self._http is not None and self._owns_http:
            await self._http.aclose()
        self._http = None

    def clear_token(self) -> None:
        self._token = None
        self._token_expires_at = 0.0

    @property
    def realm_base(self) -> str:
        return f"{settings.KEYCLOAK_SERVER_URL.rstrip('/')}/admin/realms/{settings.KEYCLOAK_REALM}"

    def _require_configuration(self) -> None:
        if not settings.keycloak_admin_configured:
            raise KeycloakAdminNotConfiguredError(reason="missing_credentials")

    # --- authentication -----------------------------------------------------------------------

    async def access_token(self) -> str:
        self._require_configuration()
        if self._token and time.monotonic() < self._token_expires_at:
            return self._token

        async with self._token_lock:
            if self._token and time.monotonic() < self._token_expires_at:
                return self._token

            url = (
                f"{settings.KEYCLOAK_SERVER_URL.rstrip('/')}/realms/{settings.KEYCLOAK_REALM}"
                "/protocol/openid-connect/token"
            )
            try:
                response = await self.http.post(
                    url,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": settings.KEYCLOAK_ADMIN_CLIENT_ID,
                        "client_secret": settings.KEYCLOAK_ADMIN_CLIENT_SECRET,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
            except httpx.HTTPError as exc:
                logger.warning(
                    "keycloak_admin_token_transport_error", extra={"reason": type(exc).__name__}
                )
                raise KeycloakAdminError(reason="transport") from exc

            if response.status_code != 200:
                # Status only. The body echoes the client id and can echo the realm's own
                # diagnostics, and neither belongs in a log line.
                logger.warning(
                    "keycloak_admin_token_rejected",
                    extra={"status_code": response.status_code},
                )
                raise KeycloakAdminError(reason="authentication")

            payload = response.json()
            token = payload.get("access_token")
            if not isinstance(token, str) or not token:
                raise KeycloakAdminError(reason="malformed_token_response")

            expires_in = payload.get("expires_in")
            lifetime = int(expires_in) if isinstance(expires_in, int | float | str) else 60
            self._token = token
            self._token_expires_at = time.monotonic() + max(
                0, lifetime - TOKEN_REFRESH_MARGIN_SECONDS
            )
            return token

    async def _request(
        self,
        method: str,
        url: str,
        *,
        json_body: Any = None,
        params: dict[str, Any] | None = None,
        expected: tuple[int, ...] = (200, 201, 204),
    ) -> httpx.Response:
        token = await self.access_token()
        try:
            response = await self.http.request(
                method,
                url,
                json=json_body,
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.HTTPError as exc:
            logger.warning(
                "keycloak_admin_transport_error",
                extra={"method": method, "reason": type(exc).__name__},
            )
            raise KeycloakAdminError(reason="transport") from exc

        if response.status_code == 401:
            # One retry on a token the server has stopped accepting, and one only.
            self.clear_token()
            token = await self.access_token()
            try:
                response = await self.http.request(
                    method,
                    url,
                    json=json_body,
                    params=params,
                    headers={"Authorization": f"Bearer {token}"},
                )
            except httpx.HTTPError as exc:
                raise KeycloakAdminError(reason="transport") from exc

        if response.status_code == 404:
            raise KeycloakUserNotFoundError(reason="not_found")
        if response.status_code not in expected:
            logger.warning(
                "keycloak_admin_request_rejected",
                extra={"method": method, "status_code": response.status_code},
            )
            raise KeycloakAdminError(reason=f"http_{response.status_code}")
        return response

    # --- users and their realm roles -----------------------------------------------------------

    async def find_user_id(self, *, subject_id: str, email: str) -> str:
        """The Keycloak user id behind one of this platform's accounts.

        `subject_id` is the `sub` claim, which for a Keycloak-issued token is the user id itself,
        so that is tried first and costs one lookup. An account brokered from Entra ID through a
        different subject format falls back to an exact email search, which is the only other
        identifier the two systems are guaranteed to share.
        """
        self._require_configuration()
        if subject_id:
            try:
                response = await self._request(
                    "GET", f"{self.realm_base}/users/{subject_id}", expected=(200,)
                )
                found = response.json()
                if isinstance(found, dict) and found.get("id"):
                    return str(found["id"])
            except KeycloakUserNotFoundError:
                pass

        if not email:
            raise KeycloakUserNotFoundError(reason="no_identifier")

        response = await self._request(
            "GET",
            f"{self.realm_base}/users",
            params={"email": email, "exact": "true", "max": 2},
            expected=(200,),
        )
        rows = response.json()
        if not isinstance(rows, list) or len(rows) != 1 or not rows[0].get("id"):
            raise KeycloakUserNotFoundError(reason="ambiguous_or_missing")
        return str(rows[0]["id"])

    async def realm_role(self, name: str) -> dict[str, Any]:
        response = await self._request("GET", f"{self.realm_base}/roles/{name}", expected=(200,))
        role = response.json()
        if not isinstance(role, dict) or not role.get("id"):
            raise KeycloakAdminError(reason="malformed_role_response")
        return {"id": role["id"], "name": role.get("name", name)}

    async def current_platform_roles(self, keycloak_user_id: str) -> list[str]:
        """The platform roles Keycloak currently holds for this account.

        Realm roles Keycloak owns for its own purposes - `default-roles-*`, `offline_access`,
        `uma_authorization` - are filtered out and are never touched by anything here.
        """
        response = await self._request(
            "GET",
            f"{self.realm_base}/users/{keycloak_user_id}/role-mappings/realm",
            expected=(200,),
        )
        rows = response.json()
        names = [
            str(row.get("name"))
            for row in rows
            if isinstance(row, dict) and row.get("name") in ALL_ROLES
        ]
        return normalise_roles(names)

    async def set_platform_roles(
        self, keycloak_user_id: str, roles: list[str]
    ) -> tuple[list[str], list[str]]:
        """Make Keycloak's platform role mapping match `roles` exactly.

        Returns what was added and what was removed, so the caller can put the real difference on
        the audit trail rather than a restatement of what it asked for. Roles outside this
        platform's own vocabulary are never added and never removed.
        """
        wanted = set(normalise_roles(roles))
        held = set(await self.current_platform_roles(keycloak_user_id))
        to_add = normalise_roles(wanted - held)
        to_remove = normalise_roles(held - wanted)

        mappings = f"{self.realm_base}/users/{keycloak_user_id}/role-mappings/realm"
        if to_add:
            await self._request(
                "POST",
                mappings,
                json_body=[await self.realm_role(name) for name in to_add],
                expected=(204, 200),
            )
        if to_remove:
            await self._request(
                "DELETE",
                mappings,
                json_body=[await self.realm_role(name) for name in to_remove],
                expected=(204, 200),
            )
        return to_add, to_remove


_client: KeycloakAdminClient | None = None


def get_keycloak_admin_client() -> KeycloakAdminClient:
    global _client
    if _client is None:
        _client = KeycloakAdminClient()
    return _client


def set_keycloak_admin_client(client: KeycloakAdminClient | None) -> None:
    """Swap the process client. The test suite drives a fake through this, nothing else does."""
    global _client
    _client = client


async def close_keycloak_admin_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None

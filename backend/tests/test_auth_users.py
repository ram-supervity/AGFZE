"""Token verification, just-in-time provisioning and role enforcement."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Annotated

import pytest
from fastapi import APIRouter, Depends, FastAPI
from httpx import AsyncClient
from jose import jwt
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import require_roles
from app.core.roles import PlatformRole
from app.models import AuditEvent, User
from app.services.audit_service import AuditEventType
from tests.utils.tokens import (
    ALGORITHM,
    PRIVATE_PEM,
    auth_header,
    build_token,
    expired_token,
)

pytestmark = pytest.mark.usefixtures("patched_jwks")

ME_URL = "/api/v1/users/me"
PROBE_URL = "/probe/admin-only"


def assert_error_envelope(payload: dict, code: str) -> None:
    assert payload["success"] is False
    assert payload["data"] is None
    assert payload["message"]
    assert code in json.dumps(payload)


def install_probe_router(app: FastAPI) -> None:
    """A throwaway route so require_roles is exercised without inventing a real endpoint."""
    router = APIRouter(prefix="/probe")

    @router.get("/admin-only")
    async def admin_only(
        user: Annotated[User, Depends(require_roles(PlatformRole.ADMIN.value))],
    ) -> dict[str, str]:
        return {"subject_id": user.subject_id}

    app.include_router(router)


async def test_a_request_without_credentials_is_rejected(client: AsyncClient) -> None:
    response = await client.get(ME_URL)
    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Bearer")
    assert_error_envelope(response.json(), "unauthenticated")


async def test_a_malformed_token_is_rejected(client: AsyncClient) -> None:
    response = await client.get(ME_URL, headers=auth_header("this.is.not-a-jwt"))
    assert response.status_code == 401
    assert_error_envelope(response.json(), "unauthenticated")


async def test_an_expired_token_is_rejected(client: AsyncClient) -> None:
    response = await client.get(ME_URL, headers=auth_header(expired_token()))
    assert response.status_code == 401
    assert_error_envelope(response.json(), "unauthenticated")


async def test_a_token_signed_by_an_unknown_key_is_rejected(client: AsyncClient) -> None:
    token = jwt.encode(
        {"iss": settings.KEYCLOAK_ISSUER, "aud": settings.KEYCLOAK_AUDIENCE, "sub": "unknown"},
        PRIVATE_PEM,
        algorithm=ALGORITHM,
        headers={"kid": "a-key-the-provider-never-published"},
    )
    response = await client.get(ME_URL, headers=auth_header(token))
    assert response.status_code == 401


async def test_a_valid_token_provisions_the_user_with_normalised_roles(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    subject_id = "9a4b1d5c-0000-4000-8000-0000000000d1"
    token = build_token(
        sub=subject_id,
        email="dual.user@agfze.ae",
        preferred_username="dual.user",
        name="Nadia Farouk",
        realm_access={
            "roles": [
                "offline_access",
                "purchase_user",
                "uma_authorization",
                "default-roles-agfze",
                "approver_hod",
                "purchase_user",
            ]
        },
    )

    response = await client.get(ME_URL, headers=auth_header(token))
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["subject_id"] == subject_id
    assert data["email"] == "dual.user@agfze.ae"
    assert data["display_name"] == "Nadia Farouk"
    assert data["roles"] == ["approver_hod", "purchase_user"]
    assert data["is_active"] is True
    assert data["notification_channel"] == "in_app"

    user = (await db_session.scalars(select(User).where(User.subject_id == subject_id))).one()
    assert user.roles == ["approver_hod", "purchase_user"]
    assert user.last_login_at is not None


async def test_a_token_carrying_the_client_id_in_azp_is_accepted(client: AsyncClient) -> None:
    """Keycloak reports the client in `azp` and routinely leaves it out of `aud`."""
    token = build_token(
        sub="6b2e7f10-0000-4000-8000-0000000000d2",
        aud="account",
        email="finance.user@agfze.ae",
        name="Tomas Ceballos",
        realm_access={"roles": ["finance_user"]},
    )
    response = await client.get(ME_URL, headers=auth_header(token))
    assert response.status_code == 200
    assert response.json()["data"]["roles"] == ["finance_user"]


def moment(rendered: str) -> datetime:
    """Parse a timestamp the API rendered.

    The envelope serialises UTC with a trailing Z, which `fromisoformat` only learned to read in
    3.11. The deployed image is 3.12, but the suite has to keep passing on the oldest interpreter
    the project claims to be importable on rather than on the newest one it happens to run under.
    """
    return datetime.fromisoformat(rendered.replace("Z", "+00:00"))


async def test_provisioning_is_recorded_once_and_login_time_advances(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = build_token(
        sub="c81f3a92-0000-4000-8000-0000000000d3",
        email="fa.user@agfze.ae",
        preferred_username="fa.user",
        name="Daniel Okafor",
        realm_access={"roles": ["fa_user"]},
    )

    first = await client.get(ME_URL, headers=auth_header(token))
    assert first.status_code == 200
    await asyncio.sleep(0.01)
    second = await client.get(ME_URL, headers=auth_header(token))
    assert second.status_code == 200

    first_login = moment(first.json()["data"]["last_login_at"])
    second_login = moment(second.json()["data"]["last_login_at"])
    assert second_login > first_login
    assert first.json()["data"]["id"] == second.json()["data"]["id"]

    assert await db_session.scalar(select(func.count()).select_from(User)) == 1
    provisioned = await db_session.scalar(
        select(func.count())
        .select_from(AuditEvent)
        .where(AuditEvent.event_type == AuditEventType.USER_PROVISIONED)
    )
    assert provisioned == 1

    event = (await db_session.scalars(select(AuditEvent))).one()
    assert event.actor_type == "user"
    assert event.occurred_at is not None


async def test_require_roles_refuses_a_role_the_user_does_not_hold(
    app: FastAPI, client: AsyncClient
) -> None:
    install_probe_router(app)
    token = build_token(
        sub="1d7c5e44-0000-4000-8000-0000000000d4",
        email="sales.user@agfze.ae",
        name="Aisha Rahman",
        realm_access={"roles": ["sales_user"]},
    )

    response = await client.get(PROBE_URL, headers=auth_header(token))
    assert response.status_code == 403
    assert_error_envelope(response.json(), "forbidden")


async def test_require_roles_admits_a_matching_role(app: FastAPI, client: AsyncClient) -> None:
    install_probe_router(app)
    subject_id = "4e0a9b63-0000-4000-8000-0000000000d5"
    token = build_token(
        sub=subject_id,
        email="admin.user@agfze.ae",
        name="Sofia Lindqvist",
        realm_access={"roles": ["admin", "offline_access"]},
    )

    response = await client.get(PROBE_URL, headers=auth_header(token))
    assert response.status_code == 200
    assert response.json() == {"subject_id": subject_id}

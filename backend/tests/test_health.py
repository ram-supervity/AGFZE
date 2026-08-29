"""Liveness stays independent of the database; readiness reports it without describing it."""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.core.config import settings
from app.db.session import get_session

# Anything that would identify the database itself: a readiness failure is a signal to the
# orchestrator, not a diagnostic channel for whoever is probing the endpoint.
LEAKY_SUBSTRINGS = (
    "postgres",
    "asyncpg",
    "sqlite",
    "aiosqlite",
    "psycopg",
    "5432",
    "://",
    "password",
    "traceback",
    "connect call failed",
)


async def test_liveness_never_opens_a_database_session(
    app: FastAPI, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    readiness_calls: list[str] = []

    async def _spy() -> bool:
        readiness_calls.append("called")
        return True

    monkeypatch.setattr("app.api.v1.health.check_database_ready", _spy)

    def _forbidden_session() -> None:
        raise AssertionError("liveness must not depend on a database session")

    app.dependency_overrides[get_session] = _forbidden_session

    for path in ("/health", f"{settings.API_V1_PREFIX}/health"):
        response = await client.get(path)
        assert response.status_code == 200
        payload = response.json()
        assert payload["success"] is True
        assert payload["data"] == {
            "status": "ok",
            "service": settings.PROJECT_NAME,
            "environment": "testing",
        }

    assert readiness_calls == []


async def test_readiness_succeeds_against_the_live_database(client: AsyncClient) -> None:
    response = await client.get("/health/ready")
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"] == {"status": "ready", "database": "ok"}


async def test_readiness_fails_generically_when_the_database_is_unreachable(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _unreachable() -> bool:
        return False

    monkeypatch.setattr("app.api.v1.health.check_database_ready", _unreachable)

    response = await client.get("/health/ready")
    assert response.status_code == 503
    payload = response.json()
    assert payload["success"] is False
    assert payload["message"]
    assert "service_unavailable" in json.dumps(payload)
    assert payload.get("data") in (None, {"status": "not_ready"})

    body = response.text.lower()
    for fragment in LEAKY_SUBSTRINGS:
        assert fragment not in body

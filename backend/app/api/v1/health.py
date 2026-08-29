"""Liveness and readiness probes.

Liveness answers whether the process is up, which is what an orchestrator restarts on, so it
never touches the database. Readiness owns the dependency check.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.db.session import check_database_ready
from app.schemas.common import ResponseEnvelope, error_response

router = APIRouter(prefix="/health", tags=["health"])

HealthEnvelope = ResponseEnvelope[dict[str, str]]


@router.get("", response_model=HealthEnvelope, summary="Liveness probe")
@router.get("/", response_model=HealthEnvelope, include_in_schema=False)
async def liveness() -> HealthEnvelope:
    return HealthEnvelope(
        data={"status": "ok", "service": settings.PROJECT_NAME, "environment": settings.ENV}
    )


@router.get("/ready", response_model=HealthEnvelope, summary="Readiness probe")
async def readiness() -> HealthEnvelope | JSONResponse:
    if not await check_database_ready():
        # The body stays generic on purpose: no driver, DSN, host or port reaches the client.
        body = error_response("service_unavailable", "Service is not ready.")
        body["data"] = {"status": "not_ready"}
        return JSONResponse(status_code=503, content=body)
    return HealthEnvelope(data={"status": "ready", "database": "ok"})

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.internal import files
from app.api.v1 import api_router, health
from app.core.config import settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.observability import init_error_tracking
from app.core.rate_limit import install_rate_limiting
from app.db.session import dispose_engine
from app.middleware.request_logging import RequestLoggingMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.services import (
    graph_sync_worker,
    integration_worker,
    mailbox_worker,
    shipment_worker,
)
from app.services.graph_service import close_graph_client
from app.services.keycloak_admin import close_keycloak_admin_client

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    error_tracking = init_error_tracking()
    logger.info(
        "application_startup",
        extra={"environment": settings.ENV, "error_tracking": error_tracking},
    )

    # The mailbox poller and its subscription keeper only start where they can do real work:
    # real credentials, polling enabled, and never inside the test harness.
    stop = asyncio.Event()
    workers: list[asyncio.Task] = []
    if mailbox_worker.should_run():
        workers.append(asyncio.create_task(mailbox_worker.run_worker(stop)))
    else:
        logger.info(
            "mailbox_worker_not_started",
            extra={"graph_configured": settings.graph_configured},
        )

    # The shipment sweep, on its own timer. Unlike the mailbox it needs no external credential to
    # be useful: with no carrier adapter registered it still ages a shipment nobody has looked at
    # into the exception queue, which is the half of its job that matters most today.
    if shipment_worker.should_run():
        workers.append(asyncio.create_task(shipment_worker.run_worker(stop)))
    else:
        logger.info("shipment_worker_not_started")

    # The integration retry sweep, and the first genuinely periodic job in this build that has
    # something real to drive: an attempt that failed transiently has a next attempt due at a
    # calculable moment, and something has to be awake to make it. It never touches a job that is
    # waiting on a person.
    if graph_sync_worker.should_run():
        workers.append(asyncio.create_task(graph_sync_worker.run_worker(stop)))
    else:
        # Off on every deployment today. The projection is derived and optional, and nothing on
        # the platform reads it, so its absence changes no behaviour anywhere.
        logger.info("graph_sync_worker_not_started")

    if integration_worker.should_run():
        workers.append(asyncio.create_task(integration_worker.run_worker(stop)))
    else:
        logger.info("integration_worker_not_started")

    try:
        yield
    finally:
        stop.set()
        for worker in workers:
            with suppress(asyncio.CancelledError, asyncio.TimeoutError):
                await asyncio.wait_for(worker, timeout=10)
        await close_graph_client()
        await close_keycloak_admin_client()
        await dispose_engine()
        logger.info("application_shutdown", extra={"environment": settings.ENV})


def create_app() -> FastAPI:
    docs_enabled = not settings.is_production
    app = FastAPI(
        title=settings.PROJECT_NAME,
        lifespan=lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )

    # Starlette inserts each middleware in front of the previous one, so registering in reverse
    # yields the intended order: CORS, then security headers, then request logging, then rate
    # limiting. The headers are applied outside the rate limiter deliberately, so a 429 carries
    # them too - a refusal is a response like any other and must not be the one that arrives
    # unhardened.
    install_rate_limiting(app)
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )

    register_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(files.router)
    app.include_router(api_router, prefix=settings.API_V1_PREFIX)
    return app


app = create_app()

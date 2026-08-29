from __future__ import annotations

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def init_error_tracking() -> bool:
    """Wire Sentry when a DSN is configured. Never raises: telemetry must not block startup."""
    if not settings.SENTRY_DSN:
        return False
    try:
        import sentry_sdk
    except ImportError:
        logger.warning("error_tracking_unavailable", extra={"reason": "sentry_sdk_not_installed"})
        return False
    try:
        sentry_sdk.init(
            dsn=settings.SENTRY_DSN,
            environment=settings.ENV,
            traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
            send_default_pii=False,
        )
    except Exception:
        logger.exception("error_tracking_init_failed")
        return False
    logger.info("error_tracking_enabled", extra={"environment": settings.ENV})
    return True

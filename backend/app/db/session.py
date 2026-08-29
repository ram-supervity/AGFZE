from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_pool_options: dict[str, object] = {}
# SQLite (the container-less test fallback) is driven through NullPool, which rejects sizing kwargs.
if make_url(settings.DATABASE_URL).get_backend_name() != "sqlite":
    _pool_options = {
        "pool_size": settings.DATABASE_POOL_SIZE,
        "max_overflow": settings.DATABASE_MAX_OVERFLOW,
        "pool_pre_ping": True,
    }

engine = create_async_engine(settings.DATABASE_URL, echo=settings.DATABASE_ECHO, **_pool_options)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    session = AsyncSessionLocal()
    try:
        yield session
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def dispose_engine() -> None:
    await engine.dispose()


async def check_database_ready() -> bool:
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception:
        # Driver detail stays server-side; the readiness endpoint answers with a generic body.
        logger.exception("database_readiness_check_failed")
        return False
    return True

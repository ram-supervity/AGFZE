from __future__ import annotations

from functools import lru_cache

from app.core.config import settings
from app.services.storage.base import StorageError, StorageService
from app.services.storage.cloud import GoogleCloudStorage
from app.services.storage.local import LocalFileSystemStorage

BACKENDS: tuple[str, ...] = ("local", "gcs")


def build_storage_service() -> StorageService:
    """Construct the configured backend. Separate from the cached accessor on purpose.

    The test suite replaces `get_storage_service` wholesale so every test writes to its own
    temporary directory, which leaves the cached accessor with no cache to clear and no selection
    logic behind it. Keeping the selection here means it stays directly testable regardless of what
    the accessor has been swapped for.
    """
    backend = settings.STORAGE_BACKEND.strip().lower()
    if backend == "local":
        return LocalFileSystemStorage(
            settings.STORAGE_LOCAL_ROOT,
            signing_secret=settings.STORAGE_SIGNED_URL_SECRET,
            base_url=settings.STORAGE_PUBLIC_BASE_URL,
            default_ttl_seconds=settings.STORAGE_SIGNED_URL_TTL_SECONDS,
        )
    if backend == "gcs":
        return GoogleCloudStorage(
            settings.STORAGE_BUCKET,
            default_ttl_seconds=settings.STORAGE_SIGNED_URL_TTL_SECONDS,
        )
    raise StorageError(
        f"Unsupported storage backend: {settings.STORAGE_BACKEND}. "
        f"Choose one of: {', '.join(BACKENDS)}."
    )


@lru_cache
def get_storage_service() -> StorageService:
    return build_storage_service()

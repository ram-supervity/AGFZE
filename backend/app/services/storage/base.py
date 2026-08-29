from __future__ import annotations

from abc import ABC, abstractmethod


class StorageError(Exception):
    """A storage backend rejected the request or could not complete it."""


class ObjectNotFoundError(StorageError):
    """No object is stored under the requested key."""


class StorageService(ABC):
    @abstractmethod
    async def upload(self, key: str, data: bytes, content_type: str | None = None) -> str:
        """Store ``data`` under ``key`` and return the stored key."""

    @abstractmethod
    async def download(self, key: str) -> bytes:
        """Return the stored bytes, raising :class:`ObjectNotFoundError` when the key is unused."""

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Remove the object. Deleting an absent key is not an error."""

    @abstractmethod
    async def get_signed_url(self, key: str, expires_in: int | None = None) -> str:
        """Return a time-limited URL for the object, using the backend default TTL when
        ``expires_in`` is None."""

    async def resolve_signed_request(self, key: str, expires: int, signature: str) -> bytes:
        """Verify a signature and expiry issued by :meth:`get_signed_url` and return the bytes.

        Only backends that serve their own signed URLs in-process implement this. An object store
        that issues its own pre-signed links redirects instead and never reaches here.
        """
        raise StorageError("This storage backend does not serve signed downloads in-process.")

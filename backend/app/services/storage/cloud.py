"""The object-store backend, for a deployment that has a bucket rather than a disk.

Fills in the second `StorageService` implementation behind the unchanged protocol. Nothing about
the interface moved to accommodate it: every caller still asks for bytes by key and a signed URL by
key, and cannot tell which backend answered.

**Google Cloud Storage rather than Azure Blob, and this is a deliberate departure worth naming.**
The PRD specifies Azure Blob Storage. Every piece of infrastructure this platform actually has is
GCP - the Terraform stack provisions Cloud Run, Cloud SQL, Secret Manager, KMS and a
`google_storage_bucket` for documents, and the backend's service account already holds an IAM
binding on that bucket. Writing an Azure client would produce a backend with no bucket to talk to,
while the bucket that does exist stayed behind a filesystem mount. So this is written against the
store that is there, and the discrepancy is recorded in docs/KNOWN-GAPS.md rather than resolved
silently in either direction. If AGFZE confirms Azure is a hard requirement, this module is the
template for that one and the factory already has the seam for it.

**Why it is worth having at all**, given a mounted bucket already works: a mount is not a client.
Writes go through the kernel's page cache and the mount's own consistency model rather than the
object store's, they are slower under the burst of page images a large scanned pack produces, and a
signed URL cannot be issued at all - the mount has no notion of one, so every download is proxied
through the API process. This backend issues the store's own pre-signed URLs, so a browser fetches
bytes directly from the bucket and the API never carries them.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from app.core.logging import get_logger
from app.services.storage.base import ObjectNotFoundError, StorageError, StorageService

logger = get_logger(__name__)


class GoogleCloudStorage(StorageService):
    """Objects in a GCS bucket, addressed by the same keys the local backend uses.

    The client is constructed lazily and once. Building it at import time would make every test
    run and every `--help` invocation try to resolve application-default credentials, and a
    deployment using the local backend has no reason to hold a cloud client at all.

    Every call is wrapped in `asyncio.to_thread` because `google-cloud-storage` is a synchronous
    library. That is the same thing `LocalFileSystemStorage` does with its blocking file I/O, for
    the same reason: an await that quietly blocks the loop is worse than an explicit thread hop.
    """

    def __init__(
        self,
        bucket_name: str,
        *,
        default_ttl_seconds: int = 900,
        client: Any | None = None,
    ) -> None:
        if not bucket_name.strip():
            raise StorageError("A bucket name is required for the cloud storage backend.")
        self._bucket_name = bucket_name.strip()
        self._default_ttl_seconds = default_ttl_seconds
        self._client = client

    def _bucket(self) -> Any:
        if self._client is None:
            try:
                from google.cloud import storage
            except ImportError as exc:  # pragma: no cover - depends on the install profile
                raise StorageError(
                    "The cloud storage backend needs google-cloud-storage installed. Either "
                    "install it or set STORAGE_BACKEND=local."
                ) from exc
            # Credentials come from the runtime's own identity - workload identity on Cloud Run -
            # and never from anything this application holds. There is no key file to leak because
            # there is no key file.
            self._client = storage.Client()
        return self._client.bucket(self._bucket_name)

    def _blob(self, key: str) -> Any:
        return self._bucket().blob(key)

    async def upload(self, key: str, data: bytes, content_type: str | None = None) -> str:
        def _write() -> None:
            blob = self._blob(key)
            blob.upload_from_string(data, content_type=content_type or "application/octet-stream")

        try:
            await asyncio.to_thread(_write)
        except Exception as exc:
            # The provider's own message never reaches a caller: it can carry a bucket name, a
            # project id and a signed URL fragment, and this exception is rendered into an API
            # response. The detail goes to the log instead.
            logger.exception("storage.upload_failed", extra={"key": key})
            raise StorageError("The document could not be stored.") from exc
        return key

    async def download(self, key: str) -> bytes:
        def _read() -> bytes:
            blob = self._blob(key)
            if not blob.exists():
                raise ObjectNotFoundError(key)
            return blob.download_as_bytes()

        try:
            return await asyncio.to_thread(_read)
        except ObjectNotFoundError:
            raise
        except Exception as exc:
            logger.exception("storage.download_failed", extra={"key": key})
            raise StorageError("The document could not be read.") from exc

    async def delete(self, key: str) -> None:
        def _remove() -> None:
            blob = self._blob(key)
            # Deleting an absent key is not an error, matching the local backend's `missing_ok`.
            # A caller cleaning up after a failure should not have to know whether it got as far
            # as writing anything.
            try:
                blob.delete()
            except Exception as exc:
                if _is_not_found(exc):
                    return
                raise

        try:
            await asyncio.to_thread(_remove)
        except Exception as exc:
            logger.exception("storage.delete_failed", extra={"key": key})
            raise StorageError("The document could not be removed.") from exc

    async def get_signed_url(self, key: str, expires_in: int | None = None) -> str:
        """A pre-signed URL the bucket itself honours, so bytes never pass through this process.

        The local backend signs a URL back to this application because a directory cannot serve
        one. An object store can, which is most of the point of using it.
        """
        ttl = expires_in if expires_in is not None else self._default_ttl_seconds

        def _sign() -> str:
            return self._blob(key).generate_signed_url(
                version="v4",
                expiration=timedelta(seconds=ttl),
                method="GET",
            )

        try:
            return await asyncio.to_thread(_sign)
        except Exception as exc:
            logger.exception("storage.sign_failed", extra={"key": key})
            raise StorageError("A download link could not be issued for this document.") from exc


def _is_not_found(exc: Exception) -> bool:
    """Whether a client error means "no such object" rather than a real failure.

    Matched on the HTTP status the client attaches rather than on the exception class, so this
    does not import `google.api_core` just to name one exception - which would make the module
    unimportable on a deployment that installed neither.
    """
    return getattr(exc, "code", None) == 404 or getattr(exc, "status_code", None) == 404

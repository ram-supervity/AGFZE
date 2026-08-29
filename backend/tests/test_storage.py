"""Local storage round-trips, signed URL validation and path containment."""

from __future__ import annotations

import time
from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from app.services.storage.base import ObjectNotFoundError, StorageError
from app.services.storage.local import LocalFileSystemStorage

KEY = "transactions/2026/ingest-batch.bin"
# Every byte value, so a driver that decodes or normalises the payload cannot pass.
PAYLOAD = bytes(range(256)) * 16
BASE_URL = "http://testserver/internal/files"


@pytest.fixture
def storage(tmp_path: Path) -> LocalFileSystemStorage:
    return LocalFileSystemStorage(
        str(tmp_path),
        signing_secret="storage-test-signing-secret",
        base_url=BASE_URL,
        default_ttl_seconds=900,
    )


async def test_upload_and_download_round_trip_is_byte_exact(
    storage: LocalFileSystemStorage,
) -> None:
    assert await storage.upload(KEY, PAYLOAD, "application/octet-stream") == KEY
    assert await storage.download(KEY) == PAYLOAD


async def test_a_signed_url_resolves_to_the_stored_bytes(
    storage: LocalFileSystemStorage,
) -> None:
    await storage.upload(KEY, PAYLOAD)

    url = await storage.get_signed_url(KEY)
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert parsed.path.endswith(KEY)
    assert int(query["expires"][0]) > time.time()
    assert query["signature"][0]

    assert await storage.resolve_signed_url(url) == PAYLOAD


async def test_a_tampered_signature_is_refused(storage: LocalFileSystemStorage) -> None:
    await storage.upload(KEY, PAYLOAD)
    url = await storage.get_signed_url(KEY)
    tampered = url[:-1] + ("a" if url[-1] != "a" else "b")

    with pytest.raises(StorageError):
        await storage.resolve_signed_url(tampered)


async def test_an_expired_url_is_refused(storage: LocalFileSystemStorage) -> None:
    await storage.upload(KEY, PAYLOAD)
    url = await storage.get_signed_url(KEY, expires_in=-5)
    assert int(parse_qs(urlparse(url).query)["expires"][0]) < time.time()

    with pytest.raises(StorageError):
        await storage.resolve_signed_url(url)


@pytest.mark.parametrize("key", ["../etc/passwd", "/etc/passwd", "nested/../../escape.txt"])
async def test_keys_outside_the_root_are_refused(storage: LocalFileSystemStorage, key: str) -> None:
    with pytest.raises(StorageError):
        await storage.upload(key, PAYLOAD)
    with pytest.raises(StorageError):
        await storage.download(key)


async def test_downloading_an_object_that_was_never_written_raises(
    storage: LocalFileSystemStorage,
) -> None:
    with pytest.raises(ObjectNotFoundError):
        await storage.download("reports/never-written.json")


async def test_delete_removes_the_object_and_is_idempotent(
    storage: LocalFileSystemStorage,
) -> None:
    await storage.upload(KEY, PAYLOAD)
    await storage.delete(KEY)

    with pytest.raises(ObjectNotFoundError):
        await storage.download(KEY)

    await storage.delete(KEY)
    await storage.delete("reports/never-written.json")


# --- the object-store backend -------------------------------------------------------------------
#
# Exercised against a fake client rather than a real bucket. The fake implements the three methods
# this backend actually calls, so a test still fails if the backend calls something else or reads
# the result wrongly - which is the part worth testing. A real bucket in CI would test Google's
# client library, cost money, and fail on a machine with no credentials.


class _FakeBlob:
    def __init__(self, store: dict[str, tuple[bytes, str | None]], key: str) -> None:
        self._store = store
        self._key = key
        self.signed_with: dict[str, object] | None = None

    def upload_from_string(self, data: bytes, content_type: str | None = None) -> None:
        self._store[self._key] = (data, content_type)

    def exists(self) -> bool:
        return self._key in self._store

    def download_as_bytes(self) -> bytes:
        return self._store[self._key][0]

    def delete(self) -> None:
        if self._key not in self._store:
            raise _FakeNotFound()
        del self._store[self._key]

    def generate_signed_url(self, **kwargs: object) -> str:
        self.signed_with = dict(kwargs)
        return f"https://storage.test/{self._key}?signed=1"


class _FakeNotFound(Exception):
    code = 404


class _FakeBucket:
    def __init__(self, store: dict[str, tuple[bytes, str | None]]) -> None:
        self._store = store
        self.blobs: dict[str, _FakeBlob] = {}

    def blob(self, key: str) -> _FakeBlob:
        # One blob object per key, so a test can read back what a signed-URL call was given.
        return self.blobs.setdefault(key, _FakeBlob(self._store, key))


class _FakeClient:
    def __init__(self) -> None:
        self.store: dict[str, tuple[bytes, str | None]] = {}
        self._bucket = _FakeBucket(self.store)
        self.requested_buckets: list[str] = []

    def bucket(self, name: str) -> _FakeBucket:
        self.requested_buckets.append(name)
        return self._bucket


@pytest.fixture
def fake_client() -> _FakeClient:
    return _FakeClient()


@pytest.fixture
def cloud(fake_client: _FakeClient):
    from app.services.storage.cloud import GoogleCloudStorage

    return GoogleCloudStorage("agfze-documents", default_ttl_seconds=900, client=fake_client)


async def test_cloud_upload_and_download_round_trip_is_byte_exact(cloud) -> None:
    payload = b"%PDF-1.7 not really a pdf, but exactly these bytes"
    key = await cloud.upload("documents/source/abc.pdf", payload, "application/pdf")

    assert key == "documents/source/abc.pdf"
    assert await cloud.download(key) == payload


async def test_cloud_upload_records_the_content_type_it_was_given(
    cloud, fake_client: _FakeClient
) -> None:
    await cloud.upload("documents/source/a.pdf", b"x", "application/pdf")
    assert fake_client.store["documents/source/a.pdf"][1] == "application/pdf"

    # An upload with no stated type gets a real default rather than None, because a bucket serving
    # an object with no content type hands the browser something it will not display.
    await cloud.upload("documents/source/b.bin", b"x")
    assert fake_client.store["documents/source/b.bin"][1] == "application/octet-stream"


async def test_cloud_download_of_an_absent_key_raises_not_found(cloud) -> None:
    """The same exception the local backend raises, so callers need no branch on backend."""
    with pytest.raises(ObjectNotFoundError):
        await cloud.download("documents/source/never-written.pdf")


async def test_cloud_delete_removes_the_object_and_is_idempotent(cloud) -> None:
    await cloud.upload("documents/source/gone.pdf", b"x")
    await cloud.delete("documents/source/gone.pdf")

    with pytest.raises(ObjectNotFoundError):
        await cloud.download("documents/source/gone.pdf")

    # Deleting what is already gone is not an error, matching the local backend's `missing_ok`.
    await cloud.delete("documents/source/gone.pdf")


async def test_cloud_issues_the_buckets_own_signed_url_rather_than_proxying(
    cloud, fake_client: _FakeClient
) -> None:
    """Most of the point of using an object store: the bytes never pass through this process."""
    await cloud.upload("documents/source/link.pdf", b"x")
    url = await cloud.get_signed_url("documents/source/link.pdf")

    assert url.startswith("https://storage.test/")
    blob = fake_client._bucket.blobs["documents/source/link.pdf"]
    assert blob.signed_with is not None
    assert blob.signed_with["version"] == "v4"
    assert blob.signed_with["method"] == "GET"
    assert blob.signed_with["expiration"] == timedelta(seconds=900)


async def test_cloud_honours_an_explicit_expiry_over_its_default(
    cloud, fake_client: _FakeClient
) -> None:
    await cloud.upload("documents/source/short.pdf", b"x")
    await cloud.get_signed_url("documents/source/short.pdf", expires_in=60)

    blob = fake_client._bucket.blobs["documents/source/short.pdf"]
    assert blob.signed_with["expiration"] == timedelta(seconds=60)


async def test_cloud_never_leaks_the_providers_own_message_to_a_caller(cloud) -> None:
    """A provider error can carry a bucket name, a project id and a URL fragment.

    This exception is rendered into an API response, so what it says matters. The detail belongs in
    the log, which is where the backend puts it.
    """

    def _explode(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("gs://agfze-documents/secret-path?X-Goog-Signature=deadbeef")

    blob = cloud._blob("documents/source/boom.pdf")
    blob.upload_from_string = _explode

    with pytest.raises(StorageError) as raised:
        await cloud.upload("documents/source/boom.pdf", b"x", "application/pdf")

    assert "agfze-documents" not in str(raised.value)
    assert "X-Goog-Signature" not in str(raised.value)


def test_a_bucketless_cloud_backend_is_refused_at_construction() -> None:
    """A backend with no bucket cannot store anything; failing later is the wrong end of it."""
    from app.services.storage.cloud import GoogleCloudStorage

    with pytest.raises(StorageError):
        GoogleCloudStorage("   ")


def test_the_factory_offers_exactly_the_backends_that_exist() -> None:
    from app.services.storage.factory import BACKENDS

    assert BACKENDS == ("local", "gcs")


def test_an_unknown_backend_name_is_refused_rather_than_defaulted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Silently falling back to local would put production documents on a container's disk."""
    from app.services.storage import factory

    monkeypatch.setattr(factory.settings, "STORAGE_BACKEND", "azure-blob")
    with pytest.raises(StorageError):
        factory.build_storage_service()


def test_the_factory_builds_each_backend_it_offers(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.storage import factory
    from app.services.storage.cloud import GoogleCloudStorage

    monkeypatch.setattr(factory.settings, "STORAGE_BACKEND", "local")
    assert isinstance(factory.build_storage_service(), LocalFileSystemStorage)

    monkeypatch.setattr(factory.settings, "STORAGE_BACKEND", "gcs")
    monkeypatch.setattr(factory.settings, "STORAGE_BUCKET", "agfze-documents")
    # Constructed without ever reaching Google: the client is built lazily, on first use.
    assert isinstance(factory.build_storage_service(), GoogleCloudStorage)

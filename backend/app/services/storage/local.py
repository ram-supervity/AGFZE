from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import tempfile
import time
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, quote, unquote, urlparse

from app.services.storage.base import ObjectNotFoundError, StorageError, StorageService


class LocalFileSystemStorage(StorageService):
    def __init__(
        self,
        root: str | Path,
        *,
        signing_secret: str,
        base_url: str,
        default_ttl_seconds: int,
    ) -> None:
        self._root = Path(root).expanduser().resolve()
        self._secret = signing_secret.encode("utf-8")
        self._base_url = base_url.rstrip("/")
        self._default_ttl_seconds = default_ttl_seconds

    async def upload(self, key: str, data: bytes, content_type: str | None = None) -> str:
        """``content_type`` is accepted for parity with object-store backends; a filesystem has
        nowhere to record it."""
        path = self._resolve(key)
        await asyncio.to_thread(self._write_atomic, path, data)
        return key

    async def download(self, key: str) -> bytes:
        path = self._resolve(key)
        try:
            return await asyncio.to_thread(path.read_bytes)
        except (FileNotFoundError, IsADirectoryError, NotADirectoryError) as exc:
            raise ObjectNotFoundError(f"No object stored under key: {key}") from exc

    async def delete(self, key: str) -> None:
        path = self._resolve(key)
        await asyncio.to_thread(path.unlink, missing_ok=True)

    async def get_signed_url(self, key: str, expires_in: int | None = None) -> str:
        self._resolve(key)
        ttl = self._default_ttl_seconds if expires_in is None else expires_in
        expires = int(time.time()) + ttl
        signature = self._sign(key, expires)
        return f"{self._base_url}/{quote(key)}?expires={expires}&signature={signature}"

    async def resolve_signed_request(self, key: str, expires: int, signature: str) -> bytes:
        """Verification behind the authenticated file route added in .

        Constant-time signature comparison first, then expiry, then the read. A key that was
        never signed for cannot be reached by guessing the path.
        """
        if not hmac.compare_digest(signature, self._sign(key, expires)):
            raise StorageError("Signed URL signature does not match.")
        if expires <= int(time.time()):
            raise StorageError("Signed URL has expired.")
        return await self.download(key)

    async def resolve_signed_url(self, url: str) -> bytes:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        try:
            expires = int(params["expires"][0])
            signature = params["signature"][0]
        except (KeyError, IndexError, ValueError) as exc:
            raise StorageError("Signed URL is missing a valid expiry or signature.") from exc
        key = self._key_from_path(parsed.path)
        return await self.resolve_signed_request(key, expires, signature)

    def _resolve(self, key: str) -> Path:
        if not key or key.startswith("/") or "\\" in key:
            raise StorageError("Object key must be a relative POSIX path.")
        parts = PurePosixPath(key).parts
        if not parts or ".." in parts:
            raise StorageError("Object key must not contain traversal segments.")
        # Re-check after resolution so a symlink inside the root cannot point outside it.
        path = self._root.joinpath(*parts).resolve()
        if not path.is_relative_to(self._root):
            raise StorageError("Object key escapes the storage root.")
        return path

    def _sign(self, key: str, expires: int) -> str:
        payload = f"{key}:{expires}".encode()
        return hmac.new(self._secret, payload, hashlib.sha256).hexdigest()

    def _key_from_path(self, path: str) -> str:
        prefix = urlparse(self._base_url).path.rstrip("/")
        decoded = unquote(path)
        if prefix and decoded.startswith(f"{prefix}/"):
            decoded = decoded[len(prefix) + 1 :]
        return decoded.lstrip("/")

    @staticmethod
    def _write_atomic(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".upload-", suffix=".part")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, path)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise

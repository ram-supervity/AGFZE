"""Server-side file admission.

Nothing here trusts a filename extension or a client-supplied content type. The whitelist is
decided by libmagic reading the actual leading bytes, and the size limit is applied while the
body is still streaming so an oversized upload is refused before it is ever fully buffered.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from typing import BinaryIO, Protocol

import magic

from app.core.config import settings
from app.core.errors import AppError


class FileTooLargeError(AppError):
    status_code = 413
    code = "file_too_large"
    message = "The file exceeds the 25 MB limit."


class UnsupportedFileTypeError(AppError):
    status_code = 415
    code = "unsupported_file_type"
    message = "That file type is not accepted."


class EmptyFileError(AppError):
    status_code = 400
    code = "empty_file"
    message = "The file is empty."


# Pipeline families the extraction router branches on.
PDF = "pdf"
DOCX = "docx"
SPREADSHEET = "spreadsheet"
IMAGE = "image"

# Detected MIME -> (canonical content type, pipeline family). Only these are admitted.
ALLOWED_TYPES: dict[str, tuple[str, str]] = {
    "application/pdf": ("application/pdf", PDF),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        DOCX,
    ),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        SPREADSHEET,
    ),
    "application/vnd.ms-excel": ("application/vnd.ms-excel", SPREADSHEET),
    "text/csv": ("text/csv", SPREADSHEET),
    "text/plain": ("text/csv", SPREADSHEET),
    "application/csv": ("text/csv", SPREADSHEET),
    "image/jpeg": ("image/jpeg", IMAGE),
    "image/png": ("image/png", IMAGE),
}

# libmagic reports both OOXML containers as generic zip archives on some builds, and as an opaque
# byte stream on others - which build a machine has is not something this platform can depend on.
# The extension is then the only remaining discriminator, so it is used to choose *between two
# already-admitted container types* and never to admit a file the magic bytes rejected: a file
# only reaches that branch once its own leading bytes have been confirmed to be a zip container,
# either by libmagic or by the local-file signature below.
ZIP_CONTAINER_TYPES = frozenset(
    {"application/zip", "application/x-zip-compressed", "application/octet-stream"}
)

# The four-byte local file header every zip archive - and so every OOXML document - begins with.
# This is the check that keeps `application/octet-stream` above from becoming a way in for
# anything at all: an octet-stream that is not actually a zip is refused exactly as it was before.
ZIP_LOCAL_FILE_SIGNATURE = b"PK\x03\x04"
ZIP_EXTENSION_TYPES = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

ACCEPTED_EXTENSIONS = (".pdf", ".docx", ".xlsx", ".xls", ".csv", ".jpg", ".jpeg", ".png")


@dataclass(frozen=True)
class InspectedFile:
    filename: str
    content_type: str
    family: str
    data: bytes
    content_hash: str

    @property
    def byte_size(self) -> int:
        return len(self.data)


class AsyncChunkReader(Protocol):
    async def read(self, size: int = -1) -> bytes: ...


def _extension(filename: str) -> str:
    _, _, tail = filename.rpartition(".")
    return f".{tail.lower()}" if tail and tail != filename else ""


def detect_type(data: bytes, filename: str) -> tuple[str, str]:
    """Resolve (content type, pipeline family) from the leading bytes, or refuse the file."""
    if not data:
        raise EmptyFileError()

    detected = magic.from_buffer(data[:8192], mime=True) or ""
    detected = detected.strip().lower()

    if detected in ZIP_CONTAINER_TYPES and data.startswith(ZIP_LOCAL_FILE_SIGNATURE):
        resolved = ZIP_EXTENSION_TYPES.get(_extension(filename))
        if resolved is None:
            raise UnsupportedFileTypeError(
                "The file is a zip archive that is neither a Word nor an Excel document."
            )
        detected = resolved

    allowed = ALLOWED_TYPES.get(detected)
    if allowed is None:
        raise UnsupportedFileTypeError(
            "Only PDF, Word, Excel, CSV, JPEG and PNG files are accepted."
        )

    # A .csv or .xls whose bytes are plain text is legitimate; a .pdf whose bytes are plain text
    # is a spoofed extension and is refused here rather than confusing the extraction router.
    content_type, family = allowed
    if family == SPREADSHEET and content_type == "text/csv":
        extension = _extension(filename)
        if extension not in (".csv", ".txt", ""):
            raise UnsupportedFileTypeError(
                "The file's contents do not match the type its name claims."
            )
    return content_type, family


def inspect_bytes(filename: str, data: bytes) -> InspectedFile:
    if len(data) > settings.MAX_UPLOAD_BYTES:
        raise FileTooLargeError()
    content_type, family = detect_type(data, filename)
    return InspectedFile(
        filename=sanitise_filename(filename),
        content_type=content_type,
        family=family,
        data=data,
        content_hash=hashlib.sha256(data).hexdigest(),
    )


async def read_within_limit(
    stream: AsyncChunkReader,
    *,
    limit: int | None = None,
    chunk_size: int | None = None,
) -> bytes:
    """Buffer an upload chunk by chunk, aborting the moment the limit is passed.

    The check runs on the running total during the read, never on a fully materialised body.
    """
    maximum = settings.MAX_UPLOAD_BYTES if limit is None else limit
    size = settings.UPLOAD_CHUNK_BYTES if chunk_size is None else chunk_size
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await stream.read(size)
        if not chunk:
            break
        total += len(chunk)
        if total > maximum:
            raise FileTooLargeError()
        chunks.append(chunk)
    return b"".join(chunks)


def read_sync_within_limit(stream: BinaryIO, *, limit: int | None = None) -> bytes:
    maximum = settings.MAX_UPLOAD_BYTES if limit is None else limit
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = stream.read(settings.UPLOAD_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > maximum:
            raise FileTooLargeError()
        chunks.append(chunk)
    return b"".join(chunks)


def sanitise_filename(filename: str) -> str:
    """Keep a display name only. It never takes part in a storage path or a type decision."""
    name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    name = "".join(character for character in name if character.isprintable())
    return (name or "attachment")[:255]


def storage_key(prefix: str, filename: str) -> str:
    """An opaque, UUID-derived key. The original name is never part of the path."""
    extension = _extension(filename)
    suffix = extension if extension in ACCEPTED_EXTENSIONS else ""
    return f"{prefix}/{uuid.uuid4().hex}{suffix}"

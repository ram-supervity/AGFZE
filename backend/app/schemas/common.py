from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel

DataT = TypeVar("DataT")


class ErrorDetail(BaseModel):
    code: str
    message: str
    field: str | None = None


class ResponseEnvelope(BaseModel, Generic[DataT]):
    success: bool = True
    data: DataT | None = None
    message: str | None = None
    errors: list[ErrorDetail] | None = None


def success_response(data: Any, message: str | None = None) -> dict[str, Any]:
    return ResponseEnvelope[Any](data=data, message=message).model_dump(mode="json")


def error_response(
    code: str,
    message: str,
    errors: list[ErrorDetail] | None = None,
) -> dict[str, Any]:
    # The envelope has no top-level code field, so a caller-supplied code is carried as the
    # single ErrorDetail when no per-field detail was collected.
    details = errors if errors else [ErrorDetail(code=code, message=message)]
    return ResponseEnvelope[Any](
        success=False,
        data=None,
        message=message,
        errors=details,
    ).model_dump(mode="json")

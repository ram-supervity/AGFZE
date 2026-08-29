from __future__ import annotations

from typing import Any, ClassVar

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.logging import get_logger

logger = get_logger(__name__)

_HTTP_ERROR_CODES = {
    400: "bad_request",
    401: "unauthenticated",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    415: "unsupported_media_type",
    422: "validation_error",
    429: "rate_limited",
    503: "service_unavailable",
}


class AppError(Exception):
    status_code: int = 500
    code: str = "internal_error"
    message: str = "An unexpected error occurred."
    headers: dict[str, str] | None = None

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        errors: list[dict[str, Any]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        cls = type(self)
        self.message = message or cls.message
        self.code = code or cls.code
        self.errors = errors
        self.headers = headers or cls.headers
        super().__init__(self.message)


class AuthenticationError(AppError):
    status_code = 401
    code = "unauthenticated"
    message = "Authentication is required."
    headers: ClassVar[dict[str, str]] = {"WWW-Authenticate": "Bearer"}


class AuthorizationError(AppError):
    status_code = 403
    code = "forbidden"
    message = "You do not have access to this resource."


class AccountDisabledError(AppError):
    status_code = 403
    code = "account_disabled"
    message = "This account is disabled. Contact your administrator."


class BadRequestError(AppError):
    status_code = 400
    code = "bad_request"
    message = "The request could not be processed as submitted."


class UnprocessableError(AppError):
    status_code = 422
    code = "validation_error"
    message = "The submitted value failed validation."


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"
    message = "The requested resource was not found."


class ConflictError(AppError):
    status_code = 409
    code = "conflict"
    message = "The request conflicts with the current state of the resource."


class ServiceUnavailableError(AppError):
    status_code = 503
    code = "service_unavailable"
    message = "The service is temporarily unavailable."


def _envelope(
    code: str, message: str, errors: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    # Same shape as app.schemas.common.error_response, built by hand: importing the schema layer
    # here would make the error handlers part of an import cycle.
    details = errors or [{"code": code, "message": message, "field": None}]
    return {"success": False, "data": None, "message": message, "errors": details}


def _json_error(
    request: Request,
    status_code: int,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    response_headers = dict(headers or {})
    request_id = getattr(request.state, "request_id", None)
    if request_id:
        response_headers["X-Request-ID"] = request_id
    return JSONResponse(status_code=status_code, content=payload, headers=response_headers or None)


async def _handle_app_error(request: Request, exc: AppError) -> JSONResponse:
    return _json_error(
        request, exc.status_code, _envelope(exc.code, exc.message, exc.errors), exc.headers
    )


async def _handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    details = [
        {
            "code": str(error.get("type", "invalid")),
            "message": str(error.get("msg", "Invalid value.")),
            "field": ".".join(str(part) for part in tuple(error.get("loc", ()))[1:]) or None,
        }
        for error in exc.errors()
    ]
    payload = _envelope("validation_error", "The request payload failed validation.", details)
    return _json_error(request, 422, payload)


async def _handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = _HTTP_ERROR_CODES.get(exc.status_code, "http_error")
    message = (
        exc.detail
        if isinstance(exc.detail, str) and exc.detail
        else "The request could not be completed."
    )
    return _json_error(
        request, exc.status_code, _envelope(code, message), getattr(exc, "headers", None)
    )


async def _handle_database_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    logger.exception(
        "database_error",
        extra={"method": request.method, "path": request.url.path},
    )
    return _json_error(request, 500, _envelope(AppError.code, AppError.message))


async def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        "unhandled_error",
        extra={"method": request.method, "path": request.url.path},
    )
    return _json_error(request, 500, _envelope(AppError.code, AppError.message))


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _handle_app_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(SQLAlchemyError, _handle_database_error)
    app.add_exception_handler(Exception, _handle_unexpected_error)

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Any

from werkzeug.exceptions import (
    BadGateway,
    BadRequest,
    Forbidden,
    GatewayTimeout,
    Gone,
    HTTPException,
    InternalServerError,
    Locked,
    MethodNotAllowed,
    NotFound,
    RequestEntityTooLarge,
    ServiceUnavailable,
    TooManyRequests,
    Unauthorized,
    UnprocessableEntity,
    UnsupportedMediaType,
    abort,
)

if TYPE_CHECKING:
    from .wrappers import Response

    type ErrorResponse = Response | HTTPException


class RegistryError(RuntimeError):
    __module__ = "odoo.http"

    db_absent: bool | None = None
    transient: bool = False


class SessionExpiredException(Exception):
    __module__ = "odoo.http"

    http_status: int = HTTPStatus.FORBIDDEN


def get_error_response(exc: BaseException) -> ErrorResponse | None:
    return getattr(exc, "error_response", None)


def set_error_response(exc: BaseException, response: ErrorResponse) -> None:
    carrier: Any = exc
    carrier.error_response = response


__all__ = (
    "BadGateway",
    "BadRequest",
    "Forbidden",
    "GatewayTimeout",
    "Gone",
    "HTTPException",
    "InternalServerError",
    "Locked",
    "MethodNotAllowed",
    "NotFound",
    "RegistryError",
    "RequestEntityTooLarge",
    "ServiceUnavailable",
    "SessionExpiredException",
    "TooManyRequests",
    "Unauthorized",
    "UnprocessableEntity",
    "UnsupportedMediaType",
    "abort",
    "get_error_response",
    "set_error_response",
)

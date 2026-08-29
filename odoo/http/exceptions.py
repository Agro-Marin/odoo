from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from werkzeug.exceptions import HTTPException

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

from http import HTTPStatus


class RegistryError(RuntimeError):
    """Error accessing the database registry."""

    __module__ = "odoo.http"

    db_absent: bool | None = None
    transient: bool = False


class SessionExpiredException(Exception):
    """The user session has expired."""

    __module__ = "odoo.http"

    http_status = HTTPStatus.FORBIDDEN

from http import HTTPStatus


class RegistryError(RuntimeError):
    __module__ = "odoo.http"

    db_absent: bool | None = None
    transient: bool = False


class SessionExpiredException(Exception):
    __module__ = "odoo.http"

    http_status = HTTPStatus.FORBIDDEN

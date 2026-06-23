from http import HTTPStatus


class RegistryError(RuntimeError):
    """Error accessing the database registry."""


# Name predates ruff's N818 ``Error``-suffix rule; exported in ``odoo.http`` and
# caught by 40+ call sites across core/enterprise, so renaming would break them.
class SessionExpiredException(Exception):  # noqa: N818
    """The user session has expired."""

    http_status = HTTPStatus.FORBIDDEN

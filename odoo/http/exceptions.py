from http import HTTPStatus


class RegistryError(RuntimeError):
    """Error accessing the database registry."""


# Historical name predates ruff's N818 ``Error`` suffix rule and is exported
# in ``odoo.http`` plus referenced by 40+ call sites across core/enterprise.
# Renaming would break every external addon catching it.
class SessionExpiredException(Exception):  # noqa: N818
    """The user session has expired."""

    http_status = HTTPStatus.FORBIDDEN

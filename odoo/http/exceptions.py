from http import HTTPStatus

# Both classes below pin ``__module__ = "odoo.http"``: their public import path
# IS ``odoo.http`` (re-exported by ``odoo/http/__init__.py``), and
# ``serialize_exception`` (``helpers.py``) embeds ``__module__`` in the JSON-RPC
# error ``name`` that the JS error registries key on (``error_dialogs.js``,
# ``error_notifications.js`` expect ``odoo.http.SessionExpiredException``, as
# does upstream/third-party code). Without the pin, the http.py -> package
# split would leak ``odoo.http.exceptions.*`` names onto the wire and break
# that contract. Pickling still resolves thanks to the re-export.


class RegistryError(RuntimeError):
    """Error accessing the database registry.

    :attr:`db_absent` qualifies the failure for the recovery path
    (``Application._recover_from_registry_error``): ``True`` — the database is
    confirmed gone from the catalog; ``False`` — the database exists but its
    registry is unusable (broken schema, dead signaling); ``None`` — the
    catalog itself could not be consulted (PostgreSQL unreachable), so nothing
    is known about the database. Only the ``None`` case is a pure
    infrastructure blip, where logging the session out would be destructive.
    """

    __module__ = "odoo.http"

    db_absent: bool | None = None


# Name predates ruff's N818 ``Error``-suffix rule; exported in ``odoo.http`` and
# caught by 40+ call sites across core/enterprise, so renaming would break them.
class SessionExpiredException(Exception):
    """The user session has expired."""

    __module__ = "odoo.http"

    http_status = HTTPStatus.FORBIDDEN

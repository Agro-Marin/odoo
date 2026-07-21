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
    """Error accessing the database registry."""

    __module__ = "odoo.http"


# Name predates ruff's N818 ``Error``-suffix rule; exported in ``odoo.http`` and
# caught by 40+ call sites across core/enterprise, so renaming would break them.
class SessionExpiredException(Exception):
    """The user session has expired."""

    __module__ = "odoo.http"

    http_status = HTTPStatus.FORBIDDEN

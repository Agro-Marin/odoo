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

    Two attributes qualify the failure for the recovery path
    (``Application._recover_from_registry_error``):

    :attr:`db_absent` — what the catalog said: ``True``, the database is
    confirmed gone; ``False``, it exists; ``None``, the catalog itself could
    not be consulted (PostgreSQL unreachable).

    :attr:`transient` — whether the underlying failure is a passing condition
    (connection loss, pool starvation, a registry observed mid-build) rather
    than a durable one (broken schema). A durable session logout is warranted
    only for a confirmed-dropped database or a durably broken registry;
    logging every user out over a passing blip forces a site-wide re-login.

    The class defaults (``None``/``False``) give a foreign raiser upstream's
    durable-logout behaviour only when it also claims ``db_absent=False``.
    """

    __module__ = "odoo.http"

    db_absent: bool | None = None
    transient: bool = False


# Name predates ruff's N818 ``Error``-suffix rule; exported in ``odoo.http`` and
# caught by 40+ call sites across core/enterprise, so renaming would break them.
class SessionExpiredException(Exception):
    """The user session has expired."""

    __module__ = "odoo.http"

    http_status = HTTPStatus.FORBIDDEN

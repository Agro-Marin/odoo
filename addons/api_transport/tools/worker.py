"""Worker-thread environment helper for async event/webhook handlers."""

from contextlib import contextmanager


@contextmanager
def worker_env(db_name, uid=None):
    """Yield a fresh-cursor ``api.Environment`` for worker-thread handlers.

    Odoo 19 removed the top-level ``odoo.registry()`` shortcut, so every async
    event/webhook handler must build its environment from
    ``Registry(db_name).cursor()``.  This wraps that idiom in one place instead
    of repeating it per handler.  The cursor commits on clean exit and rolls
    back automatically on exception.

    :param str db_name: database whose registry provides the cursor.
    :param int uid: acting user id (defaults to ``SUPERUSER_ID``).
    :return: a short-lived environment bound to a fresh cursor.
    :rtype: odoo.api.Environment
    """
    from odoo import SUPERUSER_ID, api
    from odoo.modules.registry import Registry

    registry = Registry(db_name)
    with registry.cursor() as cr:
        yield api.Environment(cr, uid or SUPERUSER_ID, {})

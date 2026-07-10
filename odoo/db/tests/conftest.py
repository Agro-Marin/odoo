"""Enable standalone testing of the pure ``odoo.db`` helpers.

Registers ``sys.modules`` stubs for ``odoo`` and ``odoo.db`` so
``from odoo.db.savepoint import Savepoint`` resolves to the leaf module without
executing ``odoo/db/__init__.py`` (which pulls in psycopg, the pool, etc.).
See :mod:`odoo._testing_bootstrap` for the shared helper.
"""

from odoo._testing_bootstrap import stub_odoo_packages

stub_odoo_packages(__file__)

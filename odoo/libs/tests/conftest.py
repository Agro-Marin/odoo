"""Enable standalone (database-free) testing of top-level ``odoo.libs`` leaf modules.

Registers ``sys.modules`` stubs for ``odoo`` and ``odoo.libs`` so
``from odoo.libs.X import Y`` resolves to the leaf module without executing the
heavy package ``__init__.py`` files.  See :mod:`odoo._testing_bootstrap`.
"""

from odoo._testing_bootstrap import stub_odoo_packages

stub_odoo_packages(__file__)

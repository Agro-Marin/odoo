"""Enable standalone (database-free) testing of ``odoo.tools`` leaf modules.

Registers ``sys.modules`` stubs for ``odoo`` and ``odoo.tools`` so
``from odoo.tools.X import Y`` resolves to the leaf module without executing
the heavy ``odoo/tools/__init__.py``.  See :mod:`odoo._testing_bootstrap`.
"""

from odoo._testing_bootstrap import stub_odoo_packages

stub_odoo_packages(__file__)

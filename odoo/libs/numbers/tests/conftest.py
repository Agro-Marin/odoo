"""Enable standalone (database-free) testing of ``odoo.libs.numbers`` leaves.

See :mod:`odoo._testing_bootstrap`; stubs ``odoo``, ``odoo.libs`` and
``odoo.libs.numbers`` so leaf modules import without the heavy package inits.
"""

from odoo._testing_bootstrap import stub_odoo_packages

stub_odoo_packages(__file__)

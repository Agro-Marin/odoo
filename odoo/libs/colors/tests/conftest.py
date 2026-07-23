"""Enable standalone (database-free) testing of ``odoo.libs.colors`` leaves.

Registers ``sys.modules`` stubs so ``from odoo.libs.colors.X import Y`` resolves
to the leaf module without executing the heavy package ``__init__.py`` files.
See :mod:`odoo._testing_bootstrap`.
"""

from odoo._testing_bootstrap import stub_odoo_packages

stub_odoo_packages(__file__)

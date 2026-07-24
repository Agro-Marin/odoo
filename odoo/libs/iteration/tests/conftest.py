"""Enable standalone ``odoo.libs.iteration`` testing without the full import chain.

Registers ``sys.modules`` stubs for ``odoo``, ``odoo.libs`` and
``odoo.libs.iteration`` so ``from odoo.libs.iteration.sorting import …``
resolves to the leaf module without executing ``odoo/libs/__init__.py``.  See
:mod:`odoo._testing_bootstrap` for the shared helper.
"""

from odoo._testing_bootstrap import stub_odoo_packages

stub_odoo_packages(__file__)

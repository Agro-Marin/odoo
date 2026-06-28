"""Enable standalone ``odoo.libs.text`` testing without the full Odoo import chain.

Registers ``sys.modules`` stubs for ``odoo``, ``odoo.libs`` and
``odoo.libs.text`` so ``from odoo.libs.text.html import …`` resolves to the leaf
module without executing ``odoo/libs/__init__.py``.  See
:mod:`odoo._testing_bootstrap` for the shared helper.
"""

from odoo._testing_bootstrap import stub_odoo_packages

stub_odoo_packages(__file__)

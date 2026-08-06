"""Enable standalone ``odoo.libs.json`` testing without the full Odoo import chain.

Registers ``sys.modules`` stubs for ``odoo`` / ``odoo.libs`` so the leaf modules
resolve without executing ``odoo/libs/__init__.py``. See
:mod:`odoo._testing_bootstrap`.
"""

from odoo._testing_bootstrap import stub_odoo_packages

stub_odoo_packages(__file__)

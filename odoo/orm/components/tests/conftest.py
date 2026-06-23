"""Enable standalone component testing without the full Odoo import chain.

Registers ``sys.modules`` stubs for ``odoo``, ``odoo.orm`` and
``odoo.orm.components`` so ``from odoo.orm.components.X import Y`` resolves to
the leaf module without executing ``odoo/orm/__init__.py`` (which imports the
whole framework).  See :mod:`odoo._testing_bootstrap` for the shared helper.
"""

from odoo._testing_bootstrap import stub_odoo_packages

stub_odoo_packages(__file__)

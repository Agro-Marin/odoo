"""Enable standalone ``_field_access`` testing without the full Odoo import chain.

Registers ``sys.modules`` stubs for ``odoo``, ``odoo.libs`` and
``odoo.libs._field_access`` so ``from odoo.libs._field_access.X import Y``
resolves to the leaf module without executing ``odoo/libs/__init__.py``.  See
:mod:`odoo._testing_bootstrap` for the shared helper.

Previously this directory had no conftest and only collected if another stub
suite had registered the stubs first — a fragile run-order dependency, now fixed.
"""

from odoo._testing_bootstrap import stub_odoo_packages

stub_odoo_packages(__file__)

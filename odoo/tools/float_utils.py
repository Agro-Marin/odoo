"""Compatibility re-exports for ``odoo.tools.float_utils``.

The implementations live in :mod:`odoo.libs.numbers` (ADR-0004); this module
keeps the historical import path working for addon code.

``round`` needs the second, explicit import: it shadows the builtin, so
``odoo.libs.numbers`` keeps it out of ``__all__`` and the star import does not
carry it — while upstream's ``odoo.tools.float_utils.round`` was reachable as a
module attribute, which addon code may rely on. It comes from the area, not the
leaf module, because the area is the public boundary (``libs_facade_check``).
"""

from odoo.libs.numbers import *  # noqa: F403
from odoo.libs.numbers import round  # noqa: F401  (re-export)

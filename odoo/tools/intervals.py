"""
Backward compatibility shim.

This module re-exports from odoo.libs.intervals.
New code should import from odoo.libs.intervals directly.

.. deprecated:: 19.0
   Import from ``odoo.libs.intervals`` instead.
"""

import warnings

warnings.warn(
    "odoo.tools.intervals is deprecated. Use odoo.libs.intervals instead.",
    DeprecationWarning,
    stacklevel=2,
)

from odoo.libs.intervals import *  # noqa: F403, E402  # deprecation warning must fire before re-exports
from odoo.libs.intervals import _boundaries  # noqa: F401, E402  # re-export underscore name (not covered by `import *`)

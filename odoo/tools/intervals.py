"""Backward compatibility shim re-exporting odoo.libs.intervals.

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
from odoo.libs.intervals import (  # noqa: E402  # deprecation warning must fire before re-exports
    _boundaries,  # noqa: F401  # re-export underscore name (not covered by `import *`)
)

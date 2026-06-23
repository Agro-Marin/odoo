"""Back-compat shim — ``TestCursor`` moved to :mod:`odoo.tests.cursor`.

The module was renamed to drop the misleading ``test_`` prefix (it is a
pseudo-cursor *utility*, not a test module).  This re-export keeps the old
import path ``from odoo.tests.test_cursor import TestCursor`` working.
"""

from .cursor import TestCursor  # noqa: F401

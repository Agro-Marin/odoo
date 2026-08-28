"""`column_exists` / `index_exists` return a real `bool`, not a truthy rowcount.

Lived in `odoo/libs/sql/tests/test_sql_builder.py`, which is the wrong suite in
two ways: the subject is `odoo.db.schema`, not the SQL builder, and reaching
`odoo.db` from a `odoo/libs/sql` suite pulls `odoo.tools.__init__` -> `query` ->
`from odoo.libs.sql import SQL`, which under the Tier-1 stub for that very
package is an ImportError. The failure was invisible because the suite could not
be collected at all when named on its own.
"""

import unittest


class TestColumnIndexExistsReturnBool(unittest.TestCase):
    class _Cursor:
        def __init__(self, rowcount: int) -> None:
            self.rowcount = rowcount

        def execute(self, *args, **kwargs) -> None:
            pass

    def test_true_is_bool(self):
        from odoo.db.schema import column_exists, index_exists

        cr = self._Cursor(1)
        self.assertIs(column_exists(cr, "t", "c"), True)  # type: ignore[arg-type]
        self.assertIs(index_exists(cr, "i"), True)  # type: ignore[arg-type]

    def test_false_is_bool(self):
        from odoo.db.schema import column_exists, index_exists

        cr = self._Cursor(0)
        self.assertIs(column_exists(cr, "t", "c"), False)  # type: ignore[arg-type]
        self.assertIs(index_exists(cr, "i"), False)  # type: ignore[arg-type]

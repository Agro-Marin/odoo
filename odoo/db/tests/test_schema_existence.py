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

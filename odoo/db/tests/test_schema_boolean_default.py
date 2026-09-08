import unittest
from unittest.mock import MagicMock

from odoo.db.schema import create_column


def _ddl_for(columntype):
    cr = MagicMock()
    create_column(cr, "some_table", "some_column", columntype)
    return cr.execute.call_args[0][0].code


class TestBooleanColumnDefault(unittest.TestCase):
    def test_the_orm_spelling_takes_no_default(self):
        self.assertNotIn("DEFAULT", _ddl_for("bool"))

    def test_the_explicit_spelling_still_takes_one(self):
        for spelling in ("boolean", "BOOLEAN", "Boolean"):
            with self.subTest(spelling=spelling):
                self.assertIn("DEFAULT false", _ddl_for(spelling))

    def test_other_types_take_no_default(self):
        for columntype in ("int4", "varchar", "numeric", "timestamp"):
            with self.subTest(columntype=columntype):
                self.assertNotIn("DEFAULT", _ddl_for(columntype))

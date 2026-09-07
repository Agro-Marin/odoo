import unittest
from unittest.mock import MagicMock

from odoo.db.schema import create_column


def _ddl_for(columntype):
    cr = MagicMock()
    create_column(cr, "some_table", "some_column", columntype)
    return cr.execute.call_args[0][0].code


class TestBooleanColumnDefault(unittest.TestCase):
    """The DDL default belongs to the explicit spelling only.

    `fields.Boolean._column_type` is ("bool", "bool"), so every column the ORM
    creates for a Boolean field must take the branch WITHOUT a default:
    `_init_column` backfills the field's own default with
    `UPDATE ... WHERE <column> IS NULL`, and a DDL default fills those rows
    first, leaving the backfill nothing to match. A field declared
    `default=True` then lands false on every pre-existing row.

    `res.company.active` is exactly that shape -- `base_data.sql` inserts
    company 1 with no `active` -- so normalizing the spelling once made the
    company come up archived, filtered it out of every user's `company_ids`,
    and stopped `base` from installing its own admin user.
    """

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

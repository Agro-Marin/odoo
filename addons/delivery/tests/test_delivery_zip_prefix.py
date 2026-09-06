from psycopg import IntegrityError

from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged("post_install", "-at_install")
class TestDeliveryZipPrefix(TransactionCase):
    def test_create_without_name_raises_cleanly(self):
        """A missing `name` must fail on the `required` constraint, not with
        a raw `KeyError` from `create()`'s own upper-casing logic."""
        with self.assertRaises(IntegrityError), mute_logger("odoo.db.cursor"):
            self.env["delivery.zip.prefix"].create({})

    def test_create_uppercases_name(self):
        prefix = self.env["delivery.zip.prefix"].create({"name": "abc"})
        self.assertEqual(prefix.name, "ABC")

import psycopg

from odoo.tests import tagged
from odoo.tools import mute_logger

from .common import BaseOrderTestCase


@tagged("post_install", "-at_install")
class TestSmoke(BaseOrderTestCase):
    def test_order_and_line_instantiate(self):
        order = self._make_order()
        line = self._make_line(order=order)

        self.assertEqual(line.order_id, order)
        self.assertEqual(order.state, "draft")
        self.assertIn(line, order.line_ids)

    def test_order_name_from_sequence(self):
        order = self._make_order()

        self.assertTrue(order.name)
        self.assertNotEqual(order.name, "New")

    @mute_logger("odoo.db.cursor")
    def test_line_requires_order(self):
        with self.assertRaises(psycopg.IntegrityError):
            self.env["base.order.test.line"].create(
                {"product_id": self.product.id}
            )
            self.env.flush_all()

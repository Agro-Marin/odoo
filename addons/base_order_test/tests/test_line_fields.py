from odoo.tests import tagged

from .common import BaseOrderTestCase


@tagged("post_install", "-at_install")
class TestLineFields(BaseOrderTestCase):
    def _line_no_name(self, **kw):
        order = self._make_order()
        vals = {"order_id": order.id, "product_id": self.product.id}
        vals.update(kw)
        return self.env["base.order.test.line"].create(vals)

    def test_name_computed_from_product(self):
        line = self._line_no_name()

        # test hook returns product.display_name
        self.assertIn(self.product.name, line.name)

    def test_name_not_computed_for_section(self):
        order = self._make_order()

        section = self.env["base.order.test.line"].create(
            {
                "order_id": order.id,
                "display_type": "line_section",
                "name": "My Section",
            }
        )

        self.assertEqual(section.name, "My Section")

    def test_qty_change_tracked_on_confirmed_order(self):
        order = self._make_order()
        line = self._make_line(order=order, product_qty=5.0)
        order.state = "done"
        before = len(order.message_ids)

        line.write({"product_qty": 8.0})

        self.assertEqual(line.product_qty, 8.0)
        self.assertGreater(len(order.message_ids), before)

    def test_qty_change_not_tracked_on_draft_order(self):
        order = self._make_order()
        line = self._make_line(order=order, product_qty=5.0)
        before = len(order.message_ids)

        line.write({"product_qty": 8.0})

        self.assertEqual(len(order.message_ids), before)

    def test_default_product_qty(self):
        line = self._line_no_name()

        self.assertEqual(line.product_qty, 1.0)

    def test_default_product_uom_from_product(self):
        line = self._line_no_name()

        self.assertEqual(line.product_uom_id, self.product.uom_id)

    def test_allowed_uoms_include_product_uom(self):
        line = self._line_no_name()

        self.assertIn(self.product.uom_id, line.allowed_uom_ids)

    def test_product_uom_qty_matches_qty_same_uom(self):
        line = self._line_no_name(product_qty=3.0)

        self.assertEqual(line.product_uom_qty, 3.0)

    def test_product_name_translated_populated(self):
        line = self._line_no_name()

        self.assertEqual(line.product_name_translated, self.product.display_name)

    def test_product_is_archived_flag(self):
        line = self._line_no_name()
        self.assertFalse(line.product_is_archived)

        self.product.active = False
        line.invalidate_recordset(["product_is_archived"])

        self.assertTrue(line.product_is_archived)

    def test_section_line_has_no_qty(self):
        order = self._make_order()

        section = self.env["base.order.test.line"].create(
            {
                "order_id": order.id,
                "display_type": "line_section",
                "name": "Section",
            }
        )

        self.assertFalse(section.product_qty)
        self.assertFalse(section.product_uom_qty)

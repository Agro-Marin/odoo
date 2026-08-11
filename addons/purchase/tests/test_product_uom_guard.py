from odoo.fields import Command
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestProductUomGuard(TransactionCase):
    """Purchase-side guards around a product's unit of measure."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.vendor = cls.env["res.partner"].create({"name": "UoM vendor"})
        cls.product = cls.env["product.product"].create(
            {
                "name": "Convertible part",
                "type": "consu",
                "purchase_ok": True,
            }
        )
        cls.unit = cls.env.ref("uom.product_uom_unit")
        cls.dozen = cls.env.ref("uom.product_uom_dozen")

    def _order(self, qty=2):
        return self.env["purchase.order"].create(
            {
                "partner_id": self.vendor.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product.id,
                            "product_qty": qty,
                        }
                    )
                ],
            }
        )

    def test_untouched_product_changes_unit_silently(self):
        """A product nobody ordered can change unit without a warning."""
        self.assertFalse(self.product._trigger_uom_warning())

    def test_ordered_product_warns_before_changing_unit(self):
        """Once purchase lines exist the unit change must be flagged."""
        self._order()
        self.assertTrue(self.product._trigger_uom_warning())

    def test_changing_the_unit_rewrites_the_order_lines(self):
        """Accepting the change carries the new unit onto existing lines."""
        order = self._order()
        self.product._update_uom(self.dozen.id)
        self.assertEqual(order.line_ids.product_uom_id, self.dozen)

    def test_purchase_history_lists_confirmed_orders_only(self):
        """The history action scopes to confirmed orders of this product."""
        action = self.product.action_view_po()
        self.assertIn(("state", "=", "done"), action["domain"])
        self.assertIn(("product_id", "in", self.product.ids), action["domain"])
        self.assertIn(self.product.display_name, action["display_name"])

    def test_purchase_import_template_is_context_driven(self):
        """The purchase import template is offered only in its own context."""
        Template = self.env["product.template"]
        offered = Template.with_context(
            purchase_product_template=True
        ).get_import_templates()
        self.assertEqual(len(offered), 1)
        self.assertIn("product_purchase.xls", offered[0]["template"])

    def test_purchase_menu_joins_the_product_backend_menus(self):
        """The product's backend menus include the purchase root."""
        menus = self.product._get_backend_root_menu_ids()
        self.assertIn(self.env.ref("purchase.menu_purchase_root").id, menus)

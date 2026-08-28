from odoo.fields import Command
from odoo.tests import TransactionCase, tagged

# subir-cobertura for sale_order._get_unavailable_quantity_from_kits: the
# existing suite is a browser tour, so this exercises the Python kit-availability
# method directly with a phantom-BoM fixture.


@tagged("post_install", "-at_install")
class TestKitUnavailability(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "Shopper"})
        cls.component_a = cls.env["product.product"].create(
            {"name": "Component A", "type": "consu", "is_storable": True}
        )
        cls.other = cls.env["product.product"].create({"name": "Unrelated"})
        cls.kit = cls.env["product.product"].create(
            {"name": "Kit", "type": "consu", "is_storable": True}
        )
        cls.env["mrp.bom"].create(
            {
                "product_tmpl_id": cls.kit.product_tmpl_id.id,
                "type": "phantom",
                "product_qty": 1,
                "bom_line_ids": [
                    Command.create({"product_id": cls.component_a.id, "product_qty": 2})
                ],
            }
        )

    def _order_with_kit(self):
        return self.env["sale.order"].create(
            {
                "partner_id": self.partner.id,
                "line_ids": [Command.create({"product_id": self.kit.id})],
            }
        )

    def test_empty_order_has_no_kit_unavailability(self):
        """An order with no lines makes no component unavailable."""
        order = self.env["sale.order"].create({"partner_id": self.partner.id})
        self.assertEqual(order._get_unavailable_quantity_from_kits(self.component_a), 0)

    def test_kit_line_consumes_its_component(self):
        """A kit line makes its component unavailable by the per-kit quantity."""
        order = self._order_with_kit()
        qty = order.line_ids.product_uom_qty
        self.assertEqual(
            order._get_unavailable_quantity_from_kits(self.component_a), 2 * qty
        )

    def test_bom_stated_in_another_uom_consumes_the_full_quantity(self):
        """A BoM stated per dozen used to under-report what its line consumes.

        `_get_bom_component_qty` converted one product-unit into the BoM's unit
        and rounded (1/12 -> 0.08), then exploded that fraction, so the shop
        thought a kit line consumed 1.92 components where it consumes 2 -- and
        could oversell on the 4% it did not count.
        """
        component = self.env["product.product"].create(
            {"name": "Dozen-BoM component", "type": "consu", "is_storable": True}
        )
        kit = self.env["product.product"].create(
            {"name": "Dozen-BoM kit", "type": "consu", "is_storable": True}
        )
        self.env["mrp.bom"].create(
            {
                "product_tmpl_id": kit.product_tmpl_id.id,
                "type": "phantom",
                "product_qty": 1,
                "product_uom_id": self.env.ref("uom.product_uom_dozen").id,
                "bom_line_ids": [
                    Command.create({"product_id": component.id, "product_qty": 24})
                ],
            }
        )
        order = self.env["sale.order"].create(
            {
                "partner_id": self.partner.id,
                "line_ids": [Command.create({"product_id": kit.id})],
            }
        )

        self.assertEqual(
            order._get_unavailable_quantity_from_kits(component),
            2 * order.line_ids.product_uom_qty,
        )

    def test_unrelated_product_is_unaffected_by_kit(self):
        """A product not in any kit is not made unavailable by kit lines."""
        order = self._order_with_kit()
        self.assertEqual(order._get_unavailable_quantity_from_kits(self.other), 0)

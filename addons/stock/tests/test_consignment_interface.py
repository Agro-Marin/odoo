from odoo import Command
from odoo.tests import TransactionCase


class TestConsignmentInterface(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.picking_type_out = cls.env.ref("stock.picking_type_out")
        cls.stock_location = cls.env.ref("stock.stock_location_stock")
        cls.customer_location = cls.env.ref("stock.stock_location_customers")
        cls.partner = cls.env["res.partner"].create({"name": "Consignee"})
        cls.product = cls.env["product.product"].create(
            {"name": "Weighed", "is_storable": True, "weight": 2.5}
        )

    def _make_picking(self, quantity):
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.picking_type_out.id,
                "partner_id": self.partner.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "move_ids": [
                    Command.create(
                        {
                            "product_id": self.product.id,
                            "product_uom_qty": quantity,
                            "location_id": self.stock_location.id,
                            "location_dest_id": self.customer_location.id,
                        }
                    )
                ],
            }
        )
        picking.action_confirm()
        picking.move_ids.quantity = quantity
        return picking

    def test_a_picking_is_its_own_consignment(self):
        picking = self._make_picking(3)
        self.assertEqual(picking._get_consignment_pickings(), picking)
        self.assertEqual(picking._get_consignment_moves(), picking.move_ids)
        self.assertEqual(picking._get_consignment_move_lines(), picking.move_line_ids)
        self.assertEqual(picking._get_consignment_partners(), self.partner)

    def test_the_consignment_weight_follows_the_move_lines(self):
        picking = self._make_picking(4)
        self.assertEqual(picking._get_consignment_weight(), 10.0)

    def test_every_consignment_answers_the_same_four_names(self):
        interface = self.env["mixin.stock.consignment"]
        names = [
            "_get_consignment_pickings",
            "_get_consignment_moves",
            "_get_consignment_move_lines",
            "_get_consignment_partners",
            "_get_consignment_weight",
        ]
        for name in names:
            self.assertTrue(hasattr(interface, name))
            self.assertTrue(hasattr(self.env["stock.picking"], name))

    def test_the_interface_refuses_a_host_that_does_not_resolve_its_pickings(self):
        with self.assertRaises(NotImplementedError):
            self.env["mixin.stock.consignment"]._get_consignment_pickings()

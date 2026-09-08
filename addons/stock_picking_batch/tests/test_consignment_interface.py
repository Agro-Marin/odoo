from odoo import Command
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestBatchConsignmentInterface(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.stock_location = cls.env.ref("stock.stock_location_stock")
        cls.customer_location = cls.env.ref("stock.stock_location_customers")
        cls.picking_type = cls.env.ref("stock.picking_type_out")
        cls.partner = cls.env["res.partner"].create({"name": "Consignee"})
        cls.product = cls.env["product.product"].create(
            {"name": "Weighed", "is_storable": True, "weight": 2.5}
        )
        cls.env["stock.quant"]._update_available_quantity(
            cls.product, cls.stock_location, 1000
        )

    def _make_picking(self, quantity):
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.picking_type.id,
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
        picking.action_assign()
        return picking

    def _make_batch(self, pickings):
        return self.env["stock.picking.batch"].create(
            {
                "picking_type_id": self.picking_type.id,
                "picking_ids": [Command.set(pickings.ids)],
            }
        )

    def test_a_batch_resolves_to_every_transfer_it_holds(self):
        pickings = self._make_picking(3) | self._make_picking(5)
        batch = self._make_batch(pickings)
        self.assertEqual(batch._get_consignment_pickings(), pickings)
        self.assertEqual(batch._get_consignment_moves(), pickings.move_ids)
        self.assertEqual(batch._get_consignment_move_lines(), pickings.move_line_ids)
        self.assertEqual(batch._get_consignment_partners(), self.partner)

    def test_a_batch_weighs_what_its_transfers_weigh_together(self):
        first, second = self._make_picking(3), self._make_picking(5)
        batch = self._make_batch(first | second)
        self.assertEqual(
            batch._get_consignment_weight(),
            first._get_consignment_weight() + second._get_consignment_weight(),
        )
        self.assertEqual(batch._get_consignment_weight(), 20.0)

    def test_one_transfer_weighs_the_same_alone_as_in_a_batch(self):
        picking = self._make_picking(4)
        alone = picking._get_consignment_weight()
        batch = self._make_batch(picking)
        self.assertEqual(batch._get_consignment_weight(), alone)

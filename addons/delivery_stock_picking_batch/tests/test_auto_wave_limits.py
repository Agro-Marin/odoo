from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestAutoWaveWeightLimit(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.stock_location = cls.env.ref("stock.stock_location_stock")
        cls.customer_location = cls.env.ref("stock.stock_location_customers")
        cls.picking_type = cls.env.ref("stock.picking_type_out").copy(
            {"name": "Auto wave limit", "sequence_code": "AWL"}
        )
        cls.picking_type.write(
            {
                "auto_batch": True,
                "batch_group_by_partner": False,
                "batch_group_by_destination": False,
                "batch_group_by_src_loc": False,
                "batch_group_by_dest_loc": False,
                "wave_group_by_product": True,
                "wave_group_by_category": False,
                "wave_group_by_location": False,
                "batch_max_lines": 0,
                "batch_max_pickings": 0,
                "batch_max_weight": 1000,
            }
        )
        cls.product = cls.env["product.product"].create(
            {"name": "Heavy sack", "is_storable": True, "weight": 25.0}
        )
        cls.env["stock.quant"]._update_available_quantity(
            cls.product, cls.stock_location, 1000
        )

    def _pickings(self, units):
        return self.env["stock.picking"].create(
            [
                {
                    "picking_type_id": self.picking_type.id,
                    "location_id": self.stock_location.id,
                    "location_dest_id": self.customer_location.id,
                    "move_ids": [
                        (
                            0,
                            0,
                            {
                                "product_id": self.product.id,
                                "product_uom_qty": units,
                                "location_id": self.stock_location.id,
                                "location_dest_id": self.customer_location.id,
                            },
                        )
                    ],
                }
                for _ in range(2)
            ]
        )

    def test_a_line_under_the_weight_cap_waves_normally(self):
        pickings = self._pickings(8)
        pickings.action_confirm()
        pickings.action_assign()
        self.assertEqual(pickings.mapped("state"), ["assigned", "assigned"])
        self.assertTrue(pickings.batch_id.is_wave)

    def test_a_line_over_the_weight_cap_still_reserves(self):
        pickings = self._pickings(45)
        pickings.action_confirm()
        pickings.action_assign()
        self.assertEqual(pickings.mapped("state"), ["assigned", "assigned"])

    def test_a_line_over_the_weight_cap_creates_no_empty_wave(self):
        before = self.env["stock.picking.batch"].search_count([])
        pickings = self._pickings(45)
        pickings.action_confirm()
        pickings.action_assign()
        waves = self.env["stock.picking.batch"].search([("is_wave", "=", True)])
        self.assertFalse(
            waves.filtered(lambda w: not w.picking_ids),
            "auto-waving created a wave holding no transfer",
        )
        self.assertLessEqual(
            self.env["stock.picking.batch"].search_count([]) - before,
            2,
            "auto-waving created more batch records than transfers",
        )

    def test_a_lone_line_over_the_weight_cap_is_not_waved_either(self):
        picking = self._pickings(45)[:1]
        picking.action_confirm()
        picking.action_assign()
        self.assertEqual(picking.state, "assigned")
        self.assertFalse(
            picking.batch_id,
            "a line no wave can hold is left alone whether or not it has a partner",
        )

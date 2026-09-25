from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestDispatchMode(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search([], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customer_location = cls.env.ref("stock.stock_location_customers")
        cls.out_type = cls.warehouse.out_type_id
        cls.out_type.write(
            {"dispatch_management": True, "dispatch_batch_required": True}
        )
        cls.product = cls.env["product.product"].create(
            {"name": "Freight", "is_storable": True}
        )
        cls.env["stock.quant"]._update_available_quantity(
            cls.product, cls.stock_location, 100
        )
        service = cls.env["product.product"].create(
            {"name": "Freight", "type": "service"}
        )
        cls.carriers = {
            mode: cls.env["delivery.carrier"].create(
                {
                    "name": mode,
                    "delivery_type": "fixed",
                    "product_id": service.id,
                    "dispatch_mode": mode,
                }
            )
            for mode in ("own_fleet", "salesperson", "third_party", "pickup")
        }

    def _picking(self, mode=None, location=None):
        location = location or self.stock_location
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.out_type.id,
                "location_id": location.id,
                "location_dest_id": self.customer_location.id,
                "carrier_id": mode and self.carriers[mode].id,
                "move_ids": [
                    Command.create(
                        {
                            "product_id": self.product.id,
                            "product_uom_qty": 1,
                            "location_id": location.id,
                            "location_dest_id": self.customer_location.id,
                        }
                    )
                ],
            }
        )
        picking.action_confirm()
        picking.action_assign()
        picking.move_ids.picked = True
        return picking

    def test_own_fleet_salesperson_and_no_carrier_travel_in_a_trip(self):
        for mode in (None, "own_fleet", "salesperson"):
            with self.subTest(mode=mode):
                picking = self._picking(mode)
                self.assertTrue(picking._requires_trip())
                with self.assertRaisesRegex(UserError, "must be delivered from a trip"):
                    picking.button_validate()

    def test_a_third_party_carrier_needs_its_tracking_reference(self):
        picking = self._picking("third_party")
        self.assertFalse(picking._requires_trip())
        with self.assertRaisesRegex(UserError, "tracking reference"):
            picking.button_validate()
        picking.carrier_tracking_ref = "TG-123"
        picking.button_validate()
        self.assertEqual(picking.state, "done")

    def test_a_customer_pickup_does_not_travel_in_a_trip(self):
        picking = self._picking("pickup")
        picking.button_validate()
        self.assertEqual(picking.state, "done")

    def test_a_third_party_transit_sets_the_mode_when_the_carrier_does_not(self):
        transit = self.env["stock.location"].create(
            {
                "name": "Third-party transit",
                "usage": "transit",
                "dispatch_mode": "third_party",
            }
        )
        self.env["stock.quant"]._update_available_quantity(self.product, transit, 10)
        picking = self._picking(location=transit)
        self.assertEqual(picking._get_dispatch_mode(), "third_party")
        self.assertFalse(picking._requires_trip())
        with self.assertRaisesRegex(UserError, "tracking reference"):
            picking.button_validate()
        picking.carrier_tracking_ref = "TG-9"
        picking.button_validate()
        self.assertEqual(picking.state, "done")

    def test_the_carrier_mode_wins_over_the_location_mode(self):
        transit = self.env["stock.location"].create(
            {"name": "Transit", "usage": "transit", "dispatch_mode": "third_party"}
        )
        self.env["stock.quant"]._update_available_quantity(self.product, transit, 10)
        picking = self._picking("own_fleet", location=transit)
        self.assertTrue(picking._requires_trip())

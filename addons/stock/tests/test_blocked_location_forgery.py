from odoo.exceptions import UserError

from .blocked_location_common import BlockedLocationCase


class TestContextForgery(BlockedLocationCase):
    def test_completing_flag_cannot_be_forged_at_the_quant_layer(self):
        self._add_stock(self.soft_out_location, 100.0)
        with self.assertRaises(UserError):
            self.Quant.with_user(self.normal_user).with_context(
                stock_blocked_completing=True
            )._update_available_quantity(self.product, self.soft_out_location, -50.0)
        self.assertEqual(self._on_hand(self.soft_out_location), 100.0)

    def test_completing_flag_cannot_be_forged_at_the_line_layer(self):
        self._add_stock(self.soft_out_location, 100.0)
        picking = self._make_delivery(self.normal_user, self.soft_out_location, 10.0)
        picking.do_unreserve()
        with self.assertRaises(UserError):
            picking.with_user(self.normal_user).with_context(
                stock_blocked_completing=True
            ).move_ids.quantity = 10.0
        self.assertEqual(self._on_hand(self.soft_out_location), 100.0)

    def test_is_inventory_flag_cannot_be_forged(self):
        self._add_stock(self.soft_out_location, 100.0)
        with self.assertRaises(UserError):
            self.Quant.with_user(self.normal_user).with_context(
                stock_blocked_is_inventory=True
            )._update_available_quantity(self.product, self.soft_out_location, -50.0)
        self.assertEqual(self._on_hand(self.soft_out_location), 100.0)

    def test_excluded_types_cannot_be_forged(self):
        self._add_stock(self.soft_out_location, 100.0)
        quants = (
            self.Quant.with_user(self.normal_user)
            .with_context(stock_blocked_excluded_types=())
            ._gather(self.product, self.stock_location)
        )
        self.assertFalse(
            quants.filtered(lambda q: q.location_id == self.soft_out_location),
            "an empty exclusion sent by the client must not un-filter gathering",
        )

    def test_excluded_types_cannot_be_forged_through_available_quantity(self):
        self._add_stock(self.soft_out_location, 100.0)
        self._add_stock(self.normal_location, 50.0)
        available = (
            self.Quant.with_user(self.normal_user)
            .with_context(stock_blocked_excluded_types=())
            ._get_available_quantity(self.product, self.stock_location)
        )
        self.assertEqual(available, 50.0)

    def test_skip_hooks_flag_cannot_be_forged(self):
        with self.assertRaises(UserError):
            self.hard_block_location.with_user(self.manager_user).with_context(
                stock_blocked_skip_hooks=True
            ).write({"block_type": "none"})
        self.assertEqual(self.hard_block_location.block_type, "hard")

    def test_visibility_bypass_cannot_be_forged(self):
        self._add_stock(self.soft_out_location, 100.0)
        product = self.product.with_user(self.vendor_user).with_context(
            bypass_blocked_locations=True,
        )
        product.invalidate_recordset(["qty_available"])
        self.assertEqual(product.qty_available, 0.0)

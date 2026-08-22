from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from odoo.addons.stock.tests.common import TestStockCommon


@tagged("post_install", "-at_install")
class TestAuditFixesV2(TestStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.p_avail, cls.p_short = cls.ProductObj.create(
            [
                {"name": "Avail V2 A", "is_storable": True},
                {"name": "Avail V2 B", "is_storable": True},
            ]
        )

    def _out_picking(self, products, qty=5.0):
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.picking_type_out.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "move_ids": [
                    Command.create(
                        {
                            "product_id": p.id,
                            "product_uom_qty": qty,
                            "product_uom_id": p.uom_id.id,
                            "location_id": self.stock_location.id,
                            "location_dest_id": self.customer_location.id,
                        }
                    )
                    for p in products
                ],
            }
        )
        picking.action_confirm()
        return picking

    def test_cancelled_sibling_move_availability(self):
        self.env["stock.quant"]._update_available_quantity(
            self.p_avail, self.stock_location, 100
        )
        picking = self._out_picking(self.p_avail | self.p_short)
        picking.action_assign()
        move_short = picking.move_ids.filtered(lambda m: m.product_id == self.p_short)
        move_short._action_cancel()
        picking.invalidate_recordset()

        self.assertEqual(picking.products_availability_state, "available")
        self.assertEqual(picking.products_availability, "Available")
        matched = self.env["stock.picking"].search(
            [
                ("id", "=", picking.id),
                ("products_availability_state", "=", "late"),
            ]
        )
        self.assertFalse(matched, "cancel-only shortage must not match the late search")

    def test_done_sibling_move_availability(self):
        self.env["stock.quant"]._update_available_quantity(
            self.p_avail, self.stock_location, 100
        )
        self.env["stock.quant"]._update_available_quantity(
            self.p_short, self.stock_location, 100
        )
        picking = self._out_picking(self.p_avail | self.p_short)
        picking.action_assign()
        move_done = picking.move_ids.filtered(lambda m: m.product_id == self.p_short)
        move_done.picked = True
        move_done._action_done()
        picking.invalidate_recordset()

        self.assertNotEqual(
            picking.products_availability_state,
            "late",
            "a done sibling move must not report the picking as late",
        )

    def test_return_all_never_negative(self):
        self.env["stock.quant"]._update_available_quantity(
            self.p_avail, self.stock_location, 100
        )
        picking = self._out_picking(self.p_avail, qty=5.0)
        picking.action_assign()
        picking.move_ids.picked = True
        picking._action_done()

        wizard = (
            self.env["stock.return.picking"]
            .with_context(active_id=picking.id, active_model="stock.picking")
            .create({"picking_id": picking.id})
        )
        wizard.product_return_moves.quantity = 8.0
        return_action = wizard.action_create_returns()
        return_picking = self.env["stock.picking"].browse(return_action["res_id"])
        return_picking.move_ids.picked = True
        return_picking.move_ids.quantity = 8.0
        return_picking._action_done()

        wizard2 = (
            self.env["stock.return.picking"]
            .with_context(active_id=picking.id, active_model="stock.picking")
            .create({"picking_id": picking.id})
        )
        with self.assertRaises(UserError):
            wizard2.action_create_returns_all()
        for line in wizard2.product_return_moves:
            self.assertGreaterEqual(
                line.quantity, 0.0, "Return All must never propose a negative quantity"
            )
        negative_returns = self.env["stock.move"].search(
            [
                ("origin_returned_move_id", "in", picking.move_ids.ids),
                ("product_uom_qty", "<", 0),
            ]
        )
        self.assertFalse(
            negative_returns, "no negative-demand return move must be created"
        )

    def test_move_line_plain_user_read_only(self):
        user = self.env["res.users"].create(
            {
                "name": "Plain V2",
                "login": "plain_v2_audit",
                "group_ids": [Command.set([self.env.ref("base.group_user").id])],
            }
        )
        with self.assertRaises(AccessError):
            self.env["stock.move.line"].with_user(user).create(
                {
                    "product_id": self.p_avail.id,
                    "location_id": self.stock_location.id,
                    "location_dest_id": self.customer_location.id,
                    "quantity": 1,
                    "product_uom_id": self.p_avail.uom_id.id,
                    "company_id": self.env.company.id,
                }
            )

    def test_sn_recommendation_uses_child_of(self):
        Location = self.env["stock.location"]
        parent = Location.create({"name": "SN Parent", "usage": "internal"})
        child = Location.create(
            {"name": "SN Child", "usage": "internal", "location_id": parent.id}
        )
        other = Location.create({"name": "SN Other", "usage": "internal"})
        self.assertTrue(child._child_of(parent))
        self.assertTrue(parent._child_of(parent))
        self.assertFalse(child._child_of(other))
        self.assertFalse(parent._child_of(child))

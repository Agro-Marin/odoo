from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from odoo.addons.stock.tests.common import TestStockCommon


@tagged("post_install", "-at_install")
class TestAuditFixesV2(TestStockCommon):
    """Regression tests for the second stock audit batch.

    Each test pins one confirmed finding so a re-introduction fails loudly:
    cancelled/done sibling moves poisoning picking availability (and its
    search), the "Return All" negative-quantity floor, the move-line ACL
    tightening (plain internal users are read-only), and the serial-number
    source-location recommendation using proper ancestry (`_child_of`) instead
    of a `parent_path` substring match.
    """

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

    # ------------------------------------------------------------
    # availability: cancelled / done siblings must not poison the picking
    # ------------------------------------------------------------

    def test_cancelled_sibling_move_availability(self):
        """A picking whose only shortage is a *cancelled* move is Available."""
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
        # The search classifier must agree with the display.
        matched = self.env["stock.picking"].search(
            [
                ("id", "=", picking.id),
                ("products_availability_state", "=", "late"),
            ]
        )
        self.assertFalse(matched, "cancel-only shortage must not match the late search")

    def test_done_sibling_move_availability(self):
        """A *done* sibling move (forecast 0) must not flag the picking late."""
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

    # ------------------------------------------------------------
    # return wizard: never propose a negative return quantity
    # ------------------------------------------------------------

    def test_return_all_never_negative(self):
        """Over-returning then "Return All" floors the quantity at 0 instead of
        creating a negative-demand move (it raises a clean "nothing to return").
        """
        self.env["stock.quant"]._update_available_quantity(
            self.p_avail, self.stock_location, 100
        )
        picking = self._out_picking(self.p_avail, qty=5.0)
        picking.action_assign()
        picking.move_ids.picked = True
        picking._action_done()

        # Over-return: push the returned quantity above what was delivered so
        # the "already returned" total exceeds the 5 that went out.
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

        # "Return All" now floors to 0 for the fully-returned line. The wizard
        # must not build a negative-demand return: no return move with a
        # negative quantity may exist, and the flow raises "nothing to return".
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

    # ------------------------------------------------------------
    # security: plain internal users are read-only on stock.move.line
    # ------------------------------------------------------------

    def test_move_line_plain_user_read_only(self):
        """A base.group_user with no stock role cannot create move lines."""
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

    # ------------------------------------------------------------
    # serial recommendation: ancestry, not parent_path substring
    # ------------------------------------------------------------

    def test_sn_recommendation_uses_child_of(self):
        """`_child_of` must reject a substring `parent_path` false positive."""
        Location = self.env["stock.location"]
        parent = Location.create({"name": "SN Parent", "usage": "internal"})
        # A sibling subtree whose parent_path can contain the other's id as a
        # substring (e.g. ".../5/" inside ".../15/"). The exact ids are assigned
        # by the DB; `_child_of` must still only match true ancestry.
        child = Location.create(
            {"name": "SN Child", "usage": "internal", "location_id": parent.id}
        )
        other = Location.create({"name": "SN Other", "usage": "internal"})
        self.assertTrue(child._child_of(parent))
        self.assertTrue(parent._child_of(parent))
        self.assertFalse(child._child_of(other))
        self.assertFalse(parent._child_of(child))

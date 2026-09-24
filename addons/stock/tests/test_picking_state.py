from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from odoo.addons.stock.tests.common import PickingCase, TestStockCommon


@tagged("post_install", "-at_install")
class TestAvailabilityFollowsDisplayState(TestStockCommon):
    def test_availability_search_matches_display_state(self):
        in_stock = self.env["product.product"].create(
            {"name": "Avail In Stock", "is_storable": True},
        )
        shortage = self.env["product.product"].create(
            {"name": "Avail Short", "is_storable": True},
        )
        warehouse = self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)],
            limit=1,
        )
        self.env["stock.quant"]._update_available_quantity(
            in_stock,
            warehouse.lot_stock_id,
            quantity=10,
        )
        customers = self.env.ref("stock.stock_location_customers")
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": warehouse.out_type_id.id,
                "location_id": warehouse.lot_stock_id.id,
                "location_dest_id": customers.id,
                "move_ids": [
                    (
                        0,
                        0,
                        {
                            "product_id": product.id,
                            "product_uom_id": product.uom_id.id,
                            "product_uom_qty": 5,
                            "location_id": warehouse.lot_stock_id.id,
                            "location_dest_id": customers.id,
                        },
                    )
                    for product in (in_stock, shortage)
                ],
            },
        )
        picking.action_confirm()
        self.assertEqual(picking.products_availability_state, "late")

        Picking = self.env["stock.picking"]
        late = Picking.search([("products_availability_state", "=", "late")])
        self.assertIn(picking, late, "a shortage picking must be searchable as late")
        available = Picking.search(
            [("products_availability_state", "=", "available")],
        )
        self.assertNotIn(
            picking,
            available,
            "the clean sibling move must not leak the picking into 'available'",
        )
        self.assertIn(
            picking,
            Picking.search(
                [("products_availability_state", "in", ["late", "expected"])],
            ),
        )
        self.assertNotIn(
            picking,
            Picking.search(
                [("products_availability_state", "not in", ["late"])],
            ),
        )


@tagged("post_install", "-at_install")
class TestPickingAvailabilityEdgeCases(TestStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.p_avail, cls.p_short = cls.ProductObj.create(
            [
                {"name": "Avail V2 A", "is_storable": True},
                {"name": "Avail V2 B", "is_storable": True},
            ]
        )

    def _create_out_picking_with_moves(self, products, qty=5.0):
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
        picking = self._create_out_picking_with_moves(self.p_avail | self.p_short)
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
        picking = self._create_out_picking_with_moves(self.p_avail | self.p_short)
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
        picking = self._create_out_picking_with_moves(self.p_avail, qty=5.0)
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
        self.assertTrue(child._is_child_of(parent))
        self.assertTrue(parent._is_child_of(parent))
        self.assertFalse(child._is_child_of(other))
        self.assertFalse(parent._is_child_of(child))


class TestCancellationIsNotALatch(PickingCase):
    def test_a_cancelled_transfer_that_regains_a_line_is_draft_again(self):
        picking = self._picking()
        picking.action_confirm()
        picking.action_cancel()
        self.assertEqual(picking.state, "cancel")
        self.assertTrue(picking.is_cancelled)

        picking.move_ids.unlink()
        self.assertEqual(picking.state, "cancel")

        picking.write(
            {
                "move_ids": [
                    Command.create(
                        {"product_id": self.product.id, "product_uom_qty": 1.0},
                    ),
                ],
            },
        )
        picking.invalidate_recordset()
        self.assertEqual(picking.state, "draft")
        self.assertFalse(picking.is_cancelled)

    def test_emptying_an_uncancelled_transfer_leaves_it_draft(self):
        picking = self._picking()
        picking.action_confirm()
        picking.action_cancel()
        picking.move_ids.unlink()
        picking.write(
            {
                "move_ids": [
                    Command.create(
                        {"product_id": self.product.id, "product_uom_qty": 1.0},
                    ),
                ],
            },
        )
        picking.move_ids.unlink()
        picking.invalidate_recordset()
        self.assertEqual(picking.state, "draft")

    def test_confirming_a_cancelled_transfer_releases_the_flag(self):
        picking = self._picking()
        picking.action_confirm()
        picking.action_cancel()
        picking.write(
            {
                "move_ids": [
                    Command.create(
                        {"product_id": self.product.id, "product_uom_qty": 1.0},
                    ),
                ],
            },
        )
        picking.action_confirm()
        self.assertFalse(picking.is_cancelled)
        self.assertNotEqual(picking.state, "cancel")

    def test_a_transfer_cancelled_while_empty_still_reads_cancelled(self):
        picking = self.env["stock.picking"].create(
            {"picking_type_id": self.type_in.id},
        )
        picking.action_cancel()
        picking.invalidate_recordset()
        self.assertTrue(picking.is_cancelled)
        self.assertEqual(picking.state, "cancel")


class TestAvailabilitySearchMatchesTheField(PickingCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.stocked = cls.env["product.product"].create(
            {"name": "Audit stocked", "is_storable": True},
        )
        cls.starved = cls.env["product.product"].create(
            {"name": "Audit starved", "is_storable": True},
        )
        cls.service = cls.env["product.product"].create(
            {"name": "Audit consumable", "type": "consu", "is_storable": False},
        )
        cls.env["stock.quant"]._update_available_quantity(
            cls.stocked,
            cls.warehouse.lot_stock_id,
            500,
        )

    def _outgoing(self, products, quantity=1.0):
        return self.env["stock.picking"].create(
            {
                "picking_type_id": self.type_out.id,
                "move_ids": [
                    Command.create(
                        {"product_id": p.id, "product_uom_qty": quantity},
                    )
                    for p in products
                ],
            },
        )

    def test_the_search_agrees_with_the_field_on_every_state(self):
        pickings = self.env["stock.picking"].concat(
            self._outgoing(self.stocked),
            self._outgoing(self.starved, quantity=900.0),
            self._outgoing(self.service),
            self._outgoing(self.stocked + self.starved, quantity=900.0),
        )
        pickings.action_confirm()
        self.env.flush_all()
        self.env.invalidate_all()

        pickings_by_state = pickings.grouped("products_availability_state")
        for state in ("available", "expected", "late"):
            with self.subTest(state=state):
                by_field = pickings_by_state.get(state, pickings.browse())
                by_search = self.env["stock.picking"].search(
                    [
                        ("id", "in", pickings.ids),
                        ("products_availability_state", "in", [state]),
                    ],
                )
                self.assertEqual(
                    by_search,
                    by_field,
                    f"the search and the field disagree on {state!r}",
                )

    def test_a_transfer_of_only_consumables_is_available(self):
        picking = self._outgoing(self.service)
        picking.action_confirm()
        self.env.flush_all()
        self.env.invalidate_all()

        self.assertEqual(picking.products_availability_state, "available")
        self.assertIn(
            picking,
            self.env["stock.picking"].search(
                [
                    ("id", "=", picking.id),
                    ("products_availability_state", "in", ["available"]),
                ],
            ),
            "a transfer with no move that can decide availability is available,"
            " and the search must still return it",
        )

    def test_a_cancelled_line_does_not_decide_availability(self):
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.type_out.id,
                "move_ids": [
                    Command.create(
                        {"product_id": self.stocked.id, "product_uom_qty": 1.0},
                    ),
                    Command.create(
                        {"product_id": self.starved.id, "product_uom_qty": 900.0},
                    ),
                ],
            },
        )
        picking.action_confirm()
        self.assertEqual(
            picking.products_availability_state,
            "late",
            "the starved line must make it late while it is alive,"
            " or cancelling it proves nothing",
        )
        picking.move_ids.filtered(
            lambda m: m.product_id == self.starved,
        )._action_cancel()
        self.env.flush_all()
        self.env.invalidate_all()

        self.assertEqual(
            picking.products_availability_state,
            self.env["stock.picking"]
            .search([("id", "=", picking.id)])
            .products_availability_state,
        )
        self.assertNotIn(
            picking,
            self.env["stock.picking"].search(
                [
                    ("id", "=", picking.id),
                    ("products_availability_state", "in", ["late"]),
                ],
            ),
            "the cancelled shortage must not make the transfer late",
        )

    def test_the_deciding_domain_excludes_what_cannot_decide(self):
        picking = self.env["stock.picking"]
        domain = {
            leaf[0]: leaf[2]
            for leaf in picking._get_domain_availability_deciding_moves()
        }
        self.assertEqual(set(domain["state"]), {"done", "cancel"})
        self.assertTrue(domain["product_id.is_storable"])

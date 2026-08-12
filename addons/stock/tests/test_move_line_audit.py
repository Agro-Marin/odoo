from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.stock.tests.common import TestStockCommon


@tagged("post_install", "-at_install")
class TestMoveLineReservationSymmetry(TestStockCommon):
    """A move line reserves at its *own* `location_id`, so the bypass verdict must be
    taken there too. Deciding it on the move's location let a line whose source differed
    from its move's in usage class reserve without releasing, or release without
    reserving -- neither of which any existing test asserted.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Quant = cls.env["stock.quant"]
        cls.Move = cls.env["stock.move"]
        cls.MoveLine = cls.env["stock.move.line"]
        cls.inventory_loc = cls.env["stock.location"].search(
            [("usage", "=", "inventory"), ("company_id", "=", cls.env.company.id)],
            limit=1,
        )

    def _make_product(self, name):
        product = self.env["product.product"].create(
            {"name": name, "is_storable": True, "type": "consu"}
        )
        self.Quant._update_available_quantity(product, self.stock_location, 100.0)
        return product

    def _reserved(self, product, location):
        self.env.invalidate_all()
        return sum(
            self.Quant.search(
                [
                    ("product_id", "=", product.id),
                    ("location_id", "=", location.id),
                ]
            ).mapped("reserved_quantity")
        )

    def _make_line(self, product, move_source, line_source, qty=30.0):
        move = self.Move.create(
            {
                "product_id": product.id,
                "product_uom_qty": qty,
                "product_uom_id": product.uom_id.id,
                "location_id": move_source.id,
                "location_dest_id": self.stock_location.id,
                "company_id": self.env.company.id,
            }
        )
        move._action_confirm()
        move.move_line_ids.unlink()
        return self.MoveLine.create(
            {
                "move_id": move.id,
                "product_id": product.id,
                "product_uom_id": product.uom_id.id,
                "quantity": qty,
                "location_id": line_source.id,
                "location_dest_id": self.customer_location.id,
                "company_id": self.env.company.id,
            }
        )

    def test_create_and_unlink_are_symmetric_when_locations_agree(self):
        """Control: the reserve/release pair nets to zero and leaves others alone."""
        product = self._make_product("sym-control")
        victim = self.Move.create(
            {
                "product_id": product.id,
                "product_uom_qty": 40.0,
                "product_uom_id": product.uom_id.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "company_id": self.env.company.id,
            }
        )
        victim._action_confirm()
        victim._action_assign()
        self.assertEqual(self._reserved(product, self.stock_location), 40.0)

        line = self._make_line(product, self.stock_location, self.stock_location)
        self.assertEqual(self._reserved(product, self.stock_location), 70.0)
        line.unlink()
        self.assertEqual(self._reserved(product, self.stock_location), 40.0)

    def test_line_source_outside_the_move_source_does_not_steal(self):
        """A move sourced at a bypass location with a line sourced at real stock must
        still reserve on create, so its unlink releases its own reservation instead of
        eating a sibling's."""
        product = self._make_product("sym-steal")
        victim = self.Move.create(
            {
                "product_id": product.id,
                "product_uom_qty": 40.0,
                "product_uom_id": product.uom_id.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "company_id": self.env.company.id,
            }
        )
        victim._action_confirm()
        victim._action_assign()

        line = self._make_line(product, self.supplier_location, self.stock_location)
        self.assertEqual(
            self._reserved(product, self.stock_location),
            70.0,
            "create must reserve at the line's own location",
        )
        line.unlink()
        self.assertEqual(
            self._reserved(product, self.stock_location),
            40.0,
            "unlink must release only what this line reserved",
        )
        self.assertEqual(
            self.Quant._get_available_quantity(
                product, self.stock_location, strict=True
            ),
            60.0,
            "the victim's 40 must stay unavailable to anyone else",
        )

    def test_line_source_on_a_bypass_location_reserves_nothing(self):
        """The reverse pairing must not strand a reservation on a virtual location."""
        product = self._make_product("sym-phantom")
        line = self._make_line(product, self.stock_location, self.inventory_loc)
        self.assertFalse(
            self.Quant.search(
                [
                    ("product_id", "=", product.id),
                    ("location_id", "=", self.inventory_loc.id),
                ]
            ),
            "a bypass location must not receive a reservation on create",
        )
        line.unlink()
        self.assertFalse(
            self.Quant.search(
                [
                    ("product_id", "=", product.id),
                    ("location_id", "=", self.inventory_loc.id),
                    ("reserved_quantity", "!=", 0),
                ]
            ),
            "and must not be left holding a phantom one after unlink",
        )


@tagged("post_install", "-at_install")
class TestMoveLineUntrackedCompensation(TestStockCommon):
    """Removing more of a lot than exists is compensated from untracked stock at the
    same location. The repair is sized by the on-hand shortfall, not by the amount moved
    and not by availability (which nets off reserved quantity).
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Quant = cls.env["stock.quant"]
        cls.MoveLine = cls.env["stock.move.line"]

    def _tracked_product(self, name):
        return self.env["product.product"].create(
            {"name": name, "is_storable": True, "type": "consu", "tracking": "lot"}
        )

    def _quantities(self, product, lot):
        self.env.invalidate_all()
        quants = self.Quant.search(
            [
                ("product_id", "=", product.id),
                ("location_id", "=", self.stock_location.id),
            ]
        )
        tracked = sum(quants.filtered(lambda q: q.lot_id == lot).mapped("quantity"))
        untracked = sum(quants.filtered(lambda q: not q.lot_id).mapped("quantity"))
        return tracked, untracked

    def test_compensation_covers_the_shortfall_not_the_whole_move(self):
        """Shipping 20 of a lot holding 5 must leave the lot at 0 and take 15 from
        untracked stock -- not leave the lot at 5 and take 20."""
        product = self._tracked_product("comp-shortfall")
        lot = self.env["stock.lot"].create(
            {
                "name": "COMP-1",
                "product_id": product.id,
                "company_id": self.env.company.id,
            }
        )
        self.Quant._update_available_quantity(
            product, self.stock_location, 5.0, lot_id=lot
        )
        self.Quant._update_available_quantity(product, self.stock_location, 50.0)

        move = self.env["stock.move"].create(
            {
                "product_id": product.id,
                "product_uom_qty": 20.0,
                "product_uom_id": product.uom_id.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "company_id": self.env.company.id,
            }
        )
        move._action_confirm()
        move._action_assign()
        move.move_line_ids.unlink()
        self.MoveLine.create(
            {
                "move_id": move.id,
                "product_id": product.id,
                "product_uom_id": product.uom_id.id,
                "quantity": 20.0,
                "lot_id": lot.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "company_id": self.env.company.id,
            }
        )
        move.picked = True
        move._action_done()

        tracked, untracked = self._quantities(product, lot)
        self.assertEqual(tracked, 0.0, "the lot's own stock must be consumed first")
        self.assertEqual(untracked, 35.0, "only the 15 short may come from untracked")

    def test_a_fully_reserved_lot_is_not_compensated(self):
        """A lot quant whose on-hand is positive must not draw on untracked stock just
        because all of it is reserved (availability negative, on-hand not)."""
        product = self._tracked_product("comp-reserved")
        lot = self.env["stock.lot"].create(
            {
                "name": "COMP-2",
                "product_id": product.id,
                "company_id": self.env.company.id,
            }
        )
        self.Quant._update_available_quantity(
            product, self.stock_location, 50.0, lot_id=lot
        )
        self.Quant._update_available_quantity(product, self.stock_location, 100.0)
        self.Quant._update_reserved_quantity(
            product, self.stock_location, 50.0, lot_id=lot
        )

        line = self.MoveLine.new(
            {
                "product_id": product.id,
                "product_uom_id": product.uom_id.id,
                "lot_id": lot.id,
                "location_id": self.stock_location.id,
                "company_id": self.env.company.id,
            }
        )
        line._synchronize_quant(-1.0, self.stock_location, lot=lot)

        tracked, untracked = self._quantities(product, lot)
        self.assertEqual(tracked, 49.0, "the removal must land on the lot itself")
        self.assertEqual(untracked, 100.0, "untracked stock must be untouched")

    def test_compensation_is_capped_by_available_untracked_stock(self):
        """When untracked stock cannot cover the shortfall, take all of it and leave the
        remainder negative."""
        product = self._tracked_product("comp-capped")
        lot = self.env["stock.lot"].create(
            {
                "name": "COMP-3",
                "product_id": product.id,
                "company_id": self.env.company.id,
            }
        )
        self.Quant._update_available_quantity(
            product, self.stock_location, 5.0, lot_id=lot
        )
        self.Quant._update_available_quantity(product, self.stock_location, 8.0)

        line = self.MoveLine.new(
            {
                "product_id": product.id,
                "product_uom_id": product.uom_id.id,
                "lot_id": lot.id,
                "location_id": self.stock_location.id,
                "company_id": self.env.company.id,
            }
        )
        line._synchronize_quant(-20.0, self.stock_location, lot=lot)

        tracked, untracked = self._quantities(product, lot)
        self.assertEqual(tracked, -7.0)
        self.assertEqual(untracked, 0.0)


@tagged("post_install", "-at_install")
class TestMoveLineWriteGuards(TestStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Quant = cls.env["stock.quant"]

    def _assigned_move(self, product, qty=5.0):
        move = self.env["stock.move"].create(
            {
                "product_id": product.id,
                "product_uom_qty": qty,
                "product_uom_id": product.uom_id.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "company_id": self.env.company.id,
            }
        )
        move._action_confirm()
        move._action_assign()
        return move

    def _stocked_product(self, name):
        product = self.env["product.product"].create(
            {"name": name, "is_storable": True, "type": "consu"}
        )
        self.Quant._update_available_quantity(product, self.stock_location, 50.0)
        return product

    def test_quant_id_cannot_change_the_product_outside_draft(self):
        """`quant_id` expands into `product_id`, so it must face the same guard a direct
        `product_id` write does."""
        product_a = self._stocked_product("guard-a")
        product_b = self._stocked_product("guard-b")
        quant_b = self.Quant.search(
            [
                ("product_id", "=", product_b.id),
                ("location_id", "=", self.stock_location.id),
            ],
            limit=1,
        )
        line = self._assigned_move(product_a).move_line_ids[:1]
        with self.assertRaises(UserError):
            line.write({"quant_id": quant_b.id})

    def test_quant_id_of_the_same_product_still_writes(self):
        """The ordinary 'Pick From' flow must keep working."""
        product = self._stocked_product("guard-same")
        quant = self.Quant.search(
            [
                ("product_id", "=", product.id),
                ("location_id", "=", self.stock_location.id),
            ],
            limit=1,
        )
        line = self._assigned_move(product).move_line_ids[:1]
        line.write({"quant_id": quant.id})
        self.assertEqual(line.product_id, product)

    def test_quant_id_may_fill_an_empty_product(self):
        """A blank detail row picking its product from a quant is not a product change."""
        product = self._stocked_product("guard-empty")
        move = self._assigned_move(product)
        move.move_line_ids.unlink()
        quant = self.Quant.search(
            [
                ("product_id", "=", product.id),
                ("location_id", "=", self.stock_location.id),
            ],
            limit=1,
        )
        line = self.env["stock.move.line"].create({"move_id": move.id})
        line.quant_id = quant
        self.assertEqual(line.product_id, product)

    def test_write_does_not_mutate_the_caller_vals(self):
        """`_copy_quant_info` must not leak the first line's characteristics into a vals
        dict the caller goes on to reuse."""
        product = self._stocked_product("guard-vals")
        quant = self.Quant.search(
            [
                ("product_id", "=", product.id),
                ("location_id", "=", self.stock_location.id),
            ],
            limit=1,
        )
        line = self._assigned_move(product).move_line_ids[:1]
        vals = {"quant_id": quant.id}
        line.write(vals)
        self.assertEqual(vals, {"quant_id": quant.id})


@tagged("post_install", "-at_install")
class TestMoveLinePutInPack(TestStockCommon):
    def test_put_in_pack_without_a_label_format(self):
        """`package_label_to_print` is not required, so auto-print with it cleared must
        not raise UnboundLocalError."""
        picking_type = self.env["stock.picking.type"].search(
            [("code", "=", "outgoing"), ("company_id", "=", self.env.company.id)],
            limit=1,
        )
        picking_type.write(
            {"auto_print_package_label": True, "package_label_to_print": False}
        )
        product = self.env["product.product"].create(
            {"name": "pack-nolabel", "is_storable": True, "type": "consu"}
        )
        self.env["stock.quant"]._update_available_quantity(
            product, self.stock_location, 10.0
        )
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": picking_type.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "move_ids": [
                    (
                        0,
                        0,
                        {
                            "product_id": product.id,
                            "product_uom_qty": 1.0,
                            "product_uom_id": product.uom_id.id,
                            "location_id": self.stock_location.id,
                            "location_dest_id": self.customer_location.id,
                        },
                    )
                ],
            }
        )
        picking.action_confirm()
        picking.action_assign()
        package = self.env["stock.package"].create({"name": "PACK-NOLABEL"})
        self.assertEqual(
            picking.move_line_ids[:1]._post_put_in_pack_hook(package), package
        )

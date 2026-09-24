from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from odoo.addons.stock.tests.common import (
    LocationCase,
    TestMoveLineCommon,
    TestStockCommon,
)


class MoveLineCase(TestStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.stock_user = cls.env["res.users"].create(
            {
                "name": "Audit Stock User",
                "login": "audit_stock_user_20260831",
                "group_ids": [
                    (
                        6,
                        0,
                        [
                            cls.env.ref("base.group_user").id,
                            cls.env.ref("stock.group_stock_user").id,
                        ],
                    )
                ],
            }
        )
        cls.warehouse = cls.env["stock.warehouse"].search([], limit=1)
        cls.src = cls.warehouse.lot_stock_id
        cls.customer = cls.env.ref("stock.stock_location_customers")
        cls.supplier = cls.env.ref("stock.stock_location_suppliers")

    def test_the_fixture_is_not_a_superuser(self):
        self.assertFalse(self.env(user=self.stock_user).su)
        self.assertTrue(self.stock_user.has_group("stock.group_stock_user"))

    def _product(self, name, tracking="none"):
        return self.env["product.product"].create(
            {
                "name": name,
                "is_storable": True,
                "type": "consu",
                "tracking": tracking,
            }
        )

    def _stock(self, product, location, qty, lot=None):
        return self.env["stock.quant"].create(
            {
                "product_id": product.id,
                "location_id": location.id,
                "lot_id": lot.id if lot else False,
                "quantity": qty,
            }
        )

    def _outgoing(self, product, qty, user=None):
        env = self.env(user=user) if user else self.env
        picking = env["stock.picking"].create(
            {
                "picking_type_id": self.warehouse.out_type_id.id,
                "location_id": self.src.id,
                "location_dest_id": self.customer.id,
            }
        )
        env["stock.move"].create(
            {
                "picking_id": picking.id,
                "product_id": product.id,
                "product_uom_qty": qty,
                "location_id": self.src.id,
                "location_dest_id": self.customer.id,
            }
        )
        picking.action_confirm()
        picking.action_assign()
        return picking


@tagged("post_install", "-at_install")
class TestWriteSurvivesAFreedSibling(MoveLineCase):
    def _done_line_and_open_line(self, open_qty, on_hand=10.0):
        product = self._product("Freed Sibling")
        self._stock(product, self.src, on_hand)
        open_picking = self._outgoing(product, open_qty)
        open_line = open_picking.move_line_ids
        done_picking = self._outgoing(product, 1.0)
        done_picking.move_line_ids.quantity = 1.0
        done_picking.move_ids.picked = True
        done_picking.button_validate()
        return done_picking.move_ids.move_line_ids, open_line

    def test_a_batch_mixing_a_done_and_an_open_line_does_not_raise_missing(self):
        done_line, open_line = self._done_line_and_open_line(2.0)
        batch = done_line | open_line
        self.assertEqual(sorted(batch.mapped("state")), ["assigned", "done"])

        batch.write({"quantity": 10.0})

        self.assertTrue(done_line.exists(), "the written done line must survive")

    def test_the_freed_sibling_really_is_unlinked(self):
        done_line, open_line = self._done_line_and_open_line(2.0)
        (done_line | open_line).write({"quantity": 10.0})
        self.assertFalse(
            open_line.exists(),
            "the competing reservation should have been freed; if it survives, "
            "this fixture no longer exercises the read-after-delete path",
        )

    def test_an_ordinary_batch_write_is_untouched(self):
        product = self._product("Ordinary Batch")
        self._stock(product, self.src, 50.0)
        picking = self._outgoing(product, 5.0)
        lines = picking.move_line_ids
        lines.write({"quantity": 3.0})
        self.assertTrue(lines.exists())
        self.assertEqual(lines.quantity, 3.0)


@tagged("post_install", "-at_install")
class TestArchivedLotsAreNamed(MoveLineCase):
    def _receipt_with_lot_name(self, product, lot_name, qty=3.0):
        picking_type = self.warehouse.in_type_id
        picking_type.write({"use_create_lots": True, "use_existing_lots": True})
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": picking_type.id,
                "location_id": self.supplier.id,
                "location_dest_id": self.src.id,
            }
        )
        move = self.env["stock.move"].create(
            {
                "picking_id": picking.id,
                "product_id": product.id,
                "product_uom_qty": qty,
                "location_id": self.supplier.id,
                "location_dest_id": self.src.id,
            }
        )
        picking.action_confirm()
        move.move_line_ids.write({"quantity": qty, "lot_name": lot_name})
        move.picked = True
        return picking

    def test_an_archived_lot_is_named_in_the_error(self):
        product = self._product("Archived Lot Product", tracking="lot")
        lot = self.env["stock.lot"].create(
            {
                "name": "AUDIT-ARCHIVED",
                "product_id": product.id,
                "company_id": self.env.company.id,
            }
        )
        lot.active = False
        picking = self._receipt_with_lot_name(product, "AUDIT-ARCHIVED")

        with self.assertRaises(UserError) as caught:
            picking.button_validate()

        message = str(caught.exception)
        self.assertIn("AUDIT-ARCHIVED", message)
        self.assertIn("archived", message.lower())
        self.assertNotIn(
            "unique",
            message.lower(),
            "the user did not create a duplicate; they named an archived lot",
        )

    def test_a_fresh_lot_name_still_creates_the_lot(self):
        product = self._product("Fresh Lot Product", tracking="lot")
        picking = self._receipt_with_lot_name(product, "AUDIT-FRESH")

        picking.button_validate()

        lot = self.env["stock.lot"].search(
            [("product_id", "=", product.id), ("name", "=", "AUDIT-FRESH")]
        )
        self.assertEqual(len(lot), 1)
        self.assertTrue(lot.active)

    def test_an_active_lot_of_the_same_name_is_reused_not_recreated(self):
        product = self._product("Active Lot Product", tracking="lot")
        lot = self.env["stock.lot"].create(
            {
                "name": "AUDIT-ACTIVE",
                "product_id": product.id,
                "company_id": self.env.company.id,
            }
        )
        picking = self._receipt_with_lot_name(product, "AUDIT-ACTIVE")

        picking.button_validate()

        self.assertEqual(picking.move_line_ids.lot_id, lot)


@tagged("post_install", "-at_install")
class TestSerialOnchangeDoesNotCollideWithItself(MoveLineCase):
    def _serial_receipt(self):
        product = self._product("Serial Product", tracking="serial")
        picking_type = self.warehouse.in_type_id
        picking_type.write({"use_create_lots": True, "use_existing_lots": True})
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": picking_type.id,
                "location_id": self.supplier.id,
                "location_dest_id": self.src.id,
            }
        )
        move = self.env["stock.move"].create(
            {
                "picking_id": picking.id,
                "product_id": product.id,
                "product_uom_qty": 1.0,
                "location_id": self.supplier.id,
                "location_dest_id": self.src.id,
            }
        )
        picking.action_confirm()
        line = move.move_line_ids
        line.write({"quantity": 1.0, "lot_name": "SN-1"})
        return picking, move, line

    def _warning_for(self, line, move, picking, serial):
        values = {
            "id": line.id,
            "product_id": line.product_id.id,
            "quantity": 1.0,
            "picking_id": picking.id,
            "move_id": move.id,
            "lot_id": False,
            "lot_name": serial,
        }
        spec = dict.fromkeys(
            ["lot_name", "lot_id", "product_id", "quantity", "picking_id", "move_id"],
            "1",
        )
        result = line.onchange(values, ["lot_name"], spec)
        return (result.get("warning") or {}).get("message")

    def test_re_entering_a_lines_own_serial_does_not_warn(self):
        picking, move, line = self._serial_receipt()
        self.assertIsNone(self._warning_for(line, move, picking, "SN-1"))

    def test_a_genuinely_new_serial_does_not_warn(self):
        picking, move, line = self._serial_receipt()
        self.assertIsNone(self._warning_for(line, move, picking, "SN-9"))

    def test_a_real_duplicate_across_two_lines_still_warns(self):
        picking, move, line = self._serial_receipt()
        second = self.env["stock.move.line"].create(
            {
                "move_id": move.id,
                "picking_id": picking.id,
                "product_id": line.product_id.id,
                "product_uom_id": line.product_uom_id.id,
                "quantity": 1.0,
                "lot_name": "SN-2",
                "location_id": self.supplier.id,
                "location_dest_id": self.src.id,
            }
        )
        warning = self._warning_for(second, move, picking, "SN-1")
        self.assertIsNotNone(warning)
        self.assertIn("same serial number twice", warning)


@tagged("post_install", "-at_install")
class TestBoundLineProductGuard(MoveLineCase):
    def test_changing_a_bound_lines_product_is_refused(self):
        product = self._product("Bound Product")
        other = self._product("Other Product")
        self._stock(product, self.src, 10.0)
        line = self._outgoing(product, 2.0).move_line_ids
        with self.assertRaises(UserError):
            line.with_user(self.stock_user).write({"product_id": other.id})

    def test_a_supplied_draft_state_does_not_lift_the_refusal(self):
        product = self._product("Bound Product Two")
        other = self._product("Other Product Two")
        self._stock(product, self.src, 10.0)
        line = self._outgoing(product, 2.0).move_line_ids
        with self.assertRaises(UserError):
            line.with_user(self.stock_user).write(
                {"product_id": other.id, "state": "draft"}
            )

    def test_writing_the_same_product_still_succeeds(self):
        product = self._product("Same Product")
        self._stock(product, self.src, 10.0)
        line = self._outgoing(product, 2.0).move_line_ids
        line.with_user(self.stock_user).write({"product_id": product.id})
        self.assertEqual(line.product_id, product)


@tagged("post_install", "-at_install")
class TestTheProductGuardReadsTheStoredState(LocationCase):
    def setUp(self):
        super().setUp()
        self.plain_user = self.env["res.users"].create(
            {
                "name": "Plain Stock User",
                "login": "hardening_plain_stock_user",
                "group_ids": [
                    (
                        6,
                        0,
                        [
                            self.env.ref("base.group_user").id,
                            self.env.ref("stock.group_stock_user").id,
                            self.env.ref("stock.group_stock_multi_locations").id,
                        ],
                    ),
                ],
            },
        )
        self.first = self._create_product("Guard Product One")
        self.second = self._create_product("Guard Product Two")

    def _moveless_line(self):
        line = (
            self.env["stock.move.line"]
            .with_user(self.plain_user)
            .create(
                {
                    "product_id": self.first.id,
                    "product_uom_id": self.first.uom_id.id,
                    "quantity": 1,
                    "location_id": self.stock_location.id,
                    "location_dest_id": self.stock_location.id,
                    "company_id": self.env.company.id,
                },
            )
        )
        self.env.flush_all()
        self.assertFalse(line.move_id, "the exposure is move-less lines only")
        self.assertFalse(line.state, "a move-less line has no stored state")
        return line

    def test_changing_the_product_is_refused(self):
        with self.assertRaises(UserError):
            self._moveless_line().write({"product_id": self.second.id})

    def test_supplying_a_draft_state_does_not_lift_the_refusal(self):
        with self.assertRaises(UserError):
            self._moveless_line().write(
                {"product_id": self.second.id, "state": "draft"},
            )

    def test_a_move_bound_line_is_refused_with_or_without_a_supplied_state(self):
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.env.ref("stock.picking_type_in").id,
                "location_id": self.env.ref("stock.stock_location_suppliers").id,
                "location_dest_id": self.stock_location.id,
            },
        )
        move = self.env["stock.move"].create(
            {
                "picking_id": picking.id,
                "product_id": self.first.id,
                "product_uom_qty": 1,
                "location_id": self.env.ref("stock.stock_location_suppliers").id,
                "location_dest_id": self.stock_location.id,
            },
        )
        picking.action_confirm()
        line = self.env["stock.move.line"].create(
            {
                "move_id": move.id,
                "product_id": self.first.id,
                "product_uom_id": self.first.uom_id.id,
                "quantity": 1,
                "location_dest_id": self.stock_location.id,
            },
        )
        for vals in (
            {"product_id": self.second.id},
            {"product_id": self.second.id, "state": "draft"},
        ):
            with self.assertRaises(UserError):
                line.write(vals)

    def test_writing_the_same_product_is_still_allowed(self):
        line = self._moveless_line()
        line.write({"product_id": self.first.id, "quantity": 2})
        self.assertEqual(line.quantity, 2)


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


class TestUnitFollowsProduct(TestMoveLineCommon):
    def _draft_line(self, product):
        picking = self._delivery(product, 5, confirm=False)
        line = self.MoveLine.create(
            {
                "move_id": picking.move_ids.id,
                "picking_id": picking.id,
                "product_id": product.id,
                "quantity": 0,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )
        self.env.flush_all()
        self.assertEqual(line.state, "draft")
        return line

    def test_a_move_owns_its_lines_product_even_in_draft(self):
        in_units = self._product("owned-units", uom=self.uom_unit)
        in_kg = self._product("owned-kg", uom=self.uom_kg)
        line = self._draft_line(in_units)

        with self.assertRaises(UserError):
            line.write({"product_id": in_kg.id})

        self.env.invalidate_all()
        self.assertEqual(line.product_id, in_units)
        self.assertEqual(line.product_uom_id, self.uom_unit)

    def test_the_pick_from_back_door_is_closed_too(self):
        in_units = self._product("quant-units", uom=self.uom_unit)
        other = self._product("quant-other", uom=self.uom_unit)
        self._stock(other, 5)
        line = self._draft_line(in_units)
        quant = self.Quant._gather(other, self.stock_location)

        with self.assertRaises(UserError):
            line.write({"quant_id": quant.id})

    def test_a_line_without_a_product_keeps_the_units_it_was_given(self):
        product = self._product("no-product-yet")
        picking = self._delivery(product, 5, confirm=False)
        line = self.MoveLine.new(
            {
                "picking_id": picking.id,
                "product_uom_id": self.uom_dozen.id,
                "quantity": 0,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )
        self.assertFalse(line.product_id)
        self.assertEqual(line.product_uom_id, self.uom_dozen)


class TestPickingTypeDerivation(TestMoveLineCommon):
    def test_a_line_reads_the_operation_type_of_its_move(self):
        product = self._product("no-picking", tracking="lot")
        move = self.env["stock.move"].create(
            {
                "product_id": product.id,
                "product_uom_qty": 5,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_type_id": self.picking_type_out.id,
            }
        )
        move._action_confirm()
        line = self.MoveLine.create(
            {
                "move_id": move.id,
                "product_id": product.id,
                "quantity": 1,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )
        self.env.flush_all()
        self.assertFalse(line.picking_id)
        self.assertEqual(line.picking_type_id, self.picking_type_out)
        self.assertEqual(line.picking_code, self.picking_type_out.code)
        self.assertEqual(
            line.picking_type_use_existing_lots,
            self.picking_type_out.use_existing_lots,
        )
        self.assertIn(
            line,
            self.MoveLine.search(
                [
                    ("id", "=", line.id),
                    ("picking_type_id", "=", self.picking_type_out.id),
                ]
            ),
            "_search_picking_type_id must find a line whose type comes from its move",
        )

    def test_the_picking_still_wins_over_the_move(self):
        product = self._product("picking-wins")
        self._stock(product, 10)
        picking = self._delivery(product, 5, assign=True)
        line = picking.move_ids.move_line_ids
        self.assertEqual(line.picking_type_id, picking.picking_type_id)

    def test_changing_a_pickings_operation_type_reaches_its_lines(self):
        product = self._product("type-change", tracking="lot")
        lot = self.env["stock.lot"].create(
            {"name": "TYPE-CHANGE-1", "product_id": product.id}
        )
        self._stock(product, 10, lot=lot)
        other_type = self.picking_type_out.copy(
            {
                "name": "Delivery Orders (lots)",
                "sequence_code": "OUTLOT",
                "use_create_lots": not self.picking_type_out.use_create_lots,
            }
        )
        picking = self._delivery(product, 5, assign=True)
        line = picking.move_ids.move_line_ids
        self.assertEqual(
            line.picking_type_use_create_lots, self.picking_type_out.use_create_lots
        )

        picking.picking_type_id = other_type
        self.env.flush_all()

        self.assertEqual(line.picking_type_id, other_type)
        self.assertEqual(
            line.picking_type_use_create_lots,
            other_type.use_create_lots,
            "no invalidate_all: the dependency must carry the change itself",
        )


class TestSerialDuplicates(TestMoveLineCommon):
    def _receipt_lines(self, product, count):
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.picking_type_in.id,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
                "move_ids": [
                    Command.create(
                        {
                            "product_id": product.id,
                            "product_uom_qty": count,
                            "location_id": self.supplier_location.id,
                            "location_dest_id": self.stock_location.id,
                        }
                    )
                ],
            }
        )
        picking.action_confirm()
        picking.move_ids.move_line_ids.unlink()
        self.env.flush_all()
        return picking

    def test_a_serial_held_as_a_name_collides_with_one_held_as_a_lot(self):
        product = self._product("serial-mixed", tracking="serial")
        lot = self.env["stock.lot"].create(
            {"name": "SN-MIXED-1", "product_id": product.id}
        )
        self._stock(product, 1, lot=lot)
        picking = self._receipt_lines(product, 2)

        self.MoveLine.create(
            {
                "move_id": picking.move_ids.id,
                "picking_id": picking.id,
                "product_id": product.id,
                "quantity": 1,
                "lot_name": lot.name,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
            }
        )
        self.env.flush_all()

        edited = self.MoveLine.new(
            {
                "move_id": picking.move_ids.id,
                "picking_id": picking.id,
                "product_id": product.id,
                "quantity": 1,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
            }
        )
        edited.lot_id = lot
        result = edited._onchange_serial_number()
        self.assertIn(
            "same serial number twice",
            (result or {}).get("warning", {}).get("message", ""),
            "sibling holds the serial as lot_name, this line as lot_id",
        )

    def test_a_line_carrying_both_still_gets_the_location_check(self):
        product = self._product("serial-both", tracking="serial")
        lot = self.env["stock.lot"].create(
            {"name": "SN-BOTH-1", "product_id": product.id}
        )
        self._stock(product, 1, lot=lot)
        picking = self._receipt_lines(product, 1)
        elsewhere = self.env["stock.location"].create(
            {
                "name": "elsewhere",
                "location_id": self.stock_location.id,
                "usage": "internal",
            }
        )

        def warning_for(**extra):
            line = self.MoveLine.new(
                {
                    "move_id": picking.move_ids.id,
                    "picking_id": picking.id,
                    "product_id": product.id,
                    "quantity": 1,
                    "location_id": elsewhere.id,
                    "location_dest_id": self.stock_location.id,
                }
            )
            for field, value in extra.items():
                line[field] = value
            return (line._onchange_serial_number() or {}).get("warning")

        self.assertEqual(
            bool(warning_for(lot_id=lot, lot_name=lot.name)),
            bool(warning_for(lot_id=lot)),
            "carrying the name as well must not silence the location check",
        )

    def test_two_lines_claiming_one_serial_are_named_in_the_error(self):
        product = self._product("serial-dup", tracking="serial")
        picking = self._receipt_lines(product, 2)
        lines = self.MoveLine.create(
            [
                {
                    "move_id": picking.move_ids.id,
                    "picking_id": picking.id,
                    "product_id": product.id,
                    "quantity": 1,
                    "lot_name": "SN-DUP-9",
                    "location_id": self.supplier_location.id,
                    "location_dest_id": self.stock_location.id,
                }
            ]
            * 2
        )
        with self.assertRaises(ValidationError) as caught:
            lines._create_production_lots()
        self.assertIn("SN-DUP-9", str(caught.exception))

    def test_one_lot_may_be_shared_by_several_lines(self):
        product = self._product("lot-shared", tracking="lot")
        picking = self._receipt_lines(product, 4)
        lines = self.MoveLine.create(
            [
                {
                    "move_id": picking.move_ids.id,
                    "picking_id": picking.id,
                    "product_id": product.id,
                    "quantity": 2,
                    "lot_name": "LOT-SHARED",
                    "location_id": self.supplier_location.id,
                    "location_dest_id": self.stock_location.id,
                }
            ]
            * 2
        )
        lines._create_production_lots()
        self.env.flush_all()
        self.assertEqual(len(lines.lot_id), 1)
        self.assertEqual(lines.lot_id.name, "LOT-SHARED")

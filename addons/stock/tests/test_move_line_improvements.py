from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tools import OrderedSet

from odoo.addons.stock.tests.common import TestStockCommon


@tagged("post_install", "-at_install")
class TestMoveLineCommon(TestStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.MoveLine = cls.env["stock.move.line"]
        cls.Quant = cls.env["stock.quant"]
        cls.uom_unit = cls.env.ref("uom.product_uom_unit")
        cls.uom_dozen = cls.env.ref("uom.product_uom_dozen")
        cls.uom_kg = cls.env.ref("uom.product_uom_kgm")

    def _product(self, name, tracking="none", uom=None, uoms=None):
        vals = {"name": name, "is_storable": True, "tracking": tracking}
        if uom:
            vals["uom_id"] = uom.id
        if uoms:
            vals["uom_ids"] = [Command.set([u.id for u in uoms])]
        return self.env["product.product"].create(vals)

    def _stock(self, product, qty, lot=None, location=None):
        self.Quant._update_available_quantity(
            product, location or self.stock_location, qty, lot_id=lot
        )
        self.env.flush_all()

    def _delivery(self, product, qty, confirm=True, assign=False):
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.picking_type_out.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "move_ids": [
                    Command.create(
                        {
                            "product_id": product.id,
                            "product_uom_qty": qty,
                            "location_id": self.stock_location.id,
                            "location_dest_id": self.customer_location.id,
                        }
                    )
                ],
            }
        )
        if confirm:
            picking.action_confirm()
        if assign:
            picking.action_assign()
        return picking

    def _lines(self, picking, count, qty, lots=None):
        picking.move_ids.move_line_ids.unlink()
        self.env.flush_all()
        move = picking.move_ids
        vals = []
        for index in range(count):
            line = {
                "move_id": move.id,
                "picking_id": picking.id,
                "product_id": move.product_id.id,
                "quantity": qty,
                "location_id": move.location_id.id,
                "location_dest_id": move.location_dest_id.id,
            }
            if lots:
                line["lot_id"] = lots[index % len(lots)].id
            vals.append(line)
        lines = self.MoveLine.create(vals)
        self.env.flush_all()
        return lines


class TestUnlinkOrdering(TestMoveLineCommon):
    def test_a_refused_unlink_leaves_every_reservation_intact(self):
        product = self._product("unlink-order")
        self._stock(product, 100)

        done_picking = self._delivery(product, 4, assign=True)
        done_picking.move_ids.picked = True
        done_picking.button_validate()
        self.env.flush_all()

        open_picking = self._delivery(product, 6, assign=True)
        self.env.flush_all()
        open_line = open_picking.move_ids.move_line_ids
        done_line = done_picking.move_ids.move_line_ids
        self.assertEqual(open_line.state, "assigned")
        self.assertEqual(done_line.state, "done")

        quant = self.Quant._gather(product, self.stock_location)
        self.assertEqual(quant.reserved_quantity, 6.0)

        with self.assertRaises(UserError):
            (open_line | done_line).unlink()

        self.env.invalidate_all()
        self.assertTrue(open_line.exists(), "the open line was not deleted")
        self.assertEqual(
            self.Quant._gather(product, self.stock_location).reserved_quantity,
            6.0,
            "a refused unlink must not have released the surviving line's reservation",
        )


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


class TestResyncReservationCharacterisation(TestMoveLineCommon):
    def _quant_state(self, product):
        self.env.invalidate_all()
        return sorted(
            (
                quant.location_id.id,
                quant.lot_id.id,
                quant.package_id.id,
                quant.owner_id.id,
                round(quant.quantity, 4),
                round(quant.reserved_quantity, 4),
            )
            for quant in self.Quant.search([("product_id", "=", product.id)])
        )

    def test_lowering_one_lines_quantity(self):
        product = self._product("resync-1")
        self._stock(product, 100)
        lines = self._lines(self._delivery(product, 10), 1, 5)
        lines.write({"quantity": 3})
        self.assertEqual(
            self._quant_state(product),
            [(self.stock_location.id, False, False, False, 100.0, 3.0)],
        )

    def test_raising_one_lines_quantity(self):
        product = self._product("resync-2")
        self._stock(product, 100)
        lines = self._lines(self._delivery(product, 10), 1, 5)
        lines.write({"quantity": 9})
        self.assertEqual(
            self._quant_state(product),
            [(self.stock_location.id, False, False, False, 100.0, 9.0)],
        )

    def test_twenty_lines_sharing_one_characteristics_tuple(self):
        product = self._product("resync-3")
        self._stock(product, 1000)
        lines = self._lines(self._delivery(product, 200), 20, 5)
        lines.write({"quantity": 3})
        self.assertEqual(
            self._quant_state(product),
            [(self.stock_location.id, False, False, False, 1000.0, 60.0)],
        )

    def test_twenty_lines_dropping_to_zero(self):
        product = self._product("resync-4")
        self._stock(product, 1000)
        lines = self._lines(self._delivery(product, 200), 20, 5)
        lines.write({"quantity": 0})
        self.assertEqual(
            self._quant_state(product),
            [(self.stock_location.id, False, False, False, 1000.0, 0.0)],
        )

    def test_ten_lines_over_ten_lots_share_no_tuple(self):
        product = self._product("resync-5", tracking="lot")
        lots = self.env["stock.lot"].create(
            [{"name": f"RESYNC-L{i}", "product_id": product.id} for i in range(10)]
        )
        for lot in lots:
            self._stock(product, 20, lot=lot)
        lines = self._lines(self._delivery(product, 50), 10, 5, lots=lots)
        lines.write({"quantity": 2})
        self.assertEqual(
            self._quant_state(product),
            sorted(
                (self.stock_location.id, lot.id, False, False, 20.0, 2.0)
                for lot in lots
            ),
        )

    def test_moving_every_line_to_another_location(self):
        product = self._product("resync-6")
        shelf = self.env["stock.location"].create(
            {
                "name": "resync-shelf",
                "location_id": self.stock_location.id,
                "usage": "internal",
            }
        )
        self._stock(product, 1000)
        self._stock(product, 1000, location=shelf)
        lines = self._lines(self._delivery(product, 200), 20, 5)
        lines.write({"location_id": shelf.id})
        self.assertEqual(
            self._quant_state(product),
            sorted(
                [
                    (self.stock_location.id, False, False, False, 1000.0, 0.0),
                    (shelf.id, False, False, False, 1000.0, 100.0),
                ]
            ),
        )

    def test_giving_every_line_an_owner(self):
        product = self._product("resync-7")
        self._stock(product, 100)
        owner = self.env["res.partner"].create({"name": "resync owner"})
        lines = self._lines(self._delivery(product, 20), 5, 2)
        lines.write({"owner_id": owner.id})
        self.assertEqual(
            self._quant_state(product),
            sorted(
                [
                    (self.stock_location.id, False, False, False, 100.0, 0.0),
                    (self.stock_location.id, False, False, owner.id, 0.0, 10.0),
                ]
            ),
        )

    def test_changing_the_unit_rescales_the_reservation(self):
        product = self._product(
            "resync-8", uom=self.uom_unit, uoms=[self.uom_unit, self.uom_dozen]
        )
        self._stock(product, 1000)
        lines = self._lines(self._delivery(product, 100), 5, 12)
        lines.write({"product_uom_id": self.uom_dozen.id})
        self.assertEqual(
            self._quant_state(product),
            [(self.stock_location.id, False, False, False, 1000.0, 720.0)],
        )

    def test_a_source_that_bypasses_reservation_reserves_nothing(self):
        product = self._product("resync-9")
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.picking_type_in.id,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
                "move_ids": [
                    Command.create(
                        {
                            "product_id": product.id,
                            "product_uom_qty": 12,
                            "location_id": self.supplier_location.id,
                            "location_dest_id": self.stock_location.id,
                        }
                    )
                ],
            }
        )
        picking.action_confirm()
        lines = self._lines(picking, 3, 4)
        lines.write({"quantity": 2})
        self.assertEqual(
            [row for row in self._quant_state(product) if row[5]],
            [],
            "a supplier location holds no reservation to move",
        )

    def test_moving_lines_to_a_location_that_bypasses_reservation(self):
        product = self._product("resync-10")
        self._stock(product, 100)
        lines = self._lines(self._delivery(product, 12), 3, 4)
        lines.write({"location_id": self.supplier_location.id})
        self.assertEqual(
            self.Quant._gather(product, self.stock_location).reserved_quantity,
            0.0,
            "the reservation left behind must be released",
        )
        self.assertEqual(
            [row for row in self._quant_state(product) if row[5]],
            [],
            "and nothing reserved at the bypassing destination",
        )

    def test_quantity_and_location_written_together(self):
        product = self._product("resync-11")
        shelf = self.env["stock.location"].create(
            {
                "name": "resync-shelf-2",
                "location_id": self.stock_location.id,
                "usage": "internal",
            }
        )
        self._stock(product, 200)
        self._stock(product, 200, location=shelf)
        lines = self._lines(self._delivery(product, 30), 6, 5)
        lines.write({"location_id": shelf.id, "quantity": 2})
        self.assertEqual(
            self._quant_state(product),
            sorted(
                [
                    (self.stock_location.id, False, False, False, 200.0, 0.0),
                    (shelf.id, False, False, False, 200.0, 12.0),
                ]
            ),
        )

    def test_a_negative_quantity_is_refused(self):
        product = self._product("resync-12")
        self._stock(product, 100)
        lines = self._lines(self._delivery(product, 10), 1, 5)
        with self.assertRaises(UserError):
            lines.write({"quantity": -1})

    def _desynced(self, reserved):
        product = self._product(f"resync-desync-{reserved:g}")
        self._stock(product, 1000)
        lines = self._lines(self._delivery(product, 200), 20, 5)
        self.Quant._gather(product, self.stock_location).sudo().write(
            {"reserved_quantity": reserved}
        )
        self.env.flush_all()
        lines.write({"quantity": 3})
        self.env.invalidate_all()
        return self.Quant._gather(product, self.stock_location).reserved_quantity

    def test_a_partly_desynced_quant_lands_where_it_always_did(self):
        self.assertEqual(self._desynced(50.0), 10.0)

    def test_a_fully_desynced_quant_is_the_one_shape_that_changed(self):
        self.assertEqual(self._desynced(0.0), 0.0)


class TestBatchQuantCost(TestMoveLineCommon):
    def _write_cost(self, count):
        product = self._product(f"cost-{count}")
        self._stock(product, 10000)
        lines = self._lines(self._delivery(product, 10 * count), count, 5)
        self.env.flush_all()
        self.env.invalidate_all()
        before = self.env.cr.sql_log_count
        lines.write({"quantity": 3})
        self.env.flush_all()
        return self.env.cr.sql_log_count - before

    def test_writing_a_quantity_costs_the_same_for_two_lines_as_for_twenty(self):
        small, large = self._write_cost(2), self._write_cost(20)
        self.assertLess(
            large - small,
            (large + small) // 4,
            f"writing 20 lines cost {large} queries against {small} for 2 -- the"
            " reservation re-sync is charging per line again",
        )

    def test_creating_lines_on_a_done_picking_does_not_gather_per_line(self):
        def cost(count):
            product = self._product(f"done-cost-{count}")
            picking = self.env["stock.picking"].create(
                {
                    "picking_type_id": self.picking_type_in.id,
                    "location_id": self.supplier_location.id,
                    "location_dest_id": self.stock_location.id,
                    "move_ids": [
                        Command.create(
                            {
                                "product_id": product.id,
                                "product_uom_qty": 1,
                                "location_id": self.supplier_location.id,
                                "location_dest_id": self.stock_location.id,
                            }
                        )
                    ],
                }
            )
            picking.action_confirm()
            picking.move_ids.picked = True
            picking.button_validate()
            self.env.flush_all()
            vals = [
                {
                    "move_id": picking.move_ids.id,
                    "picking_id": picking.id,
                    "product_id": product.id,
                    "quantity": 1,
                    "location_id": self.supplier_location.id,
                    "location_dest_id": self.stock_location.id,
                }
            ] * count
            self.env.invalidate_all()
            before = self.env.cr.sql_log_count
            self.MoveLine.create(vals)
            self.env.flush_all()
            return self.env.cr.sql_log_count - before

        small, large = cost(2), cost(20)
        per_line = (large - small) / 18
        self.assertLess(
            per_line,
            7.0,
            f"{per_line:.1f} queries per additional done line -- the quant cache is not"
            " reaching the create path",
        )


class TestFreeReservationOrder(TestMoveLineCommon):
    def _reserved_picking(self, product, qty, date_planned=None):
        picking = self._delivery(product, qty, assign=True)
        if date_planned:
            picking.date_planned = date_planned
        self.env.flush_all()
        return picking

    def test_this_transfers_own_lines_are_taken_first(self):
        product = self._product("free-order-own")
        self._stock(product, 30)
        mine = self._delivery(product, 20, assign=True)
        theirs = self._reserved_picking(product, 10)
        self.env.flush_all()

        first, second = mine.move_ids.move_line_ids, theirs.move_ids.move_line_ids
        self.assertTrue(first and second, "both transfers must have reserved")

        sibling = self.MoveLine.create(
            {
                "move_id": mine.move_ids.id,
                "picking_id": mine.id,
                "product_id": product.id,
                "quantity": 1,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )
        self.env.flush_all()

        candidates = sibling._get_outdated_candidates({sibling.id})
        self.assertEqual(
            candidates[0].picking_id,
            mine,
            "the candidate list must open with this transfer's own lines",
        )

    def test_among_other_transfers_the_latest_scheduled_goes_first(self):
        product = self._product("free-order-date")
        self._stock(product, 30)
        soon = self._reserved_picking(product, 5, date_planned="2026-01-05 08:00:00")
        later = self._reserved_picking(product, 5, date_planned="2026-03-05 08:00:00")
        mine = self._delivery(product, 5, assign=True)
        self.env.flush_all()

        line = mine.move_ids.move_line_ids
        candidates = line._get_outdated_candidates({line.id})
        ordered = [
            candidate.picking_id
            for candidate in candidates
            if candidate.picking_id in (soon | later)
        ]
        self.assertEqual(
            ordered,
            [later, soon],
            "later-scheduled transfers give up their reservation before earlier ones",
        )

    def test_a_picked_line_is_never_taken(self):
        product = self._product("free-order-picked")
        self._stock(product, 20)
        theirs = self._reserved_picking(product, 5)
        theirs.move_ids.picked = True
        mine = self._delivery(product, 5, assign=True)
        self.env.flush_all()

        line = mine.move_ids.move_line_ids
        candidates = line._get_outdated_candidates({line.id})
        self.assertNotIn(theirs, candidates.picking_id)

    def test_the_callers_ignore_set_is_not_mutated(self):
        product = self._product("free-order-ignore")
        self._stock(product, 20)
        mine = self._delivery(product, 10, assign=True)
        self.env.flush_all()
        line = mine.move_ids.move_line_ids
        caller_set = OrderedSet()
        line._free_reservation(1.0, ml_ids_to_ignore=caller_set)
        self.assertEqual(
            list(caller_set), [], "the caller's set must come back untouched"
        )

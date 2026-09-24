from unittest.mock import patch

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tools import OrderedSet

from odoo.addons.stock.models.stock_move_line import (
    LOGGED_RELATIONS,
    RENDERED_KEYS,
    RESERVATION_KEY_FIELDS,
)
from odoo.addons.stock.tests.common import TestMoveLineCommon, TestStockCommon
from odoo.addons.stock.tests.test_move_line_write import MoveLineCase


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
        before = self.env.cr.sql_statement_count
        lines.write({"quantity": 3})
        self.env.flush_all()
        return self.env.cr.sql_statement_count - before

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
            before = self.env.cr.sql_statement_count
            self.MoveLine.create(vals)
            self.env.flush_all()
            return self.env.cr.sql_statement_count - before

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


@tagged("post_install", "-at_install")
class TestMoveLineReservationSymmetry(TestStockCommon):
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

    def _create_product(self, name):
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

    def _create_line(self, product, move_source, line_source, qty=30.0):
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
        product = self._create_product("sym-control")
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

        line = self._create_line(product, self.stock_location, self.stock_location)
        self.assertEqual(self._reserved(product, self.stock_location), 70.0)
        line.unlink()
        self.assertEqual(self._reserved(product, self.stock_location), 40.0)

    def test_line_source_outside_the_move_source_does_not_steal(self):
        product = self._create_product("sym-steal")
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

        line = self._create_line(product, self.supplier_location, self.stock_location)
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
        product = self._create_product("sym-phantom")
        line = self._create_line(product, self.stock_location, self.inventory_loc)
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
        line._update_quant_at_location(-1.0, self.stock_location, lot=lot)

        tracked, untracked = self._quantities(product, lot)
        self.assertEqual(tracked, 49.0, "the removal must land on the lot itself")
        self.assertEqual(untracked, 100.0, "untracked stock must be untouched")

    def test_compensation_is_capped_by_available_untracked_stock(self):
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
        line._update_quant_at_location(-20.0, self.stock_location, lot=lot)

        tracked, untracked = self._quantities(product, lot)
        self.assertEqual(tracked, -7.0)
        self.assertEqual(untracked, 0.0)


@tagged("post_install", "-at_install")
class TestReservationKeyHasOneDefinition(MoveLineCase):
    def test_overrides_replace_only_the_named_fields(self):
        product = self._product("Key Product")
        self._stock(product, self.src, 10.0)
        picking = self._outgoing(product, 2.0)
        line = picking.move_line_ids

        stored = line._get_reservation_key()
        moved = line._get_reservation_key({"location_id": self.customer})

        self.assertEqual(len(stored), len(RESERVATION_KEY_FIELDS))
        self.assertEqual(stored[0], moved[0], "product must be untouched")
        self.assertEqual(moved[1], self.customer)
        self.assertEqual(stored[2:], moved[2:], "lot/package/owner untouched")

    def test_an_unrelated_override_key_is_ignored(self):
        product = self._product("Key Product Two")
        self._stock(product, self.src, 10.0)
        line = self._outgoing(product, 2.0).move_line_ids

        self.assertEqual(
            line._get_reservation_key(),
            line._get_reservation_key({"location_dest_id": self.customer}),
        )

    def test_rendered_keys_tracks_logged_relations(self):
        for _field, rendered in LOGGED_RELATIONS:
            self.assertIn(rendered, RENDERED_KEYS)
        self.assertIn("quantity", RENDERED_KEYS)
        self.assertNotIn(
            "product_uom_qty",
            RENDERED_KEYS,
            "stock.move.line has no such field; it was a leftover",
        )


@tagged("post_install", "-at_install")
class TestSynchronizeQuantSignature(MoveLineCase):
    def _line(self):
        product = self._product("Sync Product")
        self._stock(product, self.src, 10.0)
        return self._outgoing(product, 2.0).move_line_ids

    def test_a_misspelled_override_is_a_type_error(self):
        line = self._line()
        with self.assertRaises(TypeError):
            line._update_quant_at_location(-1.0, self.src, packge=False)

    def test_the_named_override_still_works(self):
        line = self._line()
        available, _in_date = line._update_quant_at_location(
            -1.0, self.src, package=False
        )
        self.assertIsNotNone(available)

    def test_no_caller_asks_for_the_removed_action(self):
        line = self._line()
        with self.assertRaises(TypeError):
            line._update_quant_at_location(-1.0, self.src, action="reserved")


@tagged("post_install", "-at_install")
class TestMoveLineQuantUpdates(TestStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Quant = cls.env["stock.quant"]
        cls.loc = cls.stock_location

    def test_move_less_line_write_and_unlink_reservation(self):
        product = self.env["product.product"].create(
            {"name": "qimp-moveless", "is_storable": True}
        )
        self.Quant._update_available_quantity(product, self.loc, 10.0)

        def reserved():
            return sum(
                self.Quant.search(
                    [
                        ("product_id", "=", product.id),
                        ("location_id", "=", self.loc.id),
                    ]
                ).mapped("reserved_quantity")
            )

        ml = self.env["stock.move.line"].create(
            {
                "product_id": product.id,
                "location_id": self.loc.id,
                "location_dest_id": self.shelf_1.id,
                "company_id": self.env.company.id,
                "quantity": 2.0,
            }
        )
        self.assertFalse(ml.move_id)
        self.assertEqual(reserved(), 2.0, "create must reserve for move-less lines")
        ml.quantity = 3.0
        self.assertEqual(reserved(), 3.0, "write must re-sync the reservation")
        ml.unlink()
        self.assertEqual(
            reserved(),
            0.0,
            "unlink must release the reservation create took (previously leaked)",
        )

    def test_package_history_freezes_destination_chain(self):
        product = self.env["product.product"].create(
            {"name": "qimp-pkg-hist", "is_storable": True}
        )
        self.Quant._update_available_quantity(product, self.loc, 5.0)
        outer = self.env["stock.package"].create({"name": "QIMP-OUTER"})
        inner = self.env["stock.package"].create({"name": "QIMP-INNER"})
        move = self.env["stock.move"].create(
            {
                "product_id": product.id,
                "product_uom_qty": 5.0,
                "location_id": self.loc.id,
                "location_dest_id": self.shelf_1.id,
            }
        )
        move._action_confirm()
        move._action_assign()
        ml = move.move_line_ids
        ml.result_package_id = inner
        inner.package_dest_id = outer
        ml.picked = True
        move._action_done()

        history = self.env["stock.package.history"].search(
            [("package_id", "=", inner.id)]
        )
        self.assertEqual(len(history), 1)
        self.assertEqual(
            history.package_name,
            "QIMP-OUTER > QIMP-INNER",
            "package_name must freeze the destination chain, not the origin one",
        )
        self.assertEqual(history.parent_dest_id, outer)
        self.assertEqual(
            history._get_complete_dest_name_except_outermost(), "QIMP-INNER"
        )
        outer_history = self.env["stock.package.history"].search(
            [("package_id", "=", outer.id)]
        )
        self.assertEqual(outer_history.package_name, "QIMP-OUTER")
        self.assertEqual(outer_history._get_complete_dest_name_except_outermost(), "")

    def _spy_update_available_quantity(self):
        calls = []
        Quant = type(self.env["stock.quant"])
        original = Quant._update_available_quantity

        def spy(
            model,
            product_id,
            location_id,
            quantity=False,
            reserved_quantity=False,
            **kwargs,
        ):
            calls.append(
                {
                    "location": location_id.id,
                    "quantity": quantity,
                    "reserved": reserved_quantity,
                }
            )
            return original(
                model,
                product_id,
                location_id,
                quantity=quantity,
                reserved_quantity=reserved_quantity,
                **kwargs,
            )

        return calls, patch.object(Quant, "_update_available_quantity", spy)

    def test_action_done_updates_the_source_quant_once(self):
        product = self.env["product.product"].create(
            {"name": "qimp-donemerge", "is_storable": True}
        )
        self.Quant._update_available_quantity(product, self.loc, 10.0)
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.picking_type_out.id,
                "location_id": self.loc.id,
                "location_dest_id": self.customer_location.id,
            }
        )
        self.env["stock.move"].create(
            {
                "product_id": product.id,
                "product_uom_qty": 4.0,
                "picking_id": picking.id,
                "location_id": self.loc.id,
                "location_dest_id": self.customer_location.id,
            }
        )
        picking.action_confirm()
        picking.action_assign()
        quant = self.Quant._gather(product, self.loc, strict=True)
        self.assertEqual(quant.reserved_quantity, 4.0, "setup: the line is reserved")

        picking.move_ids.write({"picked": True})
        calls, spy = self._spy_update_available_quantity()
        with spy:
            picking._action_done()

        source_calls = [c for c in calls if c["location"] == self.loc.id]
        self.assertEqual(
            len(source_calls),
            1,
            "the release and the removal must share one quant update",
        )
        self.assertEqual(source_calls[0]["quantity"], -4.0)
        self.assertEqual(
            source_calls[0]["reserved"], -4.0, "the release rides along, not separately"
        )
        quant = self.Quant._gather(product, self.loc, strict=True)
        self.assertEqual(quant.quantity, 6.0)
        self.assertEqual(quant.reserved_quantity, 0.0, "no reservation may be stranded")

    def test_action_done_sends_no_reserved_delta_where_reservation_is_bypassed(self):
        product = self.env["product.product"].create(
            {"name": "qimp-donebypass", "is_storable": True}
        )
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.warehouse_1.in_type_id.id,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.loc.id,
            }
        )
        self.env["stock.move"].create(
            {
                "product_id": product.id,
                "product_uom_qty": 7.0,
                "picking_id": picking.id,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.loc.id,
            }
        )
        picking.action_confirm()
        picking.move_ids.move_line_ids.quantity = 7.0
        picking.move_ids.write({"picked": True})
        calls, spy = self._spy_update_available_quantity()
        with spy:
            picking._action_done()

        supplier_calls = [
            c for c in calls if c["location"] == self.supplier_location.id
        ]
        self.assertTrue(supplier_calls, "the supplier side is still decremented")
        self.assertTrue(
            all(not c["reserved"] for c in supplier_calls),
            "a bypassing location must receive no reservation delta",
        )
        self.assertEqual(
            self.Quant._gather(product, self.loc, strict=True).quantity, 7.0
        )

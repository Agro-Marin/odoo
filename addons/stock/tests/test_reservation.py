import inspect
from datetime import datetime
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.base.models.ir_model_common import MODULE_UNINSTALL_FLAG
from odoo.addons.stock.models.stock_move_reservation import _ReservationOutcome
from odoo.addons.stock.models.stock_quant_reservation import LOCKED_QUANTS_CACHE_KEY


@tagged("post_install", "-at_install")
class TestReservationQuantConsistency(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Quant = cls.env["stock.quant"]
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.env.company.id)], limit=1
        )
        cls.stock = cls.warehouse.lot_stock_id
        cls.customers = cls.env.ref("stock.stock_location_customers")
        cls.suppliers = cls.env.ref("stock.stock_location_suppliers")
        cls.unit = cls.env.ref("uom.product_uom_unit")
        cls.kg = cls.env.ref("uom.product_uom_kgm")
        cls.gram = cls.env.ref("uom.product_uom_gram")
        cls.ton = cls.env.ref("uom.product_uom_ton")

    def _product(self, uom=None, tracking="none", **vals):
        return self.env["product.product"].create(
            {
                "name": "resv-audit",
                "is_storable": True,
                "uom_id": (uom or self.unit).id,
                "tracking": tracking,
                **vals,
            }
        )

    def _lot(self, product, name):
        return self.env["stock.lot"].create({"name": name, "product_id": product.id})

    def _moves(self, product, quantities, uom=None, confirm=True):
        moves = self.env["stock.move"].create(
            [
                {
                    "product_id": product.id,
                    "product_uom_qty": quantity,
                    "product_uom_id": (uom or product.uom_id).id,
                    "location_id": self.stock.id,
                    "location_dest_id": self.customers.id,
                    "picking_type_id": self.warehouse.out_type_id.id,
                }
                for quantity in quantities
            ]
        )
        if confirm:
            moves._action_confirm(merge=False)
        return moves

    def _quants(self, product, location=None):
        self.env.flush_all()
        domain = [("product_id", "=", product.id)]
        if location:
            domain.append(("location_id", "=", location.id))
        return self.Quant.search(domain, order="id")

    # R1
    def test_sub_precision_demand_is_reserved_not_waved_through(self):
        product = self._product(self.kg)
        self.Quant._update_available_quantity(product, self.stock, 10.0)
        moves = self._moves(product, [2.0, 5.0, 7.0, 1234.0], uom=self.gram)
        moves._action_assign()
        self.assertEqual(moves.mapped("state"), ["assigned"] * 4)
        self.assertEqual(moves.mapped("quantity"), [2.0, 5.0, 7.0, 1234.0])
        self.assertAlmostEqual(
            sum(self._quants(product, self.stock).mapped("reserved_quantity")),
            1.248,
            places=9,
        )

    def test_a_kilogram_short_of_a_tonne_is_partially_available(self):
        product = self._product(self.ton)
        self.Quant._update_available_quantity(product, self.stock, 1.0)
        moves = self._moves(product, [4.0, 1234.0], uom=self.kg)
        moves._action_assign()
        self.assertEqual(moves[0].state, "assigned")
        self.assertEqual(moves[0].quantity, 4.0)
        self.assertEqual(moves[1].state, "partially_available")
        self.assertEqual(moves[1].quantity, 996.0)

    # R2
    def test_editing_a_done_line_moves_stock_by_the_stored_difference(self):
        product = self._product(self.kg)
        self.Quant._update_available_quantity(product, self.stock, 10.0)
        move = self.env["stock.move"].create(
            {
                "product_id": product.id,
                "product_uom_qty": 2.0,
                "product_uom_id": self.gram.id,
                "location_id": self.suppliers.id,
                "location_dest_id": self.stock.id,
                "picking_type_id": self.warehouse.in_type_id.id,
            }
        )
        move._action_confirm()
        move._action_assign()
        move.move_line_ids.quantity = 2.0
        move.picked = True
        move._action_done()
        self.assertAlmostEqual(
            self._quants(product, self.stock).quantity, 10.002, places=9
        )
        move.move_line_ids.quantity = 3.0
        self.assertAlmostEqual(
            self._quants(product, self.stock).quantity, 10.003, places=9
        )
        move.move_line_ids.quantity = 4.0
        self.assertAlmostEqual(
            self._quants(product, self.stock).quantity, 10.004, places=9
        )

    def test_editing_a_reserved_line_moves_the_reservation_by_the_stored_difference(
        self,
    ):
        product = self._product(self.kg)
        self.Quant._update_available_quantity(product, self.stock, 10.0)
        move = self._moves(product, [3000.0], uom=self.gram)
        move._action_assign()
        move.move_line_ids.quantity = 3003.0
        quant = self._quants(product, self.stock)
        self.assertAlmostEqual(quant.reserved_quantity, 3.003, places=9)
        move.move_line_ids.unlink()
        self.assertAlmostEqual(quant.reserved_quantity, 0.0, places=9)

    def _reserve_lot_on_untracked_stock(self, product, lot):
        self.Quant._update_available_quantity(product, self.stock, 5.0)
        product.tracking = "lot"
        move = self._moves(product, [5.0])
        move._action_assign()
        move.move_line_ids.lot_id = lot
        untracked = self._quants(product, self.stock)
        self.assertFalse(untracked.lot_id)
        self.assertEqual(untracked.reserved_quantity, 5.0)
        return move, untracked

    # R3
    def test_shipping_a_lot_reserved_on_untracked_stock_takes_the_lot(self):
        product = self._product()
        lot = self._lot(product, "R3")
        move, untracked = self._reserve_lot_on_untracked_stock(product, lot)
        self.Quant._update_available_quantity(product, self.stock, 5.0, lot_id=lot)
        move.picked = True
        move._action_done()
        lot_quant = self._quants(product, self.stock).filtered("lot_id")
        self.assertEqual(lot_quant.quantity, 0.0)
        self.assertEqual(untracked.quantity, 5.0)
        self.assertEqual(untracked.reserved_quantity, 0.0)

    # R4
    def test_releasing_a_lot_reservation_reaches_an_emptied_untracked_quant(self):
        product = self._product()
        lot = self._lot(product, "R4")
        move, untracked = self._reserve_lot_on_untracked_stock(product, lot)
        untracked.with_context(inventory_mode=True).inventory_quantity = 0.0
        untracked.with_context(inventory_mode=True).action_apply_inventory()
        self.assertEqual(untracked.quantity, 0.0)
        move._unreserve()
        quants = self._quants(product, self.stock)
        self.assertEqual(quants.mapped("reserved_quantity"), [0.0] * len(quants))
        self.assertEqual(
            self.Quant._get_available_quantity(
                product, self.stock, lot_id=lot, strict=True
            ),
            0.0,
        )

    # R5
    def test_reverting_a_count_into_a_package_takes_from_the_package(self):
        product = self._product()
        package = self.env["stock.package"].create({"name": "R5"})
        self.Quant._update_available_quantity(
            product, self.stock, 5.0, package_id=package
        )
        quant = self._quants(product, self.stock)
        quant.with_context(inventory_mode=True).inventory_quantity = 8.0
        quant.with_context(inventory_mode=True).action_apply_inventory()
        self.assertEqual(quant.quantity, 8.0)
        line = self.env["stock.move.line"].search(
            [("product_id", "=", product.id), ("is_inventory", "=", True)]
        )
        line.action_revert_inventory()
        in_stock = self._quants(product, self.stock)
        self.assertEqual(
            {(q.package_id, q.quantity) for q in in_stock if q.quantity},
            {(package, 5.0)},
        )

    # R6
    def test_least_packages_sees_the_packages_taken_earlier_in_the_run(self):
        least_packages = self.env["product.removal"].search(
            [("method", "=", "least_packages")], limit=1
        )
        category = self.env["product.category"].create(
            {"name": "R6", "removal_strategy_id": least_packages.id}
        )
        product = self._product(categ_id=category.id)
        packages = self.env["stock.package"].create(
            [{"name": f"R6-{index}"} for index in range(3)]
        )
        for package in packages:
            self.Quant._update_available_quantity(
                product, self.stock, 5.0, package_id=package
            )
        moves = self._moves(product, [5.0, 5.0, 5.0], confirm=False)
        moves.picking_type_id.reservation_method = "manual"
        moves._action_confirm(merge=False)
        moves._action_assign()
        self.assertEqual(moves.mapped("state"), ["assigned"] * 3)
        self.assertEqual(moves.move_line_ids.package_id, packages)

    # R7
    def test_resolving_a_conflict_keeps_the_counting_date(self):
        product = self._product()
        self.Quant._update_available_quantity(product, self.stock, 10.0)
        quant = self._quants(product, self.stock)
        quant.with_context(inventory_mode=True).inventory_quantity = 7.0
        self.env.flush_all()
        self.Quant._update_available_quantity(product, self.stock, 1.0)
        counted_at = datetime(2026, 1, 15, 12, 0)
        wizard = self.env["stock.inventory.adjustment.name"].create(
            {"quant_ids": [(6, 0, quant.ids)], "counting_date": counted_at}
        )
        action = wizard.action_apply()
        self.assertEqual(action["res_model"], "stock.inventory.conflict")
        conflict = (
            self.env["stock.inventory.conflict"]
            .with_context(action["context"])
            .create({})
        )
        conflict.action_keep_counted_quantity()
        moves = self.env["stock.move"].search(
            [("product_id", "=", product.id), ("is_inventory", "=", True)]
        )
        self.assertEqual(moves.date, counted_at)

    # R8
    def test_quant_creation_under_a_cleared_cache_context(self):
        product = self._product()
        self.Quant.with_context(quants_cache=None)._update_available_quantity(
            product, self.stock, 5.0
        )
        self.assertEqual(self._quants(product, self.stock).quantity, 5.0)

    def test_a_quant_created_under_the_cache_is_found_in_its_subtree(self):
        product = self._product()
        shelf = self.env["stock.location"].create(
            {"name": "R8 shelf", "location_id": self.stock.id}
        )
        cache = self.Quant._get_quants_by_products_locations(product, self.stock)
        self.Quant.with_context(quants_cache=cache)._update_available_quantity(
            product, shelf, 3.0
        )
        self.assertEqual(
            cache.under(product.id, self.stock.parent_path).mapped("quantity"), [3.0]
        )

    # R9
    def test_a_sub_precision_quant_can_be_counted_to_zero(self):
        product = self._product(self.kg)
        self.Quant._update_available_quantity(product, self.stock, 0.004)
        quant = self._quants(product, self.stock)
        quant.with_context(inventory_mode=True).inventory_quantity = 0.0
        quant.with_context(inventory_mode=True).action_apply_inventory()
        self.assertAlmostEqual(quant.quantity, 0.0, places=9)

    def test_setting_the_count_to_on_hand_changes_nothing(self):
        product = self._product(self.kg)
        self.Quant._update_available_quantity(product, self.stock, 10.004)
        quant = self._quants(product, self.stock)
        quant.with_context(inventory_mode=True).action_set_inventory_quantity()
        self.assertAlmostEqual(quant.inventory_diff_quantity, 0.0, places=9)
        quant.with_context(inventory_mode=True).action_apply_inventory()
        self.assertAlmostEqual(quant.quantity, 10.004, places=9)

    # R10
    def test_force_qty_is_gone(self):
        self.assertNotIn(
            "force_qty",
            inspect.signature(type(self.env["stock.move"])._action_assign).parameters,
        )

    def test_a_reservation_does_not_grow_a_picked_line(self):
        product = self._product()
        self.Quant._update_available_quantity(product, self.stock, 3.0)
        move = self._moves(product, [10.0])
        move._action_assign()
        picked = move.move_line_ids
        picked.picked = True
        self.Quant._update_available_quantity(product, self.stock, 4.0)
        move._update_reserved_quantity(4.0, self.stock, strict=False)
        self.assertEqual(picked.quantity, 3.0)
        self.assertEqual(sorted(move.move_line_ids.mapped("quantity")), [3.0, 4.0])

    # R11
    def test_a_removal_strategy_resolves_through_one_table(self):
        Quant = type(self.Quant)
        self.assertFalse(hasattr(Quant, "_get_removal_strategy_order"))
        self.assertFalse(hasattr(Quant, "_get_removal_strategy_sort_key"))
        self.assertIs(
            self.Quant._get_removal_strategy_record("fifo"),
            self.Quant._get_removal_strategies()["fifo"],
        )

    # R12
    def test_locking_a_quant_reads_it_in_the_same_query(self):
        product = self._product()
        self.Quant._update_available_quantity(product, self.stock, 5.0)
        quant = self._quants(product, self.stock)
        self.env.cr.cache.pop(LOCKED_QUANTS_CACHE_KEY, None)
        self.env.invalidate_all()
        quant = self.Quant.browse(quant.id)
        quant.fetch(["product_id"])
        with self.assertQueryCount(1):
            locked = quant._lock_one_for_reservation(False)
            self.assertEqual((locked.quantity, locked.reserved_quantity), (5.0, 0.0))

    # R13
    def test_a_quant_locked_by_another_transaction_is_not_reserved(self):
        product = self._product()
        shelves = self.env["stock.location"].create(
            [
                {"name": f"R13-{index}", "location_id": self.stock.id}
                for index in range(2)
            ]
        )
        self.Quant._update_available_quantity(
            product, shelves[0], 5.0, in_date=datetime(2026, 1, 1)
        )
        self.Quant._update_available_quantity(
            product, shelves[1], 5.0, in_date=datetime(2026, 2, 1)
        )
        held_elsewhere = self._quants(product, shelves[0])
        self.env.cr.cache.pop(LOCKED_QUANTS_CACHE_KEY, None)
        move = self._moves(product, [5.0], confirm=False)
        move.picking_type_id.reservation_method = "manual"
        move._action_confirm()

        quant_class = type(self.Quant)
        try_lock = quant_class._try_lock

        def skip_the_held_row(records, limit=None):
            return try_lock(records - held_elsewhere, limit=limit)

        with patch.object(quant_class, "_try_lock", skip_the_held_row):
            move._action_assign()

        self.assertEqual(move.state, "assigned")
        self.assertEqual(move.move_line_ids.location_id, shelves[1])
        self.assertEqual(held_elsewhere.reserved_quantity, 0.0)
        self.assertEqual(
            len(self._quants(product)),
            2,
            "no sibling quant may carry a reservation the held row could not take",
        )

    def test_done_lines_unlink_while_a_module_is_uninstalled(self):
        product = self._product()
        self.Quant._update_available_quantity(product, self.stock, 5.0)
        move = self._moves(product, [2.0])
        move._action_assign()
        move.picked = True
        move._action_done()
        line = move.move_line_ids
        self.assertEqual(line.state, "done")
        with self.assertRaises(UserError):
            line.unlink()
        line.with_context(**{MODULE_UNINSTALL_FLAG: True}).unlink()
        self.assertFalse(line.exists())
        quant = self._quants(product, self.stock)
        self.assertEqual((quant.quantity, quant.reserved_quantity), (3.0, 0.0))

    def test_the_serial_prefill_count_is_gone(self):
        self.assertFalse(
            hasattr(type(self.env["stock.move"]), "_get_serial_count_to_prefill")
        )
        self.assertNotIn("reserved", _ReservationOutcome._fields)

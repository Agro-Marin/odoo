from operator import ge, gt, le, lt

from odoo import fields
from odoo.tests import tagged

from odoo.addons.stock.tests.common import TestStockCommon


@tagged("post_install", "-at_install")
class TestQuantDormancy(TestStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dormant_product, cls.other_product = cls.env["product.product"].create(
            [
                {"name": "Dormant Widget", "is_storable": True},
                {"name": "Other Widget", "is_storable": True},
            ]
        )

    def _stock_quant(self, product):
        return self.env["stock.quant"].search(
            [
                ("product_id", "=", product.id),
                ("location_id", "=", self.stock_location.id),
            ]
        )

    def _dormant_quant(self, product, days, quantity=10.0):
        self.env["stock.quant"]._update_available_quantity(
            product, self.stock_location, quantity
        )
        quant = self._stock_quant(product)
        quant.write(
            {"in_date": fields.Datetime.subtract(fields.Datetime.now(), days=days)}
        )
        return quant

    def test_never_moved_ages_from_in_date(self):
        quant = self._dormant_quant(self.dormant_product, 100)
        self.assertFalse(
            quant.date_last_movement, "no move line has ever touched this quant"
        )
        self.assertEqual(quant.days_since_last_movement, 100)

    def test_inventory_count_is_not_a_movement(self):
        quant = self._dormant_quant(self.dormant_product, 100)
        counted = quant.with_context(inventory_mode=True)
        counted.inventory_quantity = 12.0
        counted.action_apply_inventory()

        quant.invalidate_recordset()
        self.assertTrue(quant.last_count_date, "the count is recorded, as a count")
        self.assertFalse(quant.date_last_movement)
        self.assertEqual(quant.days_since_last_movement, 100)

    def test_real_movement_sets_the_clock(self):
        quant = self._dormant_quant(self.dormant_product, 100)
        move = self.env["stock.move"].create(
            {
                "product_id": self.dormant_product.id,
                "product_uom_id": self.uom_unit.id,
                "product_uom_qty": 4.0,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )
        move._action_confirm()
        move._action_assign()
        move.picked = True
        move._action_done()
        move.move_line_ids.date = fields.Datetime.subtract(
            fields.Datetime.now(), days=10
        )

        quant.invalidate_recordset()
        self.assertEqual(quant.quantity, 6.0)
        self.assertTrue(quant.date_last_movement)
        self.assertEqual(
            quant.days_since_last_movement,
            10,
            "the picking, not the 100-day-old arrival, is what stopped last",
        )

    def test_search_agrees_with_the_compute(self):
        quants = self._dormant_quant(self.dormant_product, 5) | self._dormant_quant(
            self.other_product, 200
        )
        comparators = {">=": ge, ">": gt, "<=": le, "<": lt}
        for days in (1, 5, 100, 200, 500):
            for symbol, compare in comparators.items():
                with self.subTest(days=days, operator=symbol):
                    expected = quants.filtered(
                        lambda quant, c=compare, n=days: c(
                            quant.days_since_last_movement, n
                        )
                    )
                    found = self.env["stock.quant"].search(
                        [
                            ("id", "in", quants.ids),
                            ("days_since_last_movement", symbol, days),
                        ]
                    )
                    self.assertEqual(found, expected)

    def test_search_ignores_inventory_counts(self):
        quant = self._dormant_quant(self.dormant_product, 100)
        counted = quant.with_context(inventory_mode=True)
        counted.inventory_quantity = 12.0
        counted.action_apply_inventory()

        found = self.env["stock.quant"].search(
            [("id", "=", quant.id), ("days_since_last_movement", ">=", 90)]
        )
        self.assertEqual(found, quant)

    def test_search_unsupported_operator(self):
        self._dormant_quant(self.dormant_product, 100)
        with self.assertRaises(NotImplementedError):
            self.env["stock.quant"].search([("days_since_last_movement", "=", 100)])

    def _move_line(
        self,
        product,
        src,
        dest,
        quantity,
        lot=None,
        src_package=None,
        dest_package=None,
        owner=None,
    ):
        move = self.env["stock.move"].create(
            {
                "product_id": product.id,
                "product_uom_id": product.uom_id.id,
                "product_uom_qty": quantity,
                "location_id": src.id,
                "location_dest_id": dest.id,
            }
        )
        move._action_confirm()
        move.move_line_ids = [
            (
                0,
                0,
                {
                    "product_id": product.id,
                    "quantity": quantity,
                    "location_id": src.id,
                    "location_dest_id": dest.id,
                    "lot_id": lot.id if lot else False,
                    "package_id": src_package.id if src_package else False,
                    "result_package_id": dest_package.id if dest_package else False,
                    "owner_id": owner.id if owner else False,
                },
            )
        ]
        move.picked = True
        move._action_done()
        return move

    def _stocked(self, product, location, quantity, lot=None, package=None, owner=None):
        self.env["stock.quant"]._update_available_quantity(
            product, location, quantity, lot_id=lot, package_id=package, owner_id=owner
        )
        quant = self.env["stock.quant"].search(
            [
                ("product_id", "=", product.id),
                ("location_id", "=", location.id),
                ("lot_id", "=", lot.id if lot else False),
                ("package_id", "=", package.id if package else False),
                ("owner_id", "=", owner.id if owner else False),
            ]
        )
        self.assertEqual(len(quant), 1)
        quant.write(
            {"in_date": fields.Datetime.subtract(fields.Datetime.now(), days=400)}
        )
        return quant

    def _assert_dormancy(self, scenario, expected_moved):
        quants = self.env["stock.quant"].browse(list(expected_moved)).exists()
        alone = {}
        for quant in quants:
            quants.invalidate_recordset()
            alone[quant.id] = bool(
                self.env["stock.quant"].browse(quant.id).date_last_movement
            )
        quants.invalidate_recordset()
        batch = {quant.id: bool(quant.date_last_movement) for quant in quants}
        days = {quant.id: quant.days_since_last_movement for quant in quants}
        dormant = set(
            self.env["stock.quant"]
            .search([("id", "in", quants.ids), ("days_since_last_movement", ">=", 300)])
            .ids
        )
        for quant in quants:
            with self.subTest(scenario=scenario, quant=quant.display_name):
                self.assertEqual(
                    alone[quant.id],
                    batch[quant.id],
                    "read alone and read in a batch must be the same quant's answer",
                )
                self.assertEqual(
                    (quant.id in dormant),
                    days[quant.id] >= 300,
                    "the SQL search and the compute must not disagree",
                )
                self.assertEqual(
                    batch[quant.id],
                    expected_moved[quant.id],
                    "whether this move line touched this quant at all",
                )

    def test_every_move_shape_wakes_only_the_quants_it_touched(self):
        stock, pack = self.stock_location, self.pack_location
        Package = self.env["stock.package"]
        Product = self.env["product.product"]

        with self.subTest(shape="unpack"):
            product = Product.create({"name": "Unpacked", "is_storable": True})
            package = Package.create({"name": "Unpack Pallet"})
            packed = self._stocked(product, stock, 20.0, package=package)
            loose = self._stocked(product, stock, 5.0)
            self._move_line(product, stock, pack, 20.0, src_package=package)
            arrived = self.env["stock.quant"].search(
                [
                    ("product_id", "=", product.id),
                    ("location_id", "=", pack.id),
                    ("package_id", "=", False),
                ]
            )
            self._assert_dormancy(
                "unpack",
                {packed.id: True, loose.id: False, arrived.id: True},
            )

        with self.subTest(shape="pack"):
            product = Product.create({"name": "Packed", "is_storable": True})
            package = Package.create({"name": "Pack Pallet"})
            source = self._stocked(product, stock, 20.0)
            bystander = self._stocked(product, pack, 4.0)
            self._move_line(product, stock, pack, 20.0, dest_package=package)
            arrived = self.env["stock.quant"].search(
                [("product_id", "=", product.id), ("package_id", "=", package.id)]
            )
            self._assert_dormancy(
                "pack",
                {source.id: True, bystander.id: False, arrived.id: True},
            )

        with self.subTest(shape="repack in place"):
            product = Product.create({"name": "Repacked", "is_storable": True})
            old_package = Package.create({"name": "Repack From"})
            new_package = Package.create({"name": "Repack Into"})
            packed = self._stocked(product, stock, 20.0, package=old_package)
            loose = self._stocked(product, stock, 6.0)
            self._move_line(
                product,
                stock,
                stock,
                20.0,
                src_package=old_package,
                dest_package=new_package,
            )
            arrived = self.env["stock.quant"].search(
                [("product_id", "=", product.id), ("package_id", "=", new_package.id)]
            )
            self._assert_dormancy(
                "repack in place",
                {packed.id: True, loose.id: False, arrived.id: True},
            )

        with self.subTest(shape="package travels whole"):
            product = Product.create({"name": "Travelled", "is_storable": True})
            package = Package.create({"name": "Travelling Pallet"})
            self._stocked(product, stock, 20.0, package=package)
            here = self._stocked(product, stock, 2.0)
            there = self._stocked(product, pack, 2.0)
            self._move_line(
                product, stock, pack, 20.0, src_package=package, dest_package=package
            )
            arrived = self.env["stock.quant"].search(
                [("product_id", "=", product.id), ("package_id", "=", package.id)]
            )
            self._assert_dormancy(
                "package travels whole",
                {here.id: False, there.id: False, arrived.id: True},
            )

        with self.subTest(shape="owner"):
            product = Product.create({"name": "Consigned", "is_storable": True})
            owner = self.env["res.partner"].create({"name": "Dormancy Owner"})
            owned = self._stocked(product, stock, 10.0, owner=owner)
            unowned = self._stocked(product, stock, 10.0)
            self._move_line(product, stock, pack, 10.0, owner=owner)
            self._assert_dormancy("owner", {owned.id: True, unowned.id: False})

        with self.subTest(shape="lot"):
            product = Product.create(
                {"name": "Tracked", "is_storable": True, "tracking": "lot"}
            )
            lot = self.env["stock.lot"].create(
                {"name": "Dormancy Lot", "product_id": product.id}
            )
            tracked = self._stocked(product, stock, 10.0, lot=lot)
            untracked = self._stocked(product, stock, 10.0)
            self._move_line(product, stock, pack, 10.0, lot=lot)
            self._assert_dormancy("lot", {tracked.id: True, untracked.id: False})

    def _package_at(self, location, name):
        return self.env["stock.package"].create({"name": name})

    def _unpack_move(self, product, package, src, dest, quantity):
        move = self.env["stock.move"].create(
            {
                "product_id": product.id,
                "product_uom_id": product.uom_id.id,
                "product_uom_qty": quantity,
                "location_id": src.id,
                "location_dest_id": dest.id,
            }
        )
        move._action_confirm()
        move.move_line_ids = [
            (
                0,
                0,
                {
                    "product_id": product.id,
                    "quantity": quantity,
                    "location_id": src.id,
                    "location_dest_id": dest.id,
                    "package_id": package.id,
                    "result_package_id": False,
                },
            )
        ]
        move.picked = True
        move._action_done()
        return move

    def _packaged_quant(self, product, package, days, quantity=20.0):
        self.env["stock.quant"]._update_available_quantity(
            product, self.stock_location, quantity, package_id=package
        )
        quant = self.env["stock.quant"].search(
            [
                ("product_id", "=", product.id),
                ("location_id", "=", self.stock_location.id),
                ("package_id", "=", package.id),
            ]
        )
        quant.write(
            {"in_date": fields.Datetime.subtract(fields.Datetime.now(), days=days)}
        )
        return quant

    def test_unpacking_a_package_does_not_wake_the_loose_stock_beside_it(self):
        package = self._package_at(self.stock_location, "Pallet")
        loose = self._dormant_quant(self.dormant_product, 400, quantity=10.0)
        packed = self._packaged_quant(self.dormant_product, package, 400)

        self._unpack_move(
            self.dormant_product,
            package,
            self.stock_location,
            self.pack_location,
            20.0,
        )
        quants = loose | packed
        quants.invalidate_recordset()

        moved = {quant.id: quant.date_last_movement for quant in quants}
        dormant = {quant.id: quant.days_since_last_movement for quant in quants}

        self.assertFalse(
            moved[loose.id],
            "the loose quant was never touched by the unpacking move",
        )
        self.assertEqual(dormant[loose.id], 400)
        self.assertTrue(moved[packed.id], "the package quant is what the move emptied")
        self.assertEqual(dormant[packed.id], 0)

    def test_stock_that_arrived_by_unpacking_is_not_dormant(self):
        package = self._package_at(self.stock_location, "Pallet")
        self._packaged_quant(self.dormant_product, package, 400)
        self._unpack_move(
            self.dormant_product,
            package,
            self.stock_location,
            self.pack_location,
            20.0,
        )
        arrived = self.env["stock.quant"].search(
            [
                ("product_id", "=", self.dormant_product.id),
                ("location_id", "=", self.pack_location.id),
                ("package_id", "=", False),
            ]
        )
        self.assertEqual(arrived.quantity, 20.0, "the goods landed here, loose")
        arrived.write(
            {"in_date": fields.Datetime.subtract(fields.Datetime.now(), days=400)}
        )
        arrived.invalidate_recordset()

        self.assertTrue(
            arrived.date_last_movement, "the unpacking move is what put it here"
        )
        self.assertEqual(arrived.days_since_last_movement, 0)
        self.assertFalse(
            self.env["stock.quant"].search(
                [("id", "=", arrived.id), ("days_since_last_movement", ">=", 300)]
            ),
            "the search must not have to disagree with the compute",
        )

    def test_the_compute_does_not_depend_on_who_else_is_in_the_recordset(self):
        package = self._package_at(self.stock_location, "Pallet")
        loose = self._dormant_quant(self.dormant_product, 400, quantity=10.0)
        packed = self._packaged_quant(self.dormant_product, package, 400)
        self._unpack_move(
            self.dormant_product,
            package,
            self.stock_location,
            self.pack_location,
            20.0,
        )

        (loose | packed).invalidate_recordset()
        alone = loose.days_since_last_movement
        (loose | packed).invalidate_recordset()
        together = {q.id: q.days_since_last_movement for q in (loose | packed)}

        self.assertEqual(
            alone,
            together[loose.id],
            "the same quant, in the same transaction, read two ways",
        )
        self.assertEqual(alone, 400)

    def test_search_agrees_with_the_compute_across_packages(self):
        package = self._package_at(self.stock_location, "Pallet")
        loose = self._dormant_quant(self.dormant_product, 400, quantity=10.0)
        packed = self._packaged_quant(self.dormant_product, package, 400)
        self._unpack_move(
            self.dormant_product,
            package,
            self.stock_location,
            self.pack_location,
            20.0,
        )
        quants = loose | packed
        quants.invalidate_recordset()

        expected = quants.filtered(lambda q: q.days_since_last_movement >= 300)
        found = self.env["stock.quant"].search(
            [("id", "in", quants.ids), ("days_since_last_movement", ">=", 300)]
        )
        self.assertEqual(found, expected)
        self.assertEqual(found, loose)

    def test_counting_a_package_is_not_a_count_of_the_loose_stock(self):
        package = self._package_at(self.stock_location, "Pallet")
        loose = self._dormant_quant(self.dormant_product, 400, quantity=10.0)
        packed = self._packaged_quant(self.dormant_product, package, 400)

        counted = packed.with_context(inventory_mode=True)
        counted.inventory_quantity = 18.0
        counted.action_apply_inventory()
        quants = loose | packed
        quants.invalidate_recordset()

        last_count = {quant.id: quant.last_count_date for quant in quants}

        self.assertTrue(last_count[packed.id], "the package quant is what was counted")
        self.assertFalse(
            last_count[loose.id], "nobody counted the loose stock beside it"
        )

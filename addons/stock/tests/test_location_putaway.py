from collections import Counter
from contextlib import contextmanager

from psycopg.errors import UniqueViolation

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tools import mute_logger

from ..models.stock_location_putaway import PutawayScan
from odoo.addons.stock.tests.common import DoneMoveCase, LocationCase, TestStockCommon


class TestEmptyOnlyStorage(DoneMoveCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        category = cls.env["stock.storage.category"].create(
            {"name": "Empty only", "allow_new_product": "empty"}
        )
        cls.bins = cls.Location.create(
            [
                {
                    "name": f"Empty only bin {index}",
                    "location_id": cls.stock.id,
                    "storage_category_id": category.id,
                }
                for index in range(3)
            ]
        )
        cls.serial = cls.Product.create(
            {"name": "Empty only serial", "is_storable": True, "tracking": "serial"}
        )
        cls.env["stock.putaway.rule"].create(
            {
                "location_in_id": cls.stock.id,
                "location_out_id": cls.stock.id,
                "product_id": cls.serial.id,
                "storage_category_id": category.id,
                "sublocation": "closest_location",
            }
        )

    def test_a_batch_does_not_fill_an_empty_only_bin_twice(self):
        locations = self.stock._get_putaway_strategy_batch(self.serial, [1, 1, 1])
        self.assertEqual(
            [location.id for location in locations],
            self.bins.ids,
            "a bin that received the first serial is no longer empty",
        )

    def test_goods_on_their_way_in_make_a_bin_non_empty(self):
        move = self.env["stock.move"].create(
            {
                "product_id": self.serial.id,
                "product_uom_qty": 1,
                "location_id": self.supplier.id,
                "location_dest_id": self.stock.id,
            }
        )
        move._action_confirm()
        move.move_line_ids.location_dest_id = self.bins[0]
        self.assertEqual(move.move_line_ids.location_dest_id, self.bins[0])
        self.assertEqual(
            self.stock._get_putaway_strategy(self.serial, quantity=1), self.bins[1]
        )
        self.assertEqual(
            self.stock.with_context(
                exclude_sml_ids=set(move.move_line_ids.ids)
            )._get_putaway_strategy(self.serial, quantity=1),
            self.bins[0],
            "the line being placed does not occupy its own bin",
        )


@tagged("post_install", "-at_install")
class TestPutawayScanCost(TestStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.package_type = cls.env["stock.package.type"].create({"name": "Audit Box"})
        cls.storage_category = cls.env["stock.storage.category"].create(
            {
                "name": "Audit Category",
                "max_weight": 10000,
                "package_capacity_ids": [
                    (0, 0, {"package_type_id": cls.package_type.id, "quantity": 1}),
                ],
            },
        )

    def _saturated_zone(self, name, width):
        zone = self.StockLocationObj.create(
            {"name": name, "location_id": self.stock_location.id, "usage": "view"},
        )
        shelves = self.StockLocationObj.create(
            [
                {
                    "name": f"{name}-{index:03d}",
                    "location_id": zone.id,
                    "storage_category_id": self.storage_category.id,
                }
                for index in range(width)
            ],
        )
        for shelf in shelves:
            self.env["stock.quant"].create(
                {
                    "product_id": self.productA.id,
                    "location_id": shelf.id,
                    "quantity": 1,
                    "package_id": self.env["stock.package"]
                    .create({"package_type_id": self.package_type.id})
                    .id,
                },
            )
        self.env["stock.putaway.rule"].create(
            {
                "location_in_id": zone.id,
                "location_out_id": zone.id,
                "storage_category_id": self.storage_category.id,
                "sublocation": "closest_location",
                "product_id": self.productA.id,
            },
        )
        self.env.flush_all()
        return zone

    def _queries_to_scan(self, name, width):
        zone = self._saturated_zone(name, width)
        package = self.env["stock.package"].create(
            {"package_type_id": self.package_type.id},
        )
        self.env.flush_all()
        self.env.invalidate_all()
        before = self.env.cr.sql_statement_count
        zone._get_putaway_strategy(self.productA, 1, package=package)
        return self.env.cr.sql_statement_count - before

    def test_scanning_twice_as_many_candidates_costs_the_same(self):
        narrow = self._queries_to_scan("Narrow scan", 5)
        wide = self._queries_to_scan("Wide scan", 25)
        self.assertLessEqual(
            wide,
            narrow + 2,
            "a per-candidate query is back in the scan: 25 candidates cost "
            f"{wide} queries where 5 cost {narrow}",
        )

    def test_the_scan_still_refuses_a_saturated_zone(self):
        zone = self._saturated_zone("Refusing", 3)
        package = self.env["stock.package"].create(
            {"package_type_id": self.package_type.id},
        )
        candidates = zone.child_internal_location_ids
        capacity = candidates._get_putaway_capacity(self.productA, package)

        for shelf in candidates:
            self.assertFalse(
                shelf._can_be_used(
                    self.productA,
                    1,
                    package=package,
                    location_qty=1,
                    capacity=capacity,
                ),
                f"{shelf.display_name} already holds its one allowed package",
            )
        self.assertTrue(
            all(
                shelf._can_be_used(
                    self.productA,
                    1,
                    package=package,
                    location_qty=0,
                    capacity=capacity,
                )
                for shelf in candidates
            ),
            "the same shelves accept a package while under capacity",
        )

    def test_the_package_weight_still_counts_against_the_maximum(self):
        self.productA.weight = 100
        self.storage_category.max_weight = 150
        zone = self.StockLocationObj.create(
            {"name": "Heavy", "location_id": self.stock_location.id, "usage": "view"},
        )
        shelf = self.StockLocationObj.create(
            {
                "name": "Heavy-shelf",
                "location_id": zone.id,
                "storage_category_id": self.storage_category.id,
            },
        )
        package = self.env["stock.package"].create(
            {"package_type_id": self.package_type.id},
        )
        move = self.env["stock.move"].create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 2,
                "location_id": self.supplier_location.id,
                "location_dest_id": shelf.id,
            },
        )
        move._action_confirm()
        self.env["stock.move.line"].create(
            {
                "move_id": move.id,
                "product_id": self.productA.id,
                "quantity": 2,
                "location_id": self.supplier_location.id,
                "location_dest_id": shelf.id,
                "result_package_id": package.id,
            },
        )
        self.env.flush_all()

        self.assertFalse(
            shelf._can_store_package(package, 0, 0.0),
            "200kg on its way into the package exceeds the 150kg maximum",
        )

    def test_a_package_is_not_placed_on_a_shelf_committed_elsewhere(self):
        category = self.env["stock.storage.category"].create(
            {"name": "Same product only", "allow_new_product": "same"},
        )
        zone = self.StockLocationObj.create(
            {
                "name": "Committed",
                "location_id": self.stock_location.id,
                "usage": "view",
            },
        )
        foreign, same = self.StockLocationObj.create(
            [
                {
                    "name": name,
                    "location_id": zone.id,
                    "storage_category_id": category.id,
                }
                for name in ("A expecting productB", "B expecting productA")
            ],
        )
        self.env["stock.putaway.rule"].create(
            {
                "location_in_id": zone.id,
                "location_out_id": zone.id,
                "storage_category_id": category.id,
                "sublocation": "closest_location",
                "product_id": self.productA.id,
            },
        )
        for product, destination in ((self.productB, foreign), (self.productA, same)):
            move = self.env["stock.move"].create(
                {
                    "product_id": product.id,
                    "product_uom_qty": 1,
                    "location_id": self.supplier_location.id,
                    "location_dest_id": destination.id,
                },
            )
            move._action_confirm()
            self.env["stock.move.line"].create(
                {
                    "move_id": move.id,
                    "product_id": product.id,
                    "quantity": 1,
                    "location_id": self.supplier_location.id,
                    "location_dest_id": destination.id,
                },
            )
        package = self.env["stock.package"].create(
            {"package_type_id": self.package_type.id},
        )
        self.env.flush_all()

        chosen = zone.with_context(products=self.productA)._get_putaway_strategy(
            self.env["product.product"], package=package
        )

        self.assertEqual(
            chosen,
            same,
            f"a package of {self.productA.name} was placed on "
            f"{chosen.name}, which is expecting {self.productB.name}",
        )

    def test_a_deep_product_category_still_matches_an_ancestor_rule(self):
        category = self.env["product.category"].create({"name": "Audit root"})
        root_category = category
        for depth in range(5):
            category = self.env["product.category"].create(
                {"name": f"Audit depth {depth}", "parent_id": category.id},
            )
        product = self.env["product.product"].create(
            {
                "name": "Deeply categorised",
                "is_storable": True,
                "categ_id": category.id,
            },
        )
        zone = self.StockLocationObj.create(
            {
                "name": "Categ zone",
                "location_id": self.stock_location.id,
                "usage": "view",
            },
        )
        shelf = self.StockLocationObj.create(
            {"name": "Categ shelf", "location_id": zone.id},
        )
        self.env["stock.putaway.rule"].create(
            {
                "location_in_id": zone.id,
                "location_out_id": shelf.id,
                "category_id": root_category.id,
            },
        )
        self.env.flush_all()

        self.assertEqual(
            zone._get_putaway_strategy(product, 1),
            shelf,
            "a rule on the root category must match a product five levels down",
        )


@tagged("post_install", "-at_install")
class TestPutawayBatchHonoursItsOwnPlacements(LocationCase):
    def _create_putaway_scenario(self, name, category_vals=None, capacity_qty=None):
        category = self.env["stock.storage.category"].create(
            {"name": name, **(category_vals or {})},
        )
        view = self._create_location(f"{name} View", usage="view")
        shelves = self.Location.create(
            [
                {
                    "name": f"{name}{letter}",
                    "location_id": view.id,
                    "usage": "internal",
                    "storage_category_id": category.id,
                }
                for letter in "AB"
            ],
        )
        product = self._create_product(f"{name} Product")
        self.env["stock.putaway.rule"].create(
            {
                "location_in_id": view.id,
                "location_out_id": view.id,
                "product_id": product.id,
                "storage_category_id": category.id,
            },
        )
        if capacity_qty is not None:
            self.env["stock.storage.category.capacity"].create(
                {
                    "storage_category_id": category.id,
                    "product_id": product.id,
                    "quantity": capacity_qty,
                },
            )
        self.env.flush_all()
        return view, shelves, product

    def _placed(self, view, product, quantities):
        locations = view._get_putaway_strategy_batch(product, quantities)
        placed = {}
        for quantity, location in zip(quantities, locations, strict=True):
            placed[location] = placed.get(location, 0.0) + quantity
        return placed

    def test_a_batch_does_not_pile_past_the_weight_capacity(self):
        view, __, product = self._create_putaway_scenario(
            "Weight", {"max_weight": 10.0}
        )
        placed = self._placed(view, product, [4.0] * 4)
        self.assertTrue(
            all(quantity * product.weight <= 10.0 for quantity in placed.values()),
            "16 kg of a 10 kg-capped category was placed as "
            f"{ {location.name: qty for location, qty in placed.items()} }",
        )

    def test_it_spills_to_the_second_shelf_exactly_as_the_quantity_cap_does(self):
        weight_view, __, weight_product = self._create_putaway_scenario(
            "W2", {"max_weight": 10.0}
        )
        qty_view, __, qty_product = self._create_putaway_scenario(
            "Q2", capacity_qty=10.0
        )
        by_weight = sorted(
            self._placed(weight_view, weight_product, [4.0] * 4).values()
        )
        by_quantity = sorted(self._placed(qty_view, qty_product, [4.0] * 4).values())
        self.assertEqual(by_weight, by_quantity)
        self.assertEqual(by_weight, [8.0, 8.0])

    def test_committed_stock_still_decides_a_single_placement(self):
        view, shelves, product = self._create_putaway_scenario(
            "W3", {"max_weight": 10.0}
        )
        self.Quant._update_available_quantity(product, shelves[0], 8)
        self.env.flush_all()
        self.assertEqual(view._get_putaway_strategy(product, 4.0), shelves[1])

    @contextmanager
    def _counting_queries(self):
        cursor_class = type(self.env.cr)
        original = cursor_class.execute
        counter = Counter()

        def patched(cursor, query, params=None, log_exceptions=True):
            counter["queries"] += 1
            return original(cursor, query, params, log_exceptions)

        cursor_class.execute = patched
        try:
            yield counter
        finally:
            cursor_class.execute = original

    def test_the_batch_does_not_cost_more_the_longer_it_gets(self):
        view, __, product = self._create_putaway_scenario("W4", {"max_weight": 1000.0})
        view._get_putaway_strategy_batch(product, [1.0])
        counts = {}
        for length in (1, 5, 20):
            self.env.flush_all()
            self.env.invalidate_all()
            with self._counting_queries() as counter:
                view._get_putaway_strategy_batch(product, [1.0] * length)
            counts[length] = counter["queries"]
        self.assertEqual(
            sorted(set(counts.values())),
            [counts[20]],
            f"a putaway batch still scales with its length: {counts}. Nothing is "
            "written between placements, so every aggregate a longer batch adds "
            "is byte-identical to one it already ran.",
        )

    def test_a_caller_supplied_additional_qty_is_not_counted_as_weight(self):
        product = self._create_product("Seeded", weight=2.0)
        scan = PutawayScan(product, {7: 100.0})
        self.assertEqual(scan.placed[7], 100.0)
        self.assertEqual(scan.get_staged_weight(7), 0.0)
        scan.place(self.stock_location.browse(7), 3.0)
        self.assertEqual(scan.placed[7], 103.0)
        self.assertEqual(scan.get_staged_weight(7), 6.0)


@tagged("post_install", "-at_install")
class TestLocationPackageEdgeCases(TestStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Package = cls.env["stock.package"]
        cls.Quant = cls.env["stock.quant"]

    def _create_full_package(self, name, product, location, qty=5.0):
        package = self.Package.create({"name": name})
        self.Quant._update_available_quantity(
            product, location, qty, package_id=package
        )
        return package

    def test_package_write_location_guards_per_record(self):
        pkg_full = self._create_full_package("PKG-FULL", self.productA, self.shelf_1)
        pkg_empty = self.Package.create({"name": "PKG-EMPTY"})
        batch = pkg_full | pkg_empty

        with self.assertRaises(UserError):
            batch.write({"location_id": False})

        with self.assertRaises(UserError):
            batch.write({"location_id": self.shelf_2.id})

        pkg_empty.write({"location_id": False})
        pkg_full.write({"location_id": self.shelf_2.id})
        self.assertEqual(pkg_full.location_id, self.shelf_2)
        moved_quants = self.Quant._gather(
            self.productA, self.shelf_2, package_id=pkg_full, strict=True
        )
        self.assertEqual(sum(moved_quants.mapped("quantity")), 5.0)

    def test_product_capacity_rounding(self):
        category = self.env["stock.storage.category"].create(
            {
                "name": "Rounding category",
                "capacity_ids": [
                    (0, 0, {"product_id": self.productA.id, "quantity": 0.4}),
                ],
            }
        )
        self.shelf_1.storage_category_id = category

        self.assertTrue(
            self.shelf_1._can_store_product(self.productA, 0.1, 0.1 + 0.2, 0.0)
        )
        self.assertFalse(self.shelf_1._can_store_product(self.productA, 0.0, 0.4, 0.0))
        self.assertFalse(self.shelf_1._can_store_product(self.productA, 0.2, 0.3, 0.0))

    def test_max_weight_zero_means_unlimited(self):
        category = self.env["stock.storage.category"].create(
            {"name": "Weight category", "max_weight": 0.0}
        )
        self.shelf_1.storage_category_id = category
        self.productB.weight = 5.0

        self.assertTrue(self.shelf_1._can_store_product(self.productB, 1.0, 0.0, 0.0))

        category.max_weight = 4.0
        self.assertFalse(self.shelf_1._can_store_product(self.productB, 1.0, 0.0, 0.0))
        category.max_weight = 5.0
        self.assertTrue(
            self.shelf_1._can_store_product(self.productB, 1.0, 0.0, 0.0000000001)
        )

    def test_package_capacity_rounding(self):
        package_type = self.env["stock.package.type"].create({"name": "Crate"})
        category = self.env["stock.storage.category"].create(
            {
                "name": "Package category",
                "capacity_ids": [
                    (0, 0, {"package_type_id": package_type.id, "quantity": 3}),
                ],
            }
        )
        self.shelf_1.storage_category_id = category
        package = self.Package.create(
            {"name": "PKG-CAP", "package_type_id": package_type.id}
        )

        self.assertTrue(self.shelf_1._can_store_package(package, 2, 0.0))
        self.assertFalse(self.shelf_1._can_store_package(package, 3, 0.0))
        self.assertFalse(self.shelf_1._can_store_package(package, 2.9999999999, 0.0))

    def test_check_new_product_policy_without_products_context(self):
        package_type = self.env["stock.package.type"].create({"name": "Tote"})
        category = self.env["stock.storage.category"].create(
            {"name": "Same-product category", "allow_new_product": "same"}
        )
        self.shelf_2.storage_category_id = category
        package = self.Package.create(
            {"name": "PKG-POLICY", "package_type_id": package_type.id}
        )

        self.assertTrue(
            self.shelf_2._can_be_used(self.env["product.product"], package=package)
        )

    def test_propagate_active_noop_keeps_archived_descendants(self):
        parent, child = self.StockLocationObj.create(
            [
                {"name": "Prop parent", "location_id": self.stock_location.id},
                {"name": "Prop child"},
            ]
        )
        child.location_id = parent
        child.active = False

        parent.write({"active": True})
        self.assertFalse(child.active)

        parent.write({"active": False})
        self.assertFalse(parent.active)
        parent.write({"active": True})
        self.assertTrue(child.active)

    def test_replenish_conflict_includes_archived_ancestor(self):
        parent, child = self.StockLocationObj.create(
            [
                {"name": "Replenish parent"},
                {"name": "Replenish child"},
            ]
        )
        child.location_id = parent
        parent.replenish_location = True
        parent.active = False
        child.active = True

        with self.assertRaises(ValidationError):
            child.replenish_location = True

    def test_package_info_recomputes_on_in_place_quant_update(self):
        package = self._create_full_package(
            "PKG-INFO", self.productC, self.shelf_1, qty=5.0
        )
        self.assertEqual(package.location_id, self.shelf_1)

        self.Quant._update_available_quantity(
            self.productC, self.shelf_1, -5.0, package_id=package
        )
        self.assertFalse(package.location_id)

    def test_lot_unique_sql_constraint(self):
        self.productA.tracking = "lot"
        self.env["stock.lot"].create(
            {"name": "LOT-UNIQ", "product_id": self.productA.id, "company_id": False}
        )
        self.env.flush_all()

        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.env["stock.lot"].create(
                {
                    "name": "LOT-UNIQ",
                    "product_id": self.productA.id,
                    "company_id": False,
                }
            )
        renamed = self.env["stock.lot"].create(
            {"name": "LOT-UNIQ-OTHER", "product_id": self.productA.id}
        )
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            renamed.write({"name": "LOT-UNIQ"})

        with (
            self.assertRaises(UniqueViolation),
            mute_logger("odoo.db.cursor"),
            self.env.cr.savepoint(),
        ):
            self.env.cr.execute(
                "INSERT INTO stock_lot (name, product_id) VALUES (%s, %s)",
                ("LOT-UNIQ", self.productA.id),
            )

        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.env["stock.lot"].create(
                {
                    "name": "LOT-UNIQ",
                    "product_id": self.productA.id,
                    "company_id": self.env.company.id,
                }
            )

    def test_search_qty_available_zero_branch(self):
        self.Quant._update_available_quantity(self.productD, self.shelf_1, 3.0)
        scoped = [("id", "in", (self.productD | self.productE).ids)]

        zero = self.ProductObj.search([("qty_available", "=", 0), *scoped])
        self.assertEqual(zero, self.productE)

        positive = self.ProductObj.search([("qty_available", ">", 0), *scoped])
        self.assertEqual(positive, self.productD)

        at_most = self.ProductObj.search([("qty_available", "<=", 3), *scoped])
        self.assertEqual(at_most, self.productD | self.productE)

    def test_inverse_qty_available_negative_raises(self):
        with self.assertRaises(UserError):
            self.productE.qty_available = -3.0

    def test_package_type_write_falsy_sequence_code(self):
        package_type = self.env["stock.package.type"].create({"name": "No-seq type"})
        package_type.write({"sequence_code": False})
        self.assertFalse(package_type.sequence_id)

    def test_scrap_location_default_designation(self):
        company = self.env.company
        adjustment = self.StockLocationObj.search(
            [("company_id", "=", company.id), ("usage", "=", "inventory")],
            order="id",
            limit=1,
        )
        designated = company._get_scrap_location()
        self.assertTrue(designated)
        self.assertNotEqual(designated, adjustment)
        scrap_default = self.env["stock.scrap"].create(
            {"product_id": self.productA.id, "company_id": company.id}
        )
        self.assertEqual(scrap_default.scrap_location_id, designated)

        scrap_location = self.StockLocationObj.create(
            {"name": "Scrap", "usage": "inventory", "company_id": company.id}
        )
        scrap_w_named = self.env["stock.scrap"].create(
            {"product_id": self.productA.id, "company_id": company.id}
        )
        self.assertEqual(
            scrap_w_named.scrap_location_id,
            designated,
            "a name is not a designation",
        )

        self.env["ir.model.data"].search(
            [
                ("module", "=", "stock"),
                ("name", "=", f"stock_location_scrap_company_{company.id}"),
            ]
        ).res_id = scrap_location.id
        scrap_w_designated = self.env["stock.scrap"].create(
            {"product_id": self.productA.id, "company_id": company.id}
        )
        self.assertEqual(scrap_w_designated.scrap_location_id, scrap_location)


@tagged("post_install", "-at_install")
class TestStockLocationPutawayContract(TestStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse_2 = cls.env["stock.warehouse"].create(
            {"name": "Second Warehouse", "code": "WH2"},
        )
        cls.package_type = cls.env["stock.package.type"].create({"name": "Box"})

    def test_get_putaway_strategy_refuses_multiple_locations(self):
        destinations = self.stock_location | self.warehouse_2.lot_stock_id
        with self.assertRaises(ValueError):
            destinations.with_context(
                locations=self.env["stock.location"]
            )._get_putaway_strategy(self.productA, 1)

    def test_locations_context_is_narrowed_to_the_destination(self):
        candidates = (
            self.warehouse_2.lot_stock_id.child_internal_location_ids
            | self.stock_location.child_internal_location_ids
        )
        view_location = self.warehouse_1.view_location_id
        chosen = view_location.with_context(locations=candidates)._get_putaway_strategy(
            self.productA, 1
        )
        self.assertTrue(
            chosen._is_child_of(view_location),
            f"{chosen.complete_name} is outside the destination "
            f"{view_location.complete_name}",
        )

    def test_empty_locations_context_is_not_a_missing_one(self):
        view_location = self.warehouse_1.view_location_id
        chosen = view_location.with_context(
            locations=self.env["stock.location"]
        )._get_putaway_strategy(self.productA, 1)
        self.assertEqual(chosen, view_location)

    def test_putaway_keeps_each_line_inside_its_own_destination(self):
        dest_1 = self.stock_location
        dest_2 = self.warehouse_1.wh_input_stock_loc_id
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.picking_type_in.id,
                "location_id": self.supplier_location.id,
                "location_dest_id": dest_1.id,
            },
        )
        moves = self.env["stock.move"].create(
            [
                {
                    "product_id": self.productA.id,
                    "product_uom_qty": 1,
                    "picking_id": picking.id,
                    "location_id": self.supplier_location.id,
                    "location_dest_id": destination.id,
                }
                for destination in (dest_1, dest_2)
            ],
        )
        picking.action_confirm()
        package = self.env["stock.package"].create(
            {"package_type_id": self.package_type.id},
        )
        move_lines = self.env["stock.move.line"].create(
            [
                {
                    "move_id": move.id,
                    "product_id": self.productA.id,
                    "quantity": 1,
                    "location_id": move.location_id.id,
                    "location_dest_id": move.location_dest_id.id,
                    "result_package_id": package.id,
                }
                for move in moves
            ],
        )

        move_lines._apply_putaway_strategy()

        for line in move_lines:
            self.assertTrue(
                line.location_dest_id._is_child_of(line.move_id.location_dest_id),
                f"line for move to {line.move_id.location_dest_id.complete_name} "
                f"was put away in {line.location_dest_id.complete_name}",
            )


@tagged("post_install", "-at_install")
class TestPutawayQuantityUnit(TestStockCommon):
    def test_capacity_is_checked_in_the_product_uom(self):
        product = self.env["product.product"].create(
            {"name": "Capped", "is_storable": True, "uom_id": self.uom_unit.id}
        )
        category = self.env["stock.storage.category"].create(
            {
                "name": "Twelve units",
                "product_capacity_ids": [
                    (0, 0, {"product_id": product.id, "quantity": 12.0})
                ],
            }
        )
        zone = self.env["stock.location"].create(
            {
                "name": "Capped Zone",
                "usage": "internal",
                "location_id": self.warehouse_1.view_location_id.id,
            }
        )
        shelf = self.env["stock.location"].create(
            {
                "name": "Capped Shelf",
                "usage": "internal",
                "location_id": zone.id,
                "storage_category_id": category.id,
            }
        )
        self.env["stock.putaway.rule"].create(
            {
                "product_id": product.id,
                "location_in_id": zone.id,
                "location_out_id": zone.id,
                "storage_category_id": category.id,
                "sublocation": "closest_location",
            }
        )
        self.env["stock.quant"]._update_available_quantity(product, shelf, 6.0)

        move = self.env["stock.move"].create(
            {
                "product_id": product.id,
                "product_uom_id": self.uom_dozen.id,
                "product_uom_qty": 1.0,
                "location_id": self.supplier_location.id,
                "location_dest_id": zone.id,
                "picking_type_id": self.warehouse_1.in_type_id.id,
            }
        )
        move._action_confirm()
        move._action_assign()

        self.assertEqual(move.move_line_ids.quantity_product_uom, 12.0)
        self.assertNotEqual(
            move.move_line_ids.location_dest_id,
            shelf,
            "a dozen is twelve units against a shelf that has room for six,"
            " whatever unit the line is written in",
        )

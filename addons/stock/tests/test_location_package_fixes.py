# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Regression tests for location/putaway/package/lot/product peripheral-model fixes."""

from psycopg.errors import UniqueViolation

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.stock.tests.common import TestStockCommon


@tagged("post_install", "-at_install")
class TestLocationPackageFixes(TestStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Package = cls.env["stock.package"]
        cls.Quant = cls.env["stock.quant"]

    def _make_full_package(self, name, product, location, qty=5.0):
        package = self.Package.create({"name": name})
        self.Quant._update_available_quantity(
            product, location, qty, package_id=package
        )
        return package

    # ------------------------------------------------------------
    # stock.package.write per-record location guards
    # ------------------------------------------------------------

    def test_package_write_location_guards_per_record(self):
        pkg_full = self._make_full_package("PKG-FULL", self.productA, self.shelf_1)
        pkg_empty = self.Package.create({"name": "PKG-EMPTY"})
        batch = pkg_full | pkg_empty

        # Clearing the location of a mixed batch used to slip through the
        # any()-based guard and null the location of the non-empty package.
        with self.assertRaises(UserError):
            batch.write({"location_id": False})

        # Moving a batch containing an empty package is still refused.
        with self.assertRaises(UserError):
            batch.write({"location_id": self.shelf_2.id})

        # The per-record guards keep the valid single-purpose writes working.
        pkg_empty.write({"location_id": False})
        pkg_full.write({"location_id": self.shelf_2.id})
        self.assertEqual(pkg_full.location_id, self.shelf_2)
        moved_quants = self.Quant._gather(
            self.productA, self.shelf_2, package_id=pkg_full, strict=True
        )
        self.assertEqual(sum(moved_quants.mapped("quantity")), 5.0)

    # ------------------------------------------------------------
    # storage-category capacity math
    # ------------------------------------------------------------

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

        # 0.1 + 0.2 accumulates to 0.30000000000000004; adding 0.1 must still
        # be accepted as exactly the 0.4 capacity (raw <= used to reject it).
        self.assertTrue(
            self.shelf_1._check_product_capacity(self.productA, 0.1, 0.1 + 0.2, 0.0)
        )
        # A location exactly at capacity is refused, even for quantity 0.
        self.assertFalse(
            self.shelf_1._check_product_capacity(self.productA, 0.0, 0.4, 0.0)
        )
        # Exceeding the capacity is refused.
        self.assertFalse(
            self.shelf_1._check_product_capacity(self.productA, 0.2, 0.3, 0.0)
        )

    def test_max_weight_zero_means_unlimited(self):
        category = self.env["stock.storage.category"].create(
            {"name": "Weight category", "max_weight": 0.0}
        )
        self.shelf_1.storage_category_id = category
        self.productB.weight = 5.0

        # max_weight = 0 used to be treated as a 0 kg capacity, rejecting any
        # weighted product from putaway suggestions.
        self.assertTrue(
            self.shelf_1._check_product_capacity(self.productB, 1.0, 0.0, 0.0)
        )

        # A configured max weight is still enforced, rounding-aware.
        category.max_weight = 4.0
        self.assertFalse(
            self.shelf_1._check_product_capacity(self.productB, 1.0, 0.0, 0.0)
        )
        category.max_weight = 5.0
        self.assertTrue(
            self.shelf_1._check_product_capacity(self.productB, 1.0, 0.0, 0.0000000001)
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

        self.assertTrue(self.shelf_1._check_package_capacity(package, 2, 0.0))
        # At capacity (including float noise around the boundary): refused.
        self.assertFalse(self.shelf_1._check_package_capacity(package, 3, 0.0))
        self.assertFalse(
            self.shelf_1._check_package_capacity(package, 2.9999999999, 0.0)
        )

    def test_check_new_product_policy_without_products_context(self):
        """The 'same' policy must answer, not crash, when neither a product nor
        the `products` context key is provided (package flows)."""
        package_type = self.env["stock.package.type"].create({"name": "Tote"})
        category = self.env["stock.storage.category"].create(
            {"name": "Same-product category", "allow_new_product": "same"}
        )
        self.shelf_2.storage_category_id = category
        package = self.Package.create(
            {"name": "PKG-POLICY", "package_type_id": package_type.id}
        )

        self.assertTrue(
            self.shelf_2._check_can_be_used(
                self.env["product.product"], package=package
            )
        )

    # ------------------------------------------------------------
    # stock.location active propagation
    # ------------------------------------------------------------

    def test_propagate_active_noop_keeps_archived_descendants(self):
        parent, child = self.StockLocationObj.create(
            [
                {"name": "Prop parent", "location_id": self.stock_location.id},
                {"name": "Prop child"},
            ]
        )
        child.location_id = parent
        child.active = False

        # A redundant write of the current value must not resurrect the child.
        parent.write({"active": True})
        self.assertFalse(child.active)

        # A real toggle still cascades to the whole subtree.
        parent.write({"active": False})
        self.assertFalse(parent.active)
        parent.write({"active": True})
        self.assertTrue(child.active)

    def test_replenish_conflict_includes_archived_ancestor(self):
        # Top-level tree: nesting under the warehouse stock location would
        # conflict with its own replenish_location flag straight away.
        parent, child = self.StockLocationObj.create(
            [
                {"name": "Replenish parent"},
                {"name": "Replenish child"},
            ]
        )
        child.location_id = parent
        parent.replenish_location = True
        parent.active = False  # cascades to child
        child.active = True  # reactivate the child only

        # The archived ancestor is still a replenish location: unarchiving it
        # later would reintroduce the overlap, so the conflict must be detected.
        with self.assertRaises(ValidationError):
            child.replenish_location = True

    # ------------------------------------------------------------
    # stock.package stored location/company recompute
    # ------------------------------------------------------------

    def test_package_info_recomputes_on_in_place_quant_update(self):
        package = self._make_full_package(
            "PKG-INFO", self.productC, self.shelf_1, qty=5.0
        )
        self.assertEqual(package.location_id, self.shelf_1)

        # Zero the quant in place: the quant_ids set does not change, only the
        # quantity does; the stored package location must still recompute.
        self.Quant._update_available_quantity(
            self.productC, self.shelf_1, -5.0, package_id=package
        )
        self.assertFalse(package.location_id)

    # ------------------------------------------------------------
    # stock.lot SQL uniqueness
    # ------------------------------------------------------------

    def test_lot_unique_sql_constraint(self):
        self.productA.tracking = "lot"
        self.env["stock.lot"].create(
            {"name": "LOT-UNIQ", "product_id": self.productA.id, "company_id": False}
        )
        self.env.flush_all()

        # ORM duplicates are rejected with a ValidationError before the INSERT
        # (`_check_duplicate_lot_keys`); NULLS NOT DISTINCT makes two
        # no-company rows collide too.
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

        # The SQL constraint remains as the race-proof backstop below the ORM.
        with (
            self.assertRaises(UniqueViolation),
            mute_logger("odoo.db.cursor"),
            self.env.cr.savepoint(),
        ):
            self.env.cr.execute(
                "INSERT INTO stock_lot (name, product_id) VALUES (%s, %s)",
                ("LOT-UNIQ", self.productA.id),
            )

        # A company-scoped lot colliding with a no-company one passes SQL
        # (NULL vs value stays distinct) and is caught by the Python constraint.
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.env["stock.lot"].create(
                {
                    "name": "LOT-UNIQ",
                    "product_id": self.productA.id,
                    "company_id": self.env.company.id,
                }
            )

    # ------------------------------------------------------------
    # product quantity search / inverse
    # ------------------------------------------------------------

    def test_search_qty_available_zero_branch(self):
        self.Quant._update_available_quantity(self.productD, self.shelf_1, 3.0)
        scoped = [("id", "in", (self.productD | self.productE).ids)]

        zero = self.ProductObj.search([("qty_available", "=", 0), *scoped])
        self.assertEqual(zero, self.productE)

        positive = self.ProductObj.search([("qty_available", ">", 0), *scoped])
        self.assertEqual(positive, self.productD)

        # <= includes both the stocked product (3 <= 3) and the zero one.
        at_most = self.ProductObj.search([("qty_available", "<=", 3), *scoped])
        self.assertEqual(at_most, self.productD | self.productE)

    def test_inverse_qty_available_negative_raises(self):
        with self.assertRaises(UserError):
            self.productE.qty_available = -3.0

    # ------------------------------------------------------------
    # stock.package.type sequence handling
    # ------------------------------------------------------------

    def test_package_type_write_falsy_sequence_code(self):
        package_type = self.env["stock.package.type"].create({"name": "No-seq type"})
        package_type.write({"sequence_code": False})
        # No bogus "Package Type Sequence False" sequence may be created.
        self.assertFalse(package_type.sequence_id)

    # ------------------------------------------------------------
    # stock.scrap default location tiebreak
    # ------------------------------------------------------------

    def test_scrap_location_default_designation(self):
        """The flagless scrap default is the company's lowest-id inventory-loss
        location; a dedicated location is designated through the company-scoped
        external id, not by its (locale-dependent) name."""
        company = self.env.company
        adjustment = self.StockLocationObj.search(
            [("company_id", "=", company.id), ("usage", "=", "inventory")],
            order="id",
            limit=1,
        )
        scrap_wo_designated = self.env["stock.scrap"].create(
            {"product_id": self.productA.id, "company_id": company.id}
        )
        self.assertEqual(scrap_wo_designated.scrap_location_id, adjustment)

        # A location named 'Scrap' no longer wins by name alone.
        scrap_location = self.StockLocationObj.create(
            {"name": "Scrap", "usage": "inventory", "company_id": company.id}
        )
        scrap_w_named = self.env["stock.scrap"].create(
            {"product_id": self.productA.id, "company_id": company.id}
        )
        self.assertEqual(scrap_w_named.scrap_location_id, adjustment)

        # Tagging it with the company-scoped external id designates it.
        self.env["ir.model.data"].create(
            {
                "module": "stock",
                "name": f"stock_location_scrap_company_{company.id}",
                "model": "stock.location",
                "res_id": scrap_location.id,
            }
        )
        scrap_w_designated = self.env["stock.scrap"].create(
            {"product_id": self.productA.id, "company_id": company.id}
        )
        self.assertEqual(scrap_w_designated.scrap_location_id, scrap_location)

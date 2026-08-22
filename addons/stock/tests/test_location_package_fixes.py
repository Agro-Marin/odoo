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

    def test_package_write_location_guards_per_record(self):
        pkg_full = self._make_full_package("PKG-FULL", self.productA, self.shelf_1)
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
        self.assertFalse(
            self.shelf_1._can_store_product(self.productA, 0.0, 0.4, 0.0)
        )
        self.assertFalse(
            self.shelf_1._can_store_product(self.productA, 0.2, 0.3, 0.0)
        )

    def test_max_weight_zero_means_unlimited(self):
        category = self.env["stock.storage.category"].create(
            {"name": "Weight category", "max_weight": 0.0}
        )
        self.shelf_1.storage_category_id = category
        self.productB.weight = 5.0

        self.assertTrue(
            self.shelf_1._can_store_product(self.productB, 1.0, 0.0, 0.0)
        )

        category.max_weight = 4.0
        self.assertFalse(
            self.shelf_1._can_store_product(self.productB, 1.0, 0.0, 0.0)
        )
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
        self.assertFalse(
            self.shelf_1._can_store_package(package, 2.9999999999, 0.0)
        )

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
            self.shelf_2._can_be_used(
                self.env["product.product"], package=package
            )
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
        package = self._make_full_package(
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
        scrap_wo_designated = self.env["stock.scrap"].create(
            {"product_id": self.productA.id, "company_id": company.id}
        )
        self.assertEqual(scrap_wo_designated.scrap_location_id, adjustment)

        scrap_location = self.StockLocationObj.create(
            {"name": "Scrap", "usage": "inventory", "company_id": company.id}
        )
        scrap_w_named = self.env["stock.scrap"].create(
            {"product_id": self.productA.id, "company_id": company.id}
        )
        self.assertEqual(scrap_w_named.scrap_location_id, adjustment)

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

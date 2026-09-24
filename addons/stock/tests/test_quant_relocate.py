from odoo.tests import tagged

from odoo.addons.stock.tests.common import TestStockCommon


@tagged("post_install", "-at_install")
class TestQuantRelocateWizard(TestStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Quant = cls.env["stock.quant"]
        cls.Wizard = cls.env["stock.quant.relocate"]
        cls.loc = cls.stock_location

    def _packed_quants(self, tag, packages, per_package):
        product = self.env["product.product"].create(
            {"name": f"qrel-{tag}", "is_storable": True, "tracking": "lot"}
        )
        lots = self.env["stock.lot"].create(
            [
                {"name": f"qrel-{tag}-l{index}", "product_id": product.id}
                for index in range(per_package)
            ]
        )
        pkgs = self.env["stock.package"].create(
            [{"name": f"qrel-{tag}-p{index}"} for index in range(packages)]
        )
        self.Quant.create(
            [
                {
                    "product_id": product.id,
                    "location_id": self.loc.id,
                    "lot_id": lot.id,
                    "package_id": package.id,
                    "quantity": 1.0,
                }
                for package in pkgs
                for lot in lots
            ]
        )
        self.env.flush_all()
        return pkgs

    def test_a_whole_package_selection_is_not_partial(self):
        pkgs = self._packed_quants("whole", packages=2, per_package=3)
        wizard = self.Wizard.create({"quant_ids": [(6, 0, pkgs.quant_ids.ids)]})
        self.assertFalse(wizard.is_partial_package)
        self.assertFalse(wizard.partial_package_names)

    def test_a_partial_package_is_named(self):
        pkgs = self._packed_quants("partial", packages=2, per_package=3)
        selection = pkgs[0].quant_ids[:2] | pkgs[1].quant_ids
        wizard = self.Wizard.create({"quant_ids": [(6, 0, selection.ids)]})
        self.assertTrue(wizard.is_partial_package)
        self.assertEqual(wizard.partial_package_names, pkgs[0].display_name)

    def test_loose_quants_are_never_partial(self):
        product = self.env["product.product"].create(
            {"name": "qrel-loose", "is_storable": True}
        )
        self.Quant._update_available_quantity(product, self.loc, quantity=5)
        self.env.flush_all()
        quants = self.Quant.search(
            [("product_id", "=", product.id), ("location_id", "=", self.loc.id)]
        )
        wizard = self.Wizard.create({"quant_ids": [(6, 0, quants.ids)]})
        self.assertFalse(
            wizard.is_partial_package, "stock in no package breaks no package open"
        )

    def test_the_partial_package_answer_does_not_cost_the_square_of_the_selection(self):
        import time

        def measure(tag, packages, per_package):
            pkgs = self._packed_quants(tag, packages, per_package)
            wizard = self.Wizard.create({"quant_ids": [(6, 0, pkgs.quant_ids.ids)]})
            self.env.flush_all()
            wizard.quant_ids.mapped("package_id.quant_ids")
            wizard.invalidate_recordset(["is_partial_package", "partial_package_names"])
            started = time.perf_counter()
            _ = wizard.is_partial_package
            return time.perf_counter() - started

        small = measure("small", packages=4, per_package=25)
        large = measure("large", packages=40, per_package=25)
        self.assertLess(
            large,
            max(small, 1e-4) * 25,
            f"a 10x selection cost {large / max(small, 1e-9):.0f}x the time; the "
            "membership set has to be hoisted out of the filter",
        )

    def test_a_lot_keeps_the_packages_it_owns_outright(self):
        product = self.env["product.product"].create(
            {"name": "qrel-lot-own", "is_storable": True, "tracking": "lot"}
        )
        lot = self.env["stock.lot"].create(
            {"name": "qrel-lot-own-l", "product_id": product.id}
        )
        first, second = self.env["stock.package"].create(
            [{"name": "qrel-own-a"}, {"name": "qrel-own-b"}]
        )
        for package in (first, second):
            self.Quant._update_available_quantity(
                product, self.loc, quantity=1, lot_id=lot, package_id=package
            )
        self.env.flush_all()
        destination = self.env["stock.location"].create(
            {
                "name": "qrel-own-dest",
                "usage": "internal",
                "location_id": self.loc.id,
            }
        )

        lot.location_id = destination
        self.env.flush_all()
        self.env.invalidate_all()

        moved = self.Quant.search(
            [("product_id", "=", product.id), ("location_id", "=", destination.id)]
        )
        self.assertEqual(sum(moved.mapped("quantity")), 2.0)
        self.assertEqual(
            moved.package_id,
            first | second,
            "both packages held nothing but this lot, so both travel intact",
        )

    def test_a_lot_leaves_a_package_it_shares(self):
        product = self.env["product.product"].create(
            {"name": "qrel-lot-share", "is_storable": True, "tracking": "lot"}
        )
        neighbour = self.env["product.product"].create(
            {"name": "qrel-lot-share-n", "is_storable": True}
        )
        lot = self.env["stock.lot"].create(
            {"name": "qrel-lot-share-l", "product_id": product.id}
        )
        package = self.env["stock.package"].create({"name": "qrel-share"})
        self.Quant._update_available_quantity(
            product, self.loc, quantity=1, lot_id=lot, package_id=package
        )
        self.Quant._update_available_quantity(
            neighbour, self.loc, quantity=1, package_id=package
        )
        self.env.flush_all()
        destination = self.env["stock.location"].create(
            {
                "name": "qrel-share-dest",
                "usage": "internal",
                "location_id": self.loc.id,
            }
        )

        lot.location_id = destination
        self.env.flush_all()
        self.env.invalidate_all()

        moved = self.Quant.search(
            [("product_id", "=", product.id), ("location_id", "=", destination.id)]
        )
        self.assertEqual(sum(moved.mapped("quantity")), 1.0)
        self.assertFalse(
            moved.package_id,
            "the package stays behind with the neighbour that was not moved",
        )

    def test_the_predicate_has_one_definition(self):
        import inspect

        from odoo.addons.stock.models import stock_lot
        from odoo.addons.stock.wizards import stock_quant_relocate

        for module in (stock_lot, stock_quant_relocate):
            source = inspect.getsource(module)
            self.assertIn("_filtered_breaking_a_package", source)
            self.assertNotIn(
                "package_id.quant_ids)",
                source,
                f"{module.__name__} must reach the package-completeness test "
                "through stock.quant, not re-spell it",
            )

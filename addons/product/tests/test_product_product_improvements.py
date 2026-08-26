from odoo.exceptions import ValidationError
from odoo.tests import tagged

from odoo.addons.product.tests.common import ProductCommon


@tagged("post_install", "-at_install")
class TestProductProductImprovements(ProductCommon):

    def test_name_search_unlimited_reaches_the_name_branch(self):
        template = self.env["product.template"].create(
            {
                "name": "ZeroLimitProbe",
                "list_price": 5.0,
            }
        )
        product = template.product_variant_id
        product.default_code = "ZLP-REF"

        Product = self.env["product.product"]
        found_none = dict(
            Product.name_search(name="ZeroLimitProbe", operator="ilike", limit=None)
        )
        found_zero = Product.name_search(
            name="ZeroLimitProbe", operator="ilike", limit=0
        )

        self.assertIn(
            product.id,
            found_none,
            "an unlimited name_search must reach the name branch",
        )
        self.assertEqual(
            found_zero,
            [],
            "a zero limit asks for no rows here exactly as it does on every"
            " other model",
        )
        self.assertEqual(
            found_zero,
            self.env["product.category"].name_search(name="no such category", limit=0),
            "sanity: the generic name_search answers a zero limit the same way",
        )

    def test_name_search_limit_zero_reaches_every_branch(self):
        """limit=0 is normalised once, so no branch of the method sees LIMIT 0."""
        template = self.env["product.template"].create(
            {
                "name": "EveryBranchProbe",
                "list_price": 1.0,
                "default_code": "EBP-CODE",
                "barcode": "EBP-BAR",
            }
        )
        product = template.product_variant_id
        partner = self.env["res.partner"].create({"name": "Every Branch Supplier"})
        self.env["product.supplierinfo"].create(
            {
                "partner_id": partner.id,
                "product_code": "EBP-SUPPLIER",
                "product_tmpl_id": template.id,
            }
        )
        Product = self.env["product.product"].with_context(partner_id=partner.id)

        for term, branch in (
            ("EBP-CODE", "default_code exact match"),
            ("EBP-BAR", "barcode exact match"),
            ("EveryBranchProbe", "name match"),
            ("EBP-SUPPLIER", "supplier-info fallback"),
        ):
            with self.subTest(branch=branch):
                bounded = dict(
                    Product.name_search(name=term, operator="ilike", limit=100)
                )
                unlimited = dict(
                    Product.name_search(name=term, operator="ilike", limit=0)
                )
                self.assertIn(
                    product.id, bounded, f"sanity: {branch} works when bounded"
                )
                self.assertIn(
                    product.id,
                    unlimited,
                    f"{branch} must survive limit=0, which means unlimited here",
                )

    def test_name_search_limit_positive_still_bounded(self):
        self.env["product.template"].create(
            [{"name": f"BoundProbe {i}", "list_price": 1.0} for i in range(3)]
        )
        res = self.env["product.product"].name_search(
            name="BoundProbe",
            operator="ilike",
            limit=2,
        )
        self.assertEqual(len(res), 2)

    def test_negative_standard_price_write_rejected(self):
        with self.assertRaises(ValidationError):
            self.product.standard_price = -1.0
            self.product.flush_recordset()

    def test_negative_standard_price_create_rejected(self):
        with self.assertRaises(ValidationError):
            self.env["product.product"].create(
                {
                    "name": "NegativeCost",
                    "standard_price": -50.0,
                }
            ).flush_recordset()

    def test_zero_and_positive_standard_price_allowed(self):
        self.product.standard_price = 0.0
        self.product.flush_recordset()
        self.product.standard_price = 12.5
        self.product.flush_recordset()
        self.assertEqual(self.product.standard_price, 12.5)

    def _import(self, rows):
        fields = ["name", "list_price", "import_attribute_values"]
        return self.env["product.product"].load(fields, rows)

    def test_import_creates_variants_with_attribute_values(self):
        rows = [
            ["ImportTee", "20", "Color:Red,Size:S"],
            ["ImportTee", "20", "Color:Red,Size:M"],
            ["ImportTee", "20", "Color:Blue,Size:S"],
        ]
        result = self._import(rows)
        self.assertFalse(
            [m for m in result["messages"] if m.get("type") == "error"],
            result["messages"],
        )
        template = self.env["product.template"].search([("name", "=", "ImportTee")])
        self.assertEqual(len(template), 1)
        self.assertEqual(len(template.product_variant_ids), 3)
        self.assertEqual(
            sorted(template.product_variant_ids.mapped("import_attribute_values")),
            sorted(["Color:Red,Size:S", "Color:Red,Size:M", "Color:Blue,Size:S"]),
        )
        self.assertEqual(
            set(template.attribute_line_ids.attribute_id.mapped("name")),
            {"Color", "Size"},
        )

    def test_import_reuses_existing_template_and_attributes(self):
        self._import([["ReuseTee", "10", "Color:Green,Size:S"]])
        template = self.env["product.template"].search([("name", "=", "ReuseTee")])
        attr_ids_before = set(self.env["product.attribute"].search([]).ids)

        result = self._import([["ReuseTee", "10", "Color:Red,Size:L"]])
        self.assertFalse(
            [m for m in result["messages"] if m.get("type") == "error"],
            result["messages"],
        )
        template.invalidate_recordset()
        self.assertEqual(len(template.product_variant_ids), 2)
        colors = self.env["product.attribute"].search([("name", "=", "Color")])
        sizes = self.env["product.attribute"].search([("name", "=", "Size")])
        self.assertEqual(len(colors), 1)
        self.assertEqual(len(sizes), 1)
        self.assertLessEqual(
            len(attr_ids_before),
            len(self.env["product.attribute"].search([]).ids),
        )

# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.exceptions import ValidationError
from odoo.tests import tagged

from odoo.addons.product.tests.common import ProductCommon


@tagged("post_install", "-at_install")
class TestProductProductImprovements(ProductCommon):
    """Locks down the fork-specific fixes on ``product.product``:

    * ``name_search`` must honour ``limit=0`` as "unlimited";
    * a negative ``standard_price`` must be rejected by a constraint (not only
      the onchange);
    * the decomposed ``_load_records_create`` import path keeps producing the
      same variants + attribute values as before the refactor.
    """

    # -- name_search(limit=0) -------------------------------------------------

    def test_name_search_limit_zero_returns_name_matches(self):
        """limit=0 means unlimited; a name-only match must still be returned."""
        template = self.env["product.template"].create(
            {
                "name": "ZeroLimitProbe",
                "list_price": 5.0,
            }
        )
        product = template.product_variant_id
        # Force the name branch: the record has NO default_code/barcode equal to
        # the search term, so it can only be found by name.
        product.default_code = "ZLP-REF"

        found_none = dict(
            self.env["product.product"].name_search(
                name="ZeroLimitProbe",
                operator="ilike",
                limit=None,
            )
        )
        found_zero = dict(
            self.env["product.product"].name_search(
                name="ZeroLimitProbe",
                operator="ilike",
                limit=0,
            )
        )

        self.assertIn(product.id, found_none, "sanity: unlimited search finds it")
        self.assertIn(
            product.id,
            found_zero,
            "limit=0 must behave like unlimited, not skip the name search",
        )

    def test_name_search_limit_positive_still_bounded(self):
        """A positive limit must still cap results (no regression)."""
        self.env["product.template"].create(
            [{"name": f"BoundProbe {i}", "list_price": 1.0} for i in range(3)]
        )
        res = self.env["product.product"].name_search(
            name="BoundProbe",
            operator="ilike",
            limit=2,
        )
        self.assertEqual(len(res), 2)

    # -- negative standard_price constraint -----------------------------------

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
        # Must NOT raise: zero and positive are valid costs.
        self.product.standard_price = 0.0
        self.product.flush_recordset()
        self.product.standard_price = 12.5
        self.product.flush_recordset()
        self.assertEqual(self.product.standard_price, 12.5)

    # -- _load_records_create decomposition (behaviour preserving) ------------

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
        # attributes + values were created on demand
        self.assertEqual(
            set(template.attribute_line_ids.attribute_id.mapped("name")),
            {"Color", "Size"},
        )

    def test_import_reuses_existing_template_and_attributes(self):
        # First import creates everything.
        self._import([["ReuseTee", "10", "Color:Green,Size:S"]])
        template = self.env["product.template"].search([("name", "=", "ReuseTee")])
        attr_ids_before = set(self.env["product.attribute"].search([]).ids)

        # Second import on the SAME template with a new combination must add a
        # variant, reuse the Color/Size attributes, and only create the missing
        # value ("Green" already exists, "L"/"Red" are new).
        result = self._import([["ReuseTee", "10", "Color:Red,Size:L"]])
        self.assertFalse(
            [m for m in result["messages"] if m.get("type") == "error"],
            result["messages"],
        )
        template.invalidate_recordset()
        self.assertEqual(len(template.product_variant_ids), 2)
        # No duplicate Color/Size attributes were spawned.
        colors = self.env["product.attribute"].search([("name", "=", "Color")])
        sizes = self.env["product.attribute"].search([("name", "=", "Size")])
        self.assertEqual(len(colors), 1)
        self.assertEqual(len(sizes), 1)
        self.assertLessEqual(
            len(attr_ids_before),
            len(self.env["product.attribute"].search([]).ids),
        )

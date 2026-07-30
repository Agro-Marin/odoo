"""Tests for account.tax company filtering, price fixing and description helpers."""

from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import BaseTaxCommon


@tagged("post_install", "-at_install")
class TestFilterTaxesByCompany(BaseTaxCommon):
    """Company-hierarchy walk of _filter_taxes_by_company."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.child_company = cls.env["res.company"].create(
            {"name": "BT child company", "parent_id": cls.company.id},
        )

    def test_empty_recordset_short_circuits(self):
        """An empty recordset is returned as-is, no company walk."""
        taxes = self.env["account.tax"]
        self.assertEqual(taxes._filter_taxes_by_company(self.child_company), taxes)

    def test_direct_company_match(self):
        """A tax of the given company is kept on the first iteration."""
        tax = self._tax(21.0)
        self.assertEqual(tax._filter_taxes_by_company(self.company), tax)

    def test_child_company_falls_back_to_parent(self):
        """With no child-company taxes the walk climbs to the parent company."""
        tax = self._tax(21.0)
        self.assertEqual(tax._filter_taxes_by_company(self.child_company), tax)


@tagged("post_install", "-at_install")
class TestFixTaxIncludedPrice(BaseTaxCommon):
    """Price adjustment when product-included taxes do not apply to the line."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.child_company = cls.env["res.company"].create(
            {"name": "BT fix-price child company", "parent_id": cls.company.id},
        )

    def test_included_tax_removed_when_not_on_line(self):
        """Dropping a price-included product tax strips it from the price."""
        incl_tax = self._tax(21.0, price_include_override="tax_included")
        Tax = self.env["account.tax"]
        price = Tax._fix_tax_included_price(121.0, incl_tax, Tax)
        self.assertAlmostEqual(price, 100.0, places=2)

    def test_price_untouched_when_tax_still_applies(self):
        """A product tax also present on the line leaves the price alone."""
        incl_tax = self._tax(21.0, price_include_override="tax_included")
        Tax = self.env["account.tax"]
        price = Tax._fix_tax_included_price(121.0, incl_tax, incl_tax)
        self.assertEqual(price, 121.0)

    def test_price_untouched_for_exclusive_product_tax(self):
        """A price-excluded product tax never adjusts the price."""
        excl_tax = self._tax(21.0)
        Tax = self.env["account.tax"]
        price = Tax._fix_tax_included_price(100.0, excl_tax, Tax)
        self.assertEqual(price, 100.0)

    def test_company_variant_filters_other_company_taxes(self):
        """The company variant ignores taxes from other companies."""
        incl_tax = self._tax(21.0, price_include_override="tax_included")
        Tax = self.env["account.tax"]
        price = Tax._fix_tax_included_price_company(
            121.0, incl_tax, Tax, self.child_company
        )
        self.assertEqual(price, 121.0)


@tagged("post_install", "-at_install")
class TestDescriptionPlaintext(BaseTaxCommon):
    """HTML description flattening of _get_description_plaintext."""

    def test_description_plaintext_strips_html(self):
        tax = self._tax(21.0, description="<p>21% &amp; surcharges</p>")
        self.assertEqual(tax._get_description_plaintext(), "21% & surcharges")

    def test_description_plaintext_empty_html(self):
        tax = self._tax(21.0, description="<p><br/></p>")
        self.assertEqual(tax._get_description_plaintext(), "")


@tagged("post_install", "-at_install")
class TestRepartitionValidationBranches(BaseTaxCommon):
    """Repartition constraint branches not covered by the base suite."""

    def test_repartition_without_tax_line_rejected(self):
        """Both distributions keep equal counts but lose their tax line."""
        tax = self._tax(10.0)
        invoice_tax_line = tax.invoice_repartition_line_ids.filtered(
            lambda line: line.repartition_type == "tax"
        )
        refund_tax_line = tax.refund_repartition_line_ids.filtered(
            lambda line: line.repartition_type == "tax"
        )
        with self.assertRaises(ValidationError):
            tax.write(
                {
                    "invoice_repartition_line_ids": [
                        Command.unlink(invoice_tax_line.id)
                    ],
                    "refund_repartition_line_ids": [Command.unlink(refund_tax_line.id)],
                }
            )

    def test_repartition_negative_factors_must_total_minus_100(self):
        """Matching -50% lines on both sides still fail the -100% total."""
        tax = self._tax(10.0)
        with self.assertRaises(ValidationError):
            tax.write(
                {
                    "invoice_repartition_line_ids": [
                        Command.create(
                            {"repartition_type": "tax", "factor_percent": -50.0}
                        )
                    ],
                    "refund_repartition_line_ids": [
                        Command.create(
                            {"repartition_type": "tax", "factor_percent": -50.0}
                        )
                    ],
                }
            )

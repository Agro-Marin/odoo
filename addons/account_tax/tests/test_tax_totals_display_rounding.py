from types import SimpleNamespace

from odoo import Command
from odoo.tests import tagged

from .common import BaseTaxCommon


@tagged("post_install", "-at_install")
class TestTaxTotalsSummaryBranches(BaseTaxCommon):
    def _totals(self, base_lines, cash_rounding=None):
        Tax = self.env["account.tax"]
        for base_line in base_lines:
            Tax._add_tax_details_in_base_line(base_line, self.company)
        Tax._round_base_lines_tax_details(base_lines, self.company)
        return Tax._get_tax_totals_summary(
            base_lines, self.currency, self.company, cash_rounding=cash_rounding
        )

    def test_fixed_taxes_group_hides_display_base(self):
        fixed = self._tax(5.0, amount_type="fixed")
        totals = self._totals([self._base_line(fixed, 100.0)])

        group = totals["subtotals"][0]["tax_groups"][0]
        self.assertIs(group["display_base_amount"], False)
        self.assertIs(group["display_base_amount_currency"], False)
        self.assertAlmostEqual(group["tax_amount"], 5.0, places=2)

    def test_division_included_taxes_display_tax_inclusive_base(self):
        division = self._tax(
            21.0, amount_type="division", price_include_override="tax_included"
        )
        totals = self._totals([self._base_line(division, 100.0)])

        group = totals["subtotals"][0]["tax_groups"][0]
        self.assertAlmostEqual(group["base_amount"], 79.0, places=2)
        self.assertAlmostEqual(group["tax_amount"], 21.0, places=2)
        self.assertAlmostEqual(group["display_base_amount"], 100.0, places=2)

    def test_cash_rounding_add_invoice_line_adjusts_base(self):
        tax = self._tax(21.0)
        rounding = SimpleNamespace(
            strategy="add_invoice_line", rounding=0.05, rounding_method="HALF-UP"
        )
        totals = self._totals([self._base_line(tax, 99.99)], cash_rounding=rounding)

        self.assertAlmostEqual(totals["cash_rounding_base_amount"], 0.01, places=2)
        self.assertAlmostEqual(totals["base_amount"], 99.99, places=2)
        self.assertAlmostEqual(totals["total_amount"], 121.00, places=2)

    def test_cash_rounding_biggest_tax_adjusts_largest_group(self):
        group_small = self.env["account.tax.group"].create(
            {
                "name": "BT small group",
                "company_ids": [Command.set(self.company.ids)],
                "country_id": self.country.id,
            },
        )
        big_tax = self._tax(21.0)
        small_tax = self._tax(5.0, tax_group_id=group_small.id)
        rounding = SimpleNamespace(
            strategy="biggest_tax", rounding=0.05, rounding_method="HALF-UP"
        )
        totals = self._totals(
            [self._base_line(big_tax, 100.0), self._base_line(small_tax, 0.99)],
            cash_rounding=rounding,
        )

        groups = {
            g["group_name"]: g for s in totals["subtotals"] for g in s["tax_groups"]
        }
        self.assertAlmostEqual(
            groups[self.tax_group.name]["tax_amount"], 21.01, places=2
        )
        self.assertAlmostEqual(groups["BT small group"]["tax_amount"], 0.05, places=2)
        self.assertAlmostEqual(totals["tax_amount"], 21.06, places=2)
        self.assertAlmostEqual(totals["total_amount"], 122.05, places=2)

    def test_cash_rounding_special_line_reported_apart(self):
        tax = self._tax(21.0)
        line = self._base_line(tax, 100.0)
        rounding_line = self._base_line(
            self.env["account.tax"], 0.02, special_type="cash_rounding"
        )
        totals = self._totals([line, rounding_line])

        self.assertAlmostEqual(totals["cash_rounding_base_amount"], 0.02, places=2)
        self.assertAlmostEqual(totals["tax_amount"], 21.0, places=2)

    def test_cash_rounding_zero_total_does_not_raise(self):
        tax = self._tax(21.0)
        rounding = SimpleNamespace(
            strategy="add_invoice_line", rounding=0.05, rounding_method="HALF-UP"
        )

        totals = self._totals([self._base_line(tax, 0.0)], cash_rounding=rounding)

        self.assertAlmostEqual(
            totals.get("cash_rounding_base_amount", 0.0), 0.0, places=2
        )

    def test_non_deductible_line_reduces_tax_group(self):
        tax = self._tax(21.0)
        deductible = self._base_line(tax, 100.0)
        non_deductible = self._base_line(tax, 50.0, special_type="non_deductible")
        totals = self._totals([deductible, non_deductible])

        group = totals["subtotals"][0]["tax_groups"][0]
        self.assertAlmostEqual(group["non_deductible_tax_amount"], 10.5, places=2)
        self.assertAlmostEqual(group["tax_amount"], 21.0, places=2)

from odoo.tests import tagged

from .common import BaseTaxCommon


@tagged("post_install", "-at_install")
class TestTaxMultiCurrency(BaseTaxCommon):
    """F013: no test in this suite ever used a currency other than the
    company's own, so nothing here would catch a regression that conflates
    `*_currency` (line-currency) and non-suffixed (company-currency) fields."""

    def _foreign_currency(self):
        foreign = self.env.ref("base.EUR")
        if foreign == self.currency:
            foreign = self.env.ref("base.USD")
        return foreign

    def test_tax_amount_currency_diverges_from_company_currency(self):
        tax = self._tax(21.0)
        Tax = self.env["account.tax"]
        foreign = self._foreign_currency()

        # rate: units of `foreign` per unit of company currency, matching the
        # convention `_add_tax_details_in_base_line` divides by (company
        # amount = currency amount / rate).
        base_line = self._base_line(tax, 100.0, currency_id=foreign, rate=2.0)
        Tax._add_tax_details_in_base_line(base_line, self.company)
        Tax._round_base_lines_tax_details([base_line], self.company)

        totals = Tax._get_tax_totals_summary([base_line], foreign, self.company)

        self.assertAlmostEqual(totals["tax_amount_currency"], 21.0, places=2)
        self.assertAlmostEqual(totals["tax_amount"], 10.5, places=2)
        self.assertAlmostEqual(totals["base_amount_currency"], 100.0, places=2)
        self.assertAlmostEqual(totals["base_amount"], 50.0, places=2)

    def test_rate_of_one_keeps_both_fields_equal(self):
        """Edge case: rate == 1.0 (the default) must leave `*_currency` and
        company-currency fields numerically identical even with a distinct
        `currency_id`, since the two currencies are still 1:1 for this line."""
        tax = self._tax(21.0)
        Tax = self.env["account.tax"]
        foreign = self._foreign_currency()

        base_line = self._base_line(tax, 100.0, currency_id=foreign, rate=1.0)
        Tax._add_tax_details_in_base_line(base_line, self.company)
        Tax._round_base_lines_tax_details([base_line], self.company)

        totals = Tax._get_tax_totals_summary([base_line], foreign, self.company)
        self.assertAlmostEqual(
            totals["tax_amount_currency"], totals["tax_amount"], places=2
        )

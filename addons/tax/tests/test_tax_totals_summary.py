from odoo import Command
from odoo.tests import tagged

from .common import BaseTaxCommon


@tagged("post_install", "-at_install")
class TestBaseTaxTotalsSummary(BaseTaxCommon):
    def _summary_for(self, base_lines):
        tax_model = self.env["account.tax"]
        for base_line in base_lines:
            tax_model._add_tax_details_in_base_line(
                base_line, self.company, rounding_method="round_per_line"
            )
        tax_model._round_base_lines_tax_details(base_lines, self.company)
        return tax_model._get_tax_totals_summary(
            base_lines, self.currency, self.company
        )

    def _second_group(self, name):
        return self.env["account.tax.group"].create(
            {
                "name": name,
                "company_ids": [Command.set(self.company.ids)],
                "country_id": self.country.id,
            }
        )

    def test_summary_aggregates_two_tax_groups(self):
        group_b = self._second_group("group B")
        tax_a = self._tax(21.0)
        tax_b = self._tax(10.0, tax_group_id=group_b.id)
        base_lines = [self._base_line(tax_a, 100.0), self._base_line(tax_b, 100.0)]
        totals = self._summary_for(base_lines)
        self.assertAlmostEqual(totals["base_amount"], 200.0, places=2)
        self.assertAlmostEqual(totals["tax_amount"], 31.0, places=2)
        group_ids = {
            tax_group["id"]
            for subtotal in totals["subtotals"]
            for tax_group in subtotal["tax_groups"]
        }
        self.assertEqual(group_ids, {self.tax_group.id, group_b.id})

    def test_exclude_tax_group_folds_amount_into_base(self):
        group_b = self._second_group("group B excl")
        tax_a = self._tax(21.0)
        tax_b = self._tax(10.0, tax_group_id=group_b.id)
        base_lines = [self._base_line(tax_a, 100.0), self._base_line(tax_b, 100.0)]
        tax_model = self.env["account.tax"]
        totals = self._summary_for(base_lines)
        base_before = totals["base_amount"]
        tax_before = totals["tax_amount"]

        excluded = tax_model._exclude_tax_groups_from_tax_totals_summary(
            totals, [group_b.id]
        )

        self.assertAlmostEqual(excluded["base_amount"], base_before + 10.0, places=2)
        self.assertAlmostEqual(excluded["tax_amount"], tax_before - 10.0, places=2)
        remaining = {
            tax_group["id"]
            for subtotal in excluded["subtotals"]
            for tax_group in subtotal["tax_groups"]
        }
        self.assertEqual(remaining, {self.tax_group.id})

    def test_exclude_all_tax_groups_collapses_subtotals(self):
        group_b = self._second_group("group B exclude all")
        tax_a = self._tax(21.0)
        tax_b = self._tax(10.0, tax_group_id=group_b.id)
        base_lines = [self._base_line(tax_a, 100.0), self._base_line(tax_b, 100.0)]
        tax_model = self.env["account.tax"]
        totals = self._summary_for(base_lines)

        excluded = tax_model._exclude_tax_groups_from_tax_totals_summary(
            totals, [self.tax_group.id, group_b.id]
        )

        self.assertEqual(excluded["subtotals"], [])
        self.assertAlmostEqual(excluded["tax_amount"], 0.0, places=2)

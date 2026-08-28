from odoo.tests import tagged

from .common import BaseTaxCommon


@tagged("post_install", "-at_install")
class TestTaxCascadeSpecialModes(BaseTaxCommon):
    def _split(self, taxes, price_unit, special_mode=False):
        AccountTax = self.env["account.tax"]
        base_line = self._base_line(taxes, price_unit, special_mode=special_mode)
        AccountTax._add_tax_details_in_base_lines([base_line], self.company)
        AccountTax._round_base_lines_tax_details([base_line], self.company)
        tax_details = base_line["tax_details"]
        return (
            tax_details["total_excluded_currency"],
            tax_details["total_included_currency"],
            [data["tax_amount_currency"] for data in tax_details["taxes_data"]],
        )

    def test_a_cascading_tax_widens_the_base_of_the_next_one(self):
        first = self._tax(10.0, include_base_amount=True, sequence=1)
        second = self._tax(10.0, sequence=2)
        self.assertEqual(
            self._split(first + second, 100.0), (100.0, 121.0, [10.0, 11.0])
        )

    def test_without_cascading_both_taxes_share_one_base(self):
        first = self._tax(10.0, sequence=1)
        second = self._tax(10.0, sequence=2)
        self.assertEqual(
            self._split(first + second, 100.0), (100.0, 120.0, [10.0, 10.0])
        )

    def test_the_taxed_total_recovers_the_same_split(self):
        first = self._tax(10.0, include_base_amount=True, sequence=1)
        second = self._tax(10.0, sequence=2)
        self.assertEqual(
            self._split(first + second, 121.0, special_mode="total_included"),
            (100.0, 121.0, [10.0, 11.0]),
        )

    def test_the_untaxed_total_recovers_the_same_split(self):
        first = self._tax(10.0, include_base_amount=True, sequence=1)
        second = self._tax(10.0, sequence=2)
        self.assertEqual(
            self._split(first + second, 100.0, special_mode="total_excluded"),
            (100.0, 121.0, [10.0, 11.0]),
        )

    def test_a_fixed_tax_is_removed_before_the_percentage_is_read_back(self):
        flat = self._tax(1.0, amount_type="fixed", sequence=1)
        percentage = self._tax(10.0, sequence=2)
        forward = self._split(flat + percentage, 110.0)
        self.assertEqual(forward, (110.0, 122.0, [1.0, 11.0]))
        self.assertEqual(
            self._split(flat + percentage, 122.0, special_mode="total_included"),
            forward,
        )

    def test_a_tax_can_opt_out_of_being_affected_by_the_previous_one(self):
        first = self._tax(10.0, include_base_amount=True, sequence=1)
        second = self._tax(10.0, sequence=2, is_base_affected=False)
        self.assertEqual(
            self._split(first + second, 100.0), (100.0, 120.0, [10.0, 10.0])
        )

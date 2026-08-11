from odoo.tests import tagged

from .common import BaseTaxCommon


@tagged("post_install", "-at_install")
class TestTaxCascadeSpecialModes(BaseTaxCommon):
    """Taxes charged on top of other taxes, read from either end.

    A tax flagged ``include_base_amount`` widens the base of the taxes after
    it. The engine has to reach the same split whether it is handed the
    untaxed amount, the taxed total, or neither -- documents arrive in all
    three shapes, and they have to agree to the cent.
    """

    def _split(self, taxes, price_unit, special_mode=False):
        """Return (untaxed, taxed, [tax amounts]) for a line."""
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
        """The second tax is charged on the first one's amount too.

        100 at 10% cascading gives 10, and the next 10% is charged on 110,
        giving 11 -- not another 10.
        """
        first = self._tax(10.0, include_base_amount=True, sequence=1)
        second = self._tax(10.0, sequence=2)
        self.assertEqual(
            self._split(first + second, 100.0), (100.0, 121.0, [10.0, 11.0])
        )

    def test_without_cascading_both_taxes_share_one_base(self):
        """Left un-flagged, the second tax ignores the first (negative)."""
        first = self._tax(10.0, sequence=1)
        second = self._tax(10.0, sequence=2)
        self.assertEqual(
            self._split(first + second, 100.0), (100.0, 120.0, [10.0, 10.0])
        )

    def test_the_taxed_total_recovers_the_same_split(self):
        """Handed 121 as a total, the engine reproduces 100 + 10 + 11."""
        first = self._tax(10.0, include_base_amount=True, sequence=1)
        second = self._tax(10.0, sequence=2)
        self.assertEqual(
            self._split(first + second, 121.0, special_mode="total_included"),
            (100.0, 121.0, [10.0, 11.0]),
        )

    def test_the_untaxed_total_recovers_the_same_split(self):
        """Stating the amount is already untaxed changes nothing here."""
        first = self._tax(10.0, include_base_amount=True, sequence=1)
        second = self._tax(10.0, sequence=2)
        self.assertEqual(
            self._split(first + second, 100.0, special_mode="total_excluded"),
            (100.0, 121.0, [10.0, 11.0]),
        )

    def test_a_fixed_tax_is_removed_before_the_percentage_is_read_back(self):
        """A flat charge ahead of a percentage survives the round trip.

        1 flat plus 10% on 110 totals 122; read back from 122 the flat
        charge has to come off first or the percentage lands wrong.
        """
        flat = self._tax(1.0, amount_type="fixed", sequence=1)
        percentage = self._tax(10.0, sequence=2)
        forward = self._split(flat + percentage, 110.0)
        self.assertEqual(forward, (110.0, 122.0, [1.0, 11.0]))
        self.assertEqual(
            self._split(flat + percentage, 122.0, special_mode="total_included"),
            forward,
        )

    def test_a_tax_can_opt_out_of_being_affected_by_the_previous_one(self):
        """A tax marked as unaffected keeps the original base (negative)."""
        first = self._tax(10.0, include_base_amount=True, sequence=1)
        second = self._tax(10.0, sequence=2, is_base_affected=False)
        self.assertEqual(
            self._split(first + second, 100.0), (100.0, 120.0, [10.0, 10.0])
        )

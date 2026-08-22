from odoo.tests import tagged

from .common import BaseTaxCommon


@tagged("post_install", "-at_install")
class TestTaxRoundingFromTaxLines(BaseTaxCommon):
    """Reconciliation of computed tax amounts against the recorded tax lines.

    When tax lines are supplied, they are the authority: the amounts spread
    over the base lines are adjusted so their total matches the tax lines to
    the cent, which is what keeps a document's tax total from drifting away
    from the tax entries actually booked.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Pin the rounding method, because it decides the expectations below and
        # the default is not the same in every database. Standalone, the engine
        # finds no `tax_calculation_rounding_method` on res.company and falls
        # back to round_per_line; with `account` installed the field exists and
        # defaults to round_globally. On this fixture the two disagree by a cent
        # (7.48 against 7.47), so unpinned these assertions were really about
        # which modules the database happened to carry -- green in base_tax's own
        # lane and red the moment `account` was beside it.
        # `test_round_globally_moves_the_total_by_a_cent` covers the other mode.
        if cls.account_installed:
            cls.company.tax_calculation_rounding_method = "round_per_line"
        cls.tax = cls._tax(21.0, price_include_override="tax_included")
        cls.tax_rep = cls.tax.invoice_repartition_line_ids.filtered(
            lambda rep: rep.repartition_type == "tax"
        )[0]

    def _rounded_lines(self, tax_lines=None, price_unit=21.53, count=2):
        """Two identical price-included lines, rounded against ``tax_lines``."""
        AccountTax = self.env["account.tax"]
        base_lines = [self._base_line(self.tax, price_unit) for _ in range(count)]
        AccountTax._add_tax_details_in_base_lines(base_lines, self.company)
        AccountTax._round_base_lines_tax_details(
            base_lines, self.company, tax_lines=tax_lines
        )
        return base_lines

    def _total_tax(self, base_lines):
        return sum(
            tax_data["tax_amount_currency"]
            for base_line in base_lines
            for tax_data in base_line["tax_details"]["taxes_data"]
        )

    def _tax_line(self, amount, tax_rep=None, sign=1):
        return {
            "tax_repartition_line_id": tax_rep or self.tax_rep,
            "sign": sign,
            "currency_id": self.currency,
            "amount_currency": amount,
            "balance": amount,
        }

    def test_without_tax_lines_the_computed_amounts_stand(self):
        """Left alone, the engine rounds as its own worked example says.

        Two lines of 21.53 at 21% included each yield 21.53 / 1.21 = 17.79.
        """
        base_lines = self._rounded_lines()
        self.assertEqual(
            [line["tax_details"]["total_excluded_currency"] for line in base_lines],
            [17.79, 17.79],
        )
        self.assertEqual(self._total_tax(base_lines), 7.48)

    def test_round_globally_moves_the_total_by_a_cent(self):
        """The rounding method, not the tax lines, is what makes this 7.47.

        Two lines of 21.53 at 21% included: rounded per line each is 21.53 -
        17.79 = 3.74, so 7.48; rounded globally the untaxed total is
        43.06 / 1.21 = 35.59 and the tax is the 7.47 left over. Asserting it
        here is what keeps the class's other expectations honest -- they hold
        because setUpClass pins the mode, not because 7.48 is the only answer.
        """
        if not self.account_installed:
            self.skipTest("no company rounding-method field without account")
        self.company.tax_calculation_rounding_method = "round_globally"
        base_lines = self._rounded_lines()
        self.assertAlmostEqual(self._total_tax(base_lines), 7.47, places=2)

    def test_tax_lines_agreeing_with_the_computation_change_nothing(self):
        """Tax lines that already match leave the amounts untouched."""
        base_lines = self._rounded_lines(tax_lines=[self._tax_line(7.48)])
        self.assertEqual(self._total_tax(base_lines), 7.48)

    def test_a_higher_tax_line_pulls_the_total_up_to_it(self):
        """The booked tax entry wins over the computed one."""
        base_lines = self._rounded_lines(tax_lines=[self._tax_line(7.50)])
        self.assertEqual(self._total_tax(base_lines), 7.50)

    def test_a_lower_tax_line_pulls_the_total_down_to_it(self):
        """The adjustment works in both directions."""
        base_lines = self._rounded_lines(tax_lines=[self._tax_line(7.40)])
        self.assertEqual(self._total_tax(base_lines), 7.40)

    def test_no_tax_lines_at_all_is_a_no_op(self):
        """Passing None leaves the computation alone (negative)."""
        base_lines = self._rounded_lines(tax_lines=None)
        self.assertEqual(self._total_tax(base_lines), 7.48)

    def test_an_empty_tax_line_list_is_a_no_op(self):
        """An empty list is not an instruction to zero anything (negative)."""
        base_lines = self._rounded_lines(tax_lines=[])
        self.assertEqual(self._total_tax(base_lines), 7.48)

    def test_a_tax_line_of_another_tax_is_ignored(self):
        """A tax line nothing on the document uses adjusts nothing (negative)."""
        other_tax = self._tax(7.0)
        other_rep = other_tax.invoice_repartition_line_ids.filtered(
            lambda rep: rep.repartition_type == "tax"
        )[0]
        base_lines = self._rounded_lines(
            tax_lines=[self._tax_line(99.0, tax_rep=other_rep)]
        )
        self.assertEqual(self._total_tax(base_lines), 7.48)

    def test_several_tax_lines_of_one_tax_are_summed_before_adjusting(self):
        """Split tax entries are reconciled against their total, not each one."""
        base_lines = self._rounded_lines(
            tax_lines=[self._tax_line(4.00), self._tax_line(3.50)]
        )
        self.assertEqual(self._total_tax(base_lines), 7.50)

    def test_an_opposite_signed_tax_line_subtracts(self):
        """A tax line's sign decides whether it adds to or cancels the total."""
        base_lines = self._rounded_lines(
            tax_lines=[self._tax_line(7.50), self._tax_line(0.10, sign=-1)]
        )
        self.assertEqual(self._total_tax(base_lines), 7.40)

from odoo.tests import tagged

from .common import BaseTaxCommon


@tagged("post_install", "-at_install")
class TestBaseTaxRefundReversal(BaseTaxCommon):
    def test_reverse_extra_tax_data_none_returns_none(self):
        tax_model = self.env["account.tax"]
        self.assertIsNone(tax_model._reverse_quantity_base_line_extra_tax_data(None))

    def test_reverse_extra_tax_data_flips_all_signs(self):
        tax_model = self.env["account.tax"]
        data = {
            "quantity": 2.0,
            "manual_total_excluded": 100.0,
            "manual_total_excluded_currency": 100.0,
            "manual_tax_amounts": {
                "1": {
                    "base_amount": 100.0,
                    "tax_amount": 21.0,
                    "base_amount_currency": 100.0,
                    "tax_amount_currency": 21.0,
                }
            },
        }
        reversed_data = tax_model._reverse_quantity_base_line_extra_tax_data(data)
        self.assertEqual(reversed_data["quantity"], -2.0)
        self.assertEqual(reversed_data["manual_total_excluded"], -100.0)
        self.assertEqual(reversed_data["manual_total_excluded_currency"], -100.0)
        manual = reversed_data["manual_tax_amounts"]["1"]
        self.assertEqual(manual["base_amount"], -100.0)
        self.assertEqual(manual["tax_amount"], -21.0)
        self.assertEqual(data["quantity"], 2.0)

    def _refund_base_line(self):
        tax_model = self.env["account.tax"]
        tax = self._tax(21.0)
        base_line = self._base_line(tax, 100.0, quantity=2.0, is_refund=True)
        tax_model._add_tax_details_in_base_line(
            base_line, self.company, rounding_method="round_per_line"
        )
        tax_model._round_base_lines_tax_details([base_line], self.company)
        return base_line

    def test_turn_refund_flag_off_negates_quantity_and_details(self):
        tax_model = self.env["account.tax"]
        base_line = self._refund_base_line()
        total_excluded_before = base_line["tax_details"]["total_excluded"]

        new_base_line = tax_model._turn_base_line_is_refund_flag_off(base_line)

        self.assertFalse(new_base_line["is_refund"])
        self.assertEqual(new_base_line["quantity"], -2.0)
        self.assertEqual(
            new_base_line["tax_details"]["total_excluded"], -total_excluded_before
        )

    def test_turn_refund_flag_off_noop_when_not_refund(self):
        tax_model = self.env["account.tax"]
        tax = self._tax(21.0)
        base_line = self._base_line(tax, 100.0, is_refund=False)
        tax_model._add_tax_details_in_base_line(
            base_line, self.company, rounding_method="round_per_line"
        )
        self.assertIs(
            tax_model._turn_base_line_is_refund_flag_off(base_line), base_line
        )

    def test_turn_refund_flag_off_plural(self):
        tax_model = self.env["account.tax"]
        base_line = self._refund_base_line()
        result = tax_model._turn_base_lines_is_refund_flag_off([base_line])
        self.assertEqual(len(result), 1)
        self.assertFalse(result[0]["is_refund"])
        self.assertEqual(result[0]["quantity"], -2.0)

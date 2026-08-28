from odoo.tests import tagged

from .common import BaseTaxCommon


@tagged("post_install", "-at_install")
class TestTaxManualAmounts(BaseTaxCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tax = cls._tax(21.0, type_tax_use="purchase")

    def _line(self, tax=None, price_unit=100.0, **kwargs):
        AccountTax = self.env["account.tax"]
        base_line = self._base_line(tax or self.tax, price_unit, **kwargs)
        AccountTax._add_tax_details_in_base_lines([base_line], self.company)
        AccountTax._round_base_lines_tax_details([base_line], self.company)
        return base_line

    def _tax_amounts(self, base_line):
        return [
            tax_data["tax_amount_currency"]
            for tax_data in base_line["tax_details"]["taxes_data"]
        ]

    def _reverse_charge_tax(self):
        return self._tax(
            21.0,
            type_tax_use="purchase",
            invoice_repartition_line_ids=[
                (
                    0,
                    0,
                    {
                        "repartition_type": "base",
                        "factor_percent": 100.0,
                        "document_type": "invoice",
                    },
                ),
                (
                    0,
                    0,
                    {
                        "repartition_type": "tax",
                        "factor_percent": 100.0,
                        "document_type": "invoice",
                    },
                ),
                (
                    0,
                    0,
                    {
                        "repartition_type": "tax",
                        "factor_percent": -100.0,
                        "document_type": "invoice",
                    },
                ),
            ],
            refund_repartition_line_ids=[
                (
                    0,
                    0,
                    {
                        "repartition_type": "base",
                        "factor_percent": 100.0,
                        "document_type": "refund",
                    },
                ),
                (
                    0,
                    0,
                    {
                        "repartition_type": "tax",
                        "factor_percent": 100.0,
                        "document_type": "refund",
                    },
                ),
                (
                    0,
                    0,
                    {
                        "repartition_type": "tax",
                        "factor_percent": -100.0,
                        "document_type": "refund",
                    },
                ),
            ],
        )

    def test_untouched_line_keeps_the_computed_amounts(self):
        base_line = self._line()
        self.assertEqual(base_line["tax_details"]["total_excluded_currency"], 100.0)
        self.assertEqual(self._tax_amounts(base_line), [21.0])

    def test_a_typed_tax_amount_replaces_the_computed_one(self):
        base_line = self._line(
            manual_tax_amounts={str(self.tax.id): {"tax_amount_currency": 19.0}}
        )
        self.assertEqual(self._tax_amounts(base_line), [19.0])

    def test_a_typed_tax_amount_does_not_move_the_base(self):
        base_line = self._line(
            manual_tax_amounts={str(self.tax.id): {"tax_amount_currency": 19.0}}
        )
        self.assertEqual(base_line["tax_details"]["total_excluded_currency"], 100.0)

    def test_a_typed_untaxed_amount_replaces_the_computed_base(self):
        base_line = self._line(manual_total_excluded_currency=90.0)
        self.assertEqual(base_line["tax_details"]["total_excluded_currency"], 90.0)

    def test_amounts_typed_for_another_tax_are_ignored(self):
        other_tax = self._tax(7.0, type_tax_use="purchase")
        base_line = self._line(
            manual_tax_amounts={str(other_tax.id): {"tax_amount_currency": 99.0}}
        )
        self.assertEqual(self._tax_amounts(base_line), [21.0])

    def test_an_empty_correction_is_not_a_zero(self):
        base_line = self._line(manual_tax_amounts={})
        self.assertEqual(self._tax_amounts(base_line), [21.0])

    def test_reverse_charge_legs_cancel_before_any_correction(self):
        base_line = self._line(tax=self._reverse_charge_tax())
        self.assertEqual(self._tax_amounts(base_line), [21.0, -21.0])

    def test_a_correction_keeps_reverse_charge_cancelling_out(self):
        tax = self._reverse_charge_tax()
        base_line = self._line(
            tax=tax,
            manual_tax_amounts={str(tax.id): {"tax_amount_currency": 19.0}},
        )
        self.assertEqual(self._tax_amounts(base_line), [19.0, -19.0])
        self.assertEqual(sum(self._tax_amounts(base_line)), 0.0)

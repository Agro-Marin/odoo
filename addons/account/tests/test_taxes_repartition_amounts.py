from odoo import Command
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestTaxesRepartitionAmounts(AccountTestInvoicingCommon):
    """The repartition lines of a tax must add up to that tax's own amount.

    Nothing asserted this before, which is how `_add_tax_repartition_amounts` came to
    seed its two currency columns from different pipeline stages: the foreign column
    from the raw amounts, the company column from `tax_data['tax_amount']`, whose
    meaning flips from foreign to company currency once the rounding pass has run.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.foreign_currency = cls.setup_other_currency("EUR")

    def _make_tax(self, factors, amount=21.0):
        def reps(document_type):
            return [
                Command.create(
                    {
                        "document_type": document_type,
                        "repartition_type": "base",
                        "factor_percent": 100.0,
                    }
                )
            ] + [
                Command.create(
                    {
                        "document_type": document_type,
                        "repartition_type": "tax",
                        "factor_percent": factor,
                        "account_id": self.company_data["default_account_tax_sale"].id,
                    }
                )
                for factor in factors
            ]

        return self.env["account.tax"].create(
            {
                "name": f"rep {'/'.join(str(f) for f in factors)}",
                "amount_type": "percent",
                "amount": amount,
                "company_ids": [Command.set(self.env.company.ids)],
                "invoice_repartition_line_ids": reps("invoice"),
                "refund_repartition_line_ids": reps("refund"),
            }
        )

    def _tax_data(self, tax, price_unit, rate, rounded):
        AccountTax = self.env["account.tax"]
        base_line = AccountTax._prepare_base_line_for_taxes_computation(
            None,
            currency_id=self.foreign_currency,
            tax_ids=tax,
            price_unit=price_unit,
            quantity=1.0,
            rate=rate,
        )
        AccountTax._add_tax_details_in_base_line(base_line, self.env.company)
        if rounded:
            AccountTax._round_base_lines_tax_details([base_line], self.env.company)
        AccountTax._add_accounting_data_to_base_line_tax_details(
            base_line, self.env.company, rounded=rounded
        )
        return base_line["tax_details"]["taxes_data"][0]

    FACTORS = ([100.0], [50.0, 50.0], [33.3333, 66.6667], [10.0, 20.0, 30.0, 40.0])
    PRICES = (100.03, 33.33, 1234.567, 7.77, 19.99, 0.07, 2705.4455, 13647.3795)
    RATES = (1.0, 1.13, 0.007, 137.5, 4.0)

    def test_repartition_lines_sum_to_the_tax_amount_when_rounded(self):
        for factors in self.FACTORS:
            tax = self._make_tax(factors)
            for price_unit in self.PRICES:
                for rate in self.RATES:
                    with self.subTest(factors=factors, price_unit=price_unit, rate=rate):
                        tax_data = self._tax_data(tax, price_unit, rate, rounded=True)
                        reps = tax_data["tax_reps_data"]
                        self.assertEqual(
                            self.foreign_currency.round(
                                sum(rep["tax_amount_currency"] for rep in reps)
                            ),
                            tax_data["tax_amount_currency"],
                        )
                        self.assertEqual(
                            self.env.company.currency_id.round(
                                sum(rep["tax_amount"] for rep in reps)
                            ),
                            tax_data["tax_amount"],
                        )

    def test_repartition_lines_sum_to_the_tax_amount_when_not_rounded(self):
        """The `rounded=False` path is what compute_all uses.

        It reads the raw amounts, and the per-line figures it produces are rounded to
        the currency, so the target is the *rounded* raw amount -- each in its own
        currency. Seeding the company column from the foreign figure is the currency
        mix-up this asserts against; at rate 4.0 it is wrong by a factor of four, not
        by a cent.
        """
        company_currency = self.env.company.currency_id
        for factors in self.FACTORS:
            tax = self._make_tax(factors)
            for price_unit in self.PRICES:
                for rate in self.RATES:
                    with self.subTest(factors=factors, price_unit=price_unit, rate=rate):
                        tax_data = self._tax_data(tax, price_unit, rate, rounded=False)
                        reps = tax_data["tax_reps_data"]
                        self.assertEqual(
                            self.foreign_currency.round(
                                sum(rep["tax_amount_currency"] for rep in reps)
                            ),
                            self.foreign_currency.round(
                                tax_data["raw_tax_amount_currency"]
                            ),
                        )
                        self.assertEqual(
                            company_currency.round(
                                sum(rep["tax_amount"] for rep in reps)
                            ),
                            company_currency.round(tax_data["raw_tax_amount"]),
                        )

    def test_single_full_repartition_line_carries_the_whole_tax(self):
        """A lone 100% repartition line must equal the tax exactly, in both modes.

        This is the argument-free form of the invariant: no distribution to reason
        about, so any difference is a seeding error.
        """
        tax = self._make_tax([100.0])
        company_currency = self.env.company.currency_id
        for price_unit in self.PRICES:
            for rate in self.RATES:
                for rounded in (True, False):
                    with self.subTest(price_unit=price_unit, rate=rate, rounded=rounded):
                        tax_data = self._tax_data(tax, price_unit, rate, rounded)
                        rep = tax_data["tax_reps_data"][0]
                        prefix = "" if rounded else "raw_"
                        self.assertEqual(
                            rep["tax_amount"],
                            company_currency.round(tax_data[f"{prefix}tax_amount"]),
                        )
                        self.assertEqual(
                            rep["tax_amount_currency"],
                            self.foreign_currency.round(
                                tax_data[f"{prefix}tax_amount_currency"]
                            ),
                        )

from odoo.tests import tagged

from odoo.addons.sale_stock.tests.test_anglo_saxon_valuation_reconciliation import (
    TestValuationReconciliationCommon,
)


@tagged("post_install", "-at_install")
class TestAngloSaxonAccounting(TestValuationReconciliationCommon):
    def test_cogs_should_use_price_from_the_right_company(self):
        company_a_data = self.company
        company_b_data = self._create_company()
        companies_with_b_first = company_b_data + company_a_data
        self.env.user.company_ids = companies_with_b_first
        product = self.product_standard_auto

        company_a_standard_price = 20.0
        product.with_company(company_a_data).standard_price = company_a_standard_price
        company_b_standard_price = 10.0
        product.with_company(company_b_data).standard_price = company_b_standard_price

        self._so_deliver(
            product,
            quantity=1,
            price=66.0,
            picking=False,
            partner=self.vendor,
            date_order="2021-01-01",
        )
        company_a_invoice = self._create_invoice(
            product, quantity=1, price_unit=66.0, invoice_date="2021-01-10", post=False
        )

        company_a_invoice.with_context(
            allowed_company_ids=companies_with_b_first.ids
        ).action_post()

        anglo_saxon_lines = company_a_invoice.line_ids.filtered(
            lambda l: l.display_type == "cogs"
        )
        self.assertRecordValues(
            anglo_saxon_lines,
            [
                {"debit": 0.0, "credit": company_a_standard_price},
                {"debit": company_a_standard_price, "credit": 0.0},
            ],
        )

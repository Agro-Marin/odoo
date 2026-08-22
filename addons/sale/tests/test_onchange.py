from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSaleOnchanges(TransactionCase):
    def test_create_products_in_different_companies(self):
        company_a = self.env["res.company"].create({"name": "Company A"})
        company_b = self.env["res.company"].create({"name": "Company B"})
        products = self.env["product.template"].create(
            [
                {"name": "Product Test 1", "company_id": company_a.id},
                {"name": "Product Test 2", "company_id": company_b.id},
                {"name": "Product Test 3", "company_id": False},
            ]
        )
        self.assertRecordValues(
            products,
            [
                {"company_id": company_a.id},
                {"company_id": company_b.id},
                {"company_id": False},
            ],
        )

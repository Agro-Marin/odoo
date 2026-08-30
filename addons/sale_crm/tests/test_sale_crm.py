from odoo.fields import Command

from odoo.addons.crm.tests.common import TestCrmCommon


class TestSaleCrm(TestCrmCommon):
    def test_sale_crm_revenue(self):
        product1, product2 = self.env["product.template"].create(
            [
                {
                    "name": "Test product1",
                    "list_price": 100.0,
                },
                {
                    "name": "Test product2",
                    "list_price": 200.0,
                },
            ]
        )

        my_pricelist = self.env["product.pricelist"].create(
            {"name": "Rupee", "currency_id": self.ref("base.INR")}
        )
        pricelist_expected_by_lead = self.env["product.pricelist"].create(
            {"name": "Rupee", "currency_id": self.ref("base.USD")}
        )

        so_values = {
            "partner_id": self.env.user.partner_id.id,
            "opportunity_id": self.lead_1.id,
        }
        so1, so2 = self.env["sale.order"].create(
            [
                {
                    **so_values,
                    "pricelist_id": my_pricelist.id,
                    "line_ids": [
                        Command.create(
                            {
                                "product_id": product1.product_variant_id.id,
                            }
                        ),
                    ],
                },
                {
                    **so_values,
                    "pricelist_id": pricelist_expected_by_lead.id,
                    "line_ids": [
                        Command.create(
                            {
                                "product_id": product2.product_variant_id.id,
                            }
                        ),
                    ],
                },
            ]
        )

        self.assertEqual(self.lead_1.expected_revenue, 0)

        so1.action_confirm()
        self.assertEqual(self.lead_1.expected_revenue, 0)
        so2.action_confirm()
        self.assertEqual(self.lead_1.expected_revenue, 200)

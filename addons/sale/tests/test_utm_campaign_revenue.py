from odoo.fields import Command
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestUtmCampaignRevenue(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.campaign = cls.env["utm.campaign"].create({"name": "Spring push"})
        cls.other_campaign = cls.env["utm.campaign"].create({"name": "Untouched"})
        cls.customer = cls.env["res.partner"].create({"name": "Campaign buyer"})
        cls.product = cls.env["product.product"].create(
            {
                "name": "Campaign product",
                "type": "consu",
                "list_price": 100.0,
            }
        )

    def _quotation(self, campaign=None):
        return self.env["sale.order"].create(
            {
                "partner_id": self.customer.id,
                "campaign_id": (campaign or self.campaign).id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product.id,
                            "product_uom_qty": 1,
                        }
                    )
                ],
            }
        )

    def _invoice(self, amount=100.0, move_type="out_invoice", post=True):
        invoice = self.env["account.move"].create(
            {
                "move_type": move_type,
                "partner_id": self.customer.id,
                "campaign_id": self.campaign.id,
                "invoice_line_ids": [
                    Command.create(
                        {
                            "product_id": self.product.id,
                            "quantity": 1,
                            "price_unit": amount,
                        }
                    )
                ],
            }
        )
        if post:
            invoice.action_post()
        return invoice

    def test_quotation_count_per_campaign(self):
        self._quotation()
        self._quotation()
        self._quotation(campaign=self.other_campaign)
        (self.campaign + self.other_campaign).invalidate_recordset(
            ["quotation_count"],
        )
        self.assertEqual(self.campaign.quotation_count, 2)
        self.assertEqual(self.other_campaign.quotation_count, 1)

    def test_campaign_without_quotations_counts_zero(self):
        self.assertEqual(self.other_campaign.quotation_count, 0)

    def test_invoiced_amount_counts_posted_invoices(self):
        self._invoice(amount=100.0)
        self.campaign.invalidate_recordset(["invoiced_amount"])
        self.assertEqual(self.campaign.invoiced_amount, 100.0)

    def test_draft_invoices_are_not_counted(self):
        self._invoice(amount=250.0, post=False)
        self.campaign.invalidate_recordset(["invoiced_amount"])
        self.assertEqual(self.campaign.invoiced_amount, 0.0)

    def test_refunds_reduce_the_revenue(self):
        self._invoice(amount=100.0)
        self._invoice(amount=40.0, move_type="out_refund")
        self.campaign.invalidate_recordset(["invoiced_amount"])
        self.assertEqual(self.campaign.invoiced_amount, 60.0)

    def test_campaign_without_invoices_reports_zero(self):
        self.other_campaign.invalidate_recordset(["invoiced_amount"])
        self.assertEqual(self.other_campaign.invoiced_amount, 0)

    def test_quotation_redirect_is_scoped_to_the_campaign(self):
        action = self.campaign.action_redirect_to_quotations()
        self.assertIn(("campaign_id", "=", self.campaign.id), action["domain"])
        self.assertEqual(
            action["context"]["default_campaign_id"],
            self.campaign.id,
        )

    def test_invoiced_redirect_lists_only_live_invoices(self):
        invoice = self._invoice(amount=100.0)
        action = self.campaign.action_redirect_to_invoiced()
        domain = {item[0]: item[2] for item in action["domain"] if len(item) == 3}
        self.assertIn(invoice.id, domain["id"])
        self.assertEqual(domain["state"], ["draft", "cancel"])
        self.assertFalse(action["context"]["create"])

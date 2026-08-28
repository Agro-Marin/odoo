from odoo import Command
from odoo.tests import tagged

from odoo.addons.account_payment_provider.tests.common import AccountPaymentCommon


@tagged("-at_install", "post_install")
class TestPaymentLinkWizard(AccountPaymentCommon):
    def _create_posted_invoice(self):
        invoice = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": self.partner.id,
                "invoice_line_ids": [
                    Command.create({"name": "line", "price_unit": 100.0}),
                ],
            }
        )
        invoice.action_post()
        return invoice

    def _create_wizard(self, invoice, **vals):
        return (
            self.env["payment.link.wizard"]
            .with_context(active_model="account.move", active_id=invoice.id)
            .create(vals)
        )

    def test_epd_info_set_on_exact_match(self):
        """Test that epd_info is populated when amount equals invoice_amount_due."""
        invoice = self._create_posted_invoice()
        wizard = self._create_wizard(invoice, amount=100.0, amount_max=100.0)
        wizard.has_eligible_epd = True
        wizard.discount_date = "2024-01-01"
        wizard._compute_epd_info()
        self.assertTrue(
            wizard.epd_info,
            "epd_info should be set when amount exactly equals invoice_amount_due.",
        )

    def test_epd_info_not_set_on_real_mismatch(self):
        """Test that epd_info stays empty when amount is genuinely different from
        invoice_amount_due (beyond rounding tolerance)."""
        invoice = self._create_posted_invoice()
        wizard = self._create_wizard(invoice, amount=50.0, amount_max=100.0)
        wizard.has_eligible_epd = True
        wizard.discount_date = "2024-01-01"
        wizard._compute_epd_info()
        self.assertFalse(wizard.epd_info)

    def test_link_uses_portal_url_for_invoice(self):
        """Test that the link for an account.move routes through the invoice portal
        page instead of the generic /payment/pay page, and carries the
        account_payment-specific query params."""
        invoice = self._create_posted_invoice()
        wizard = self._create_wizard(invoice, amount=100.0, amount_max=100.0)

        self.assertIn(invoice.get_portal_url(), wizard.link)
        self.assertNotIn("/payment/pay", wizard.link)
        self.assertIn("payment_token=", wizard.link)
        self.assertIn("payment=True", wizard.link)
        self.assertTrue(wizard.link.endswith("#portal_pay"))

    def test_link_falls_back_to_base_behavior_for_non_invoice(self):
        """Test that the link for a non-account.move record keeps the base
        `payment` module's generic /payment/pay behavior untouched."""
        wizard = self.env["payment.link.wizard"].create(
            {
                "res_model": "res.partner",
                "res_id": self.partner.id,
                "amount": 10.0,
                "amount_max": 10.0,
                "currency_id": self.currency_euro.id,
                "partner_id": self.partner.id,
            }
        )

        self.assertIn("/payment/pay", wizard.link)
        self.assertIn("access_token=", wizard.link)
        self.assertNotIn("payment_token=", wizard.link)
        self.assertFalse(wizard.link.endswith("#portal_pay"))

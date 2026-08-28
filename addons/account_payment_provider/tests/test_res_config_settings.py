from odoo import Command
from odoo.tests import tagged

from odoo.addons.account_payment_provider.tests.common import AccountPaymentCommon


@tagged("-at_install", "post_install")
class TestResConfigSettings(AccountPaymentCommon):
    def test_pay_invoices_online_round_trips_through_config_parameter(self):
        """Test that the pay_invoices_online setting reads/writes the same
        ir.config_parameter that payment_link_wizard.py's warning message check
        reads (account_payment_provider.enable_portal_payment)."""
        get_param = self.env["ir.config_parameter"].sudo().get_param

        settings = self.env["res.config.settings"].create(
            {"pay_invoices_online": False}
        )
        settings.execute()
        self.assertEqual(
            get_param("account_payment_provider.enable_portal_payment"), "False"
        )

        settings = self.env["res.config.settings"].create({"pay_invoices_online": True})
        settings.execute()
        self.assertEqual(
            get_param("account_payment_provider.enable_portal_payment"), "True"
        )

    def test_warning_message_reacts_to_pay_invoices_online(self):
        """Test that payment.link.wizard's warning_message reacts to
        account_payment_provider.enable_portal_payment, which pay_invoices_online sets."""
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

        self.env["ir.config_parameter"].sudo().set_param(
            "account_payment_provider.enable_portal_payment", "True"
        )
        wizard = (
            self.env["payment.link.wizard"]
            .with_context(active_model="account.move", active_id=invoice.id)
            .create({})
        )
        self.assertFalse(wizard.warning_message)

        self.env["ir.config_parameter"].sudo().set_param(
            "account_payment_provider.enable_portal_payment", "False"
        )
        wizard = (
            self.env["payment.link.wizard"]
            .with_context(active_model="account.move", active_id=invoice.id)
            .create({})
        )
        self.assertTrue(wizard.warning_message)

from datetime import timedelta

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import tagged

from odoo.addons.account_payment_provider.tests.common import AccountPaymentCommon
from odoo.addons.payment.tests.http_common import PaymentHttpCommon


@tagged("post_install", "-at_install")
class TestPortalInvoiceAccess(AccountPaymentCommon, PaymentHttpCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param(
            "account_payment_provider.enable_portal_payment", "True"
        )
        cls.portal_invoice = cls.init_invoice(
            "out_invoice",
            partner=cls.portal_partner,
            amounts=[100.0],
            currency=cls.currency,
            post=True,
        )
        cls.other_invoice = cls.init_invoice(
            "out_invoice",
            partner=cls.partner,
            amounts=[70.0],
            currency=cls.currency,
            post=True,
        )

    def _link_transaction(self, invoice, reference, **values):
        return self._create_transaction(
            "redirect",
            reference=reference,
            partner_id=invoice.partner_id.id,
            invoice_ids=[Command.set(invoice.ids)],
            **values,
        )

    def _get_as_portal(self, route):
        self.authenticate(self.portal_user.login, self.portal_user.login)
        return self._make_http_get_request(self._build_url(route))

    def test_portal_invoice_list_renders_without_transactions(self):
        resp = self._get_as_portal("/my/invoices")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(self.portal_invoice.name, resp.text)
        self.assertNotIn(self.other_invoice.name, resp.text)

    def test_portal_invoice_list_renders_with_transactions(self):
        self._link_transaction(self.portal_invoice, "PORTAL-TX-DRAFT")
        resp = self._get_as_portal("/my/invoices")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(self.portal_invoice.name, resp.text)
        self.assertIn(
            self.portal_invoice.get_portal_url(
                anchor="portal_pay", query_string="&payment=True"
            ).replace("&", "&amp;"),
            resp.text,
        )

    def test_portal_invoice_page_renders_with_transactions(self):
        self._link_transaction(self.portal_invoice, "PORTAL-TX-DRAFT")
        resp = self._get_as_portal(f"/my/invoices/{self.portal_invoice.id}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(self.portal_invoice.name, resp.text)
        self.assertIn('data-bs-target="#pay_with"', resp.text)

    def test_portal_overdue_invoices_page_renders_with_transactions(self):
        self.portal_invoice.invoice_date_due = (
            self.portal_invoice.invoice_date - timedelta(days=10)
        )
        self._link_transaction(self.portal_invoice, "PORTAL-TX-OVERDUE")
        resp = self._get_as_portal("/my/invoices/overdue")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._get_payment_context(resp)["amount"], 100.0)

    def test_portal_payment_checks_stay_scoped_to_readable_invoices(self):
        self._link_transaction(self.other_invoice, "OTHER-TX")
        foreign_invoice = self.other_invoice.with_user(self.portal_user)
        with self.assertRaises(AccessError):
            foreign_invoice._has_to_be_paid()
        with self.assertRaises(AccessError):
            foreign_invoice._get_online_payment_error()

    def test_portal_privilege_reads_only_own_invoice_transactions(self):
        own_tx = self._link_transaction(self.portal_invoice, "PORTAL-TX-OWN")
        self._link_transaction(self.other_invoice, "PORTAL-TX-FOREIGN")
        transactions = self.env["payment.transaction"].with_user(self.portal_user)
        self.assertFalse(transactions.has_access("read"))
        privileged = transactions.with_privilege(
            "account_payment_provider.privilege_read_own_invoice_transactions"
        )
        self.assertEqual(privileged.search([]), own_tx)

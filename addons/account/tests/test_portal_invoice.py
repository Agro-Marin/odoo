from freezegun import freeze_time

from odoo.fields import Command
from odoo.tests.common import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingHttpCommon


@tagged("post_install", "-at_install")
class TestPortalInvoice(AccountTestInvoicingHttpCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user_portal = cls._create_new_portal_user()
        cls.portal_partner = cls.user_portal.partner_id

    def test_portal_my_invoice_detail_not_his_invoice(self):
        not_his_invoice = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": self.partner_a.id,
                "invoice_line_ids": [Command.create({"price_unit": 100})],
            }
        )
        not_his_invoice.action_post()
        url = f"/my/invoices/{not_his_invoice.id}?report_type=pdf&download=True"
        self.authenticate(self.user_portal.login, self.user_portal.login)
        res = self.url_open(url)
        self.assertEqual(res.status_code, 200)

    def test_portal_my_invoice_detail_download_pdf(self):
        invoice_with_pdf = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": self.portal_partner.id,
                "invoice_line_ids": [Command.create({"price_unit": 100})],
            }
        )
        invoice_with_pdf.action_post()
        invoice_with_pdf._generate_and_send()
        self.assertTrue(invoice_with_pdf.invoice_pdf_report_id)

        url = f"/my/invoices/{invoice_with_pdf.id}?report_type=pdf&download=True"
        self.authenticate(self.user_portal.login, self.user_portal.login)
        res = self.url_open(url)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.content, invoice_with_pdf.invoice_pdf_report_id.raw)

    def test_portal_my_invoice_detail_download_proforma(self):
        invoice_no_pdf = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": self.portal_partner.id,
                "invoice_line_ids": [Command.create({"price_unit": 100})],
            }
        )
        invoice_no_pdf.action_post()
        self.assertFalse(invoice_no_pdf.invoice_pdf_report_id)

        url = f"/my/invoices/{invoice_no_pdf.id}?report_type=pdf&download=True"
        self.authenticate(self.user_portal.login, self.user_portal.login)
        res = self.url_open(url)
        self.assertEqual(res.status_code, 200)
        self.assertIn("Proforma", res.content.decode("utf-8"))

    @freeze_time("2026-01-16 02:00:00")
    def test_overdue_filter_uses_the_customer_local_day(self):
        """An invoice due today must not be listed as overdue.

        The server runs on UTC. At 02:00 UTC on the 16th it is still 20:00 on the
        15th in Mexico City, so an invoice due the 15th is due *today* for the
        customer reading the page -- yet comparing against the UTC day made it
        overdue. Every evening after 18:00 local, invoices fell into the overdue
        filter a day early.
        """
        self.env.user.tz = "America/Mexico_City"
        self.user_portal.tz = "America/Mexico_City"

        def make_invoice(due):
            invoice = self.env["account.move"].create(
                {
                    "move_type": "out_invoice",
                    "partner_id": self.portal_partner.id,
                    "invoice_date": "2026-01-01",
                    "invoice_date_due": due,
                    "invoice_line_ids": [Command.create({"price_unit": 100})],
                }
            )
            invoice.action_post()
            return invoice

        due_today = make_invoice("2026-01-15")
        genuinely_overdue = make_invoice("2026-01-14")

        self.authenticate(self.user_portal.login, self.user_portal.login)
        res = self.url_open("/my/invoices?filterby=overdue_invoices")
        self.assertEqual(res.status_code, 200)
        page = res.content.decode("utf-8")

        self.assertIn(genuinely_overdue.name, page)
        self.assertNotIn(due_today.name, page)

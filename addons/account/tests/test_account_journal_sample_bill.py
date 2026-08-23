from datetime import timedelta

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestAccountJournalSampleBill(AccountTestInvoicingCommon):
    """The sample vendor bill is offered by the bill-upload guide and clicked by
    account_accountant's onboarding tour, and no Python test reached it.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # the action refuses to run outside demo mode; bind the xmlid it looks for
        # so these assertions do not depend on how the database was seeded
        if not cls.env.ref("base.res_partner_2", raise_if_not_found=False):
            partner = cls.env["res.partner"].create({"name": "Sample Vendor"})
            cls.env["ir.model.data"].create(
                {
                    "module": "base",
                    "name": "res_partner_2",
                    "model": "res.partner",
                    "res_id": partner.id,
                }
            )

    @property
    def _purchase_journal(self):
        return self.company_data["default_journal_purchase"]

    def test_the_sample_bill_is_a_posted_shaped_vendor_bill(self):
        action = self._purchase_journal.action_create_vendor_bill()
        bill = self.env["account.move"].browse(action["res_id"])

        self.assertEqual(action["res_model"], "account.move")
        self.assertEqual(bill.move_type, "in_invoice")
        self.assertEqual(bill.journal_id, self._purchase_journal)
        self.assertEqual(bill.state, "draft")
        self.assertEqual(len(bill.invoice_line_ids), 2)
        self.assertEqual(bill.amount_untaxed, 5 * 1500 + 5 * 2350)
        self.assertEqual(bill.invoice_date_due - bill.invoice_date, timedelta(days=30))
        self.assertEqual(bill.ref, "DE%s" % bill.invoice_date.strftime("%Y%m"))

    def test_no_weasyprint_render_happens_under_test(self):
        """The guard is the reason this action is affordable in a tour. Outside a
        test run the same call returns one attachment, so the assertion below is a
        statement about the guard rather than about weasyprint being unavailable.
        """
        attachments = self._purchase_journal._render_sample_bill_attachment(
            self.env.company, "DE202601", self.env.cr.now().date()
        )
        self.assertFalse(attachments)

        action = self._purchase_journal.action_create_vendor_bill()
        bill = self.env["account.move"].browse(action["res_id"])
        self.assertTrue(bill.message_ids, "the bill is still announced in the log")
        self.assertFalse(bill.message_ids.attachment_ids)

    def test_a_company_without_a_purchase_journal_says_which_type_is_missing(self):
        company = self.env["res.company"].create({"name": "No Journals Co"})
        journals = self.env["account.journal"].with_context(
            allowed_company_ids=[company.id]
        )
        self.assertFalse(journals.search([("type", "=", "purchase")]))

        with self.assertRaisesRegex(UserError, "No journal could be found.*purchase"):
            journals.action_create_vendor_bill()

    def test_is_sample_action_available_tracks_the_demo_partner(self):
        self.assertTrue(self.env["account.journal"].is_sample_action_available())

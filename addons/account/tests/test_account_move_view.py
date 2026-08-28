from lxml import etree

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestAccountMoveView(AccountTestInvoicingCommon):
    def test_the_invoice_company_is_limited_to_the_journal_branch(self):
        invoice = self.init_invoice("out_invoice", amounts=[100])
        self.assertEqual(invoice.journal_company_id, invoice.journal_id.company_id)

        # `company_id` only reaches the arch for a multi-company user.
        self.env.user.group_ids = [
            Command.link(self.env.ref("base.group_multi_company").id)
        ]
        view = self.env["account.move"].get_view(
            view_id=self.env.ref("account.view_move_form").id,
            view_type="form",
        )
        self.assertIn(
            "journal_company_id",
            view["models"]["account.move"],
            "the domain cannot be evaluated unless the view loads the field",
        )
        arch = etree.fromstring(view["arch"])

        company_field = arch.find(
            ".//group[@name='accounting_info_group']/field[@name='company_id']"
        )
        self.assertIsNotNone(company_field)
        self.assertEqual(
            company_field.get("domain"),
            "[('id', 'child_of', journal_company_id)]",
            "the company of an invoice must stay inside the journal's branch",
        )

        # The journal entry tab keeps no domain on purpose: an entry may still be
        # moved to another company, and `_inverse_company_id` refits its journal.
        entry_company_field = arch.find(
            ".//page[@id='other_tab_entry']//field[@name='company_id']"
        )
        self.assertIsNotNone(entry_company_field)
        self.assertIsNone(entry_company_field.get("domain"))

        # Without the domain the user can pick an unrelated company and only
        # finds out when the record is flushed.
        other_root = self.env["res.company"].create({"name": "Unrelated Co"})
        with self.assertRaises(UserError):
            invoice.company_id = other_root
            invoice.flush_recordset()

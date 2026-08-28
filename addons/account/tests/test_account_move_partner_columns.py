from lxml import etree

from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestAccountMovePartnerColumns(AccountTestInvoicingCommon):
    def _invoice_list_arch(self):
        view = self.env["account.move"].get_view(
            view_id=self.env.ref("account.view_invoice_tree").id,
            view_type="list",
        )
        return etree.fromstring(view["arch"])

    def test_partner_columns_are_the_editable_relation(self):
        arch = self._invoice_list_arch()
        columns = {
            column.get("string"): column
            for column in arch.findall(".//field[@name='partner_id']")
            if column.get("string") in ("Vendor", "Customer")
        }
        self.assertEqual(
            set(columns),
            {"Vendor", "Customer"},
            "the Vendor and Customer columns must be partner_id so that several"
            " invoices can have their partner set in one mass edit",
        )
        for label, column in columns.items():
            self.assertEqual(
                column.get("widget"),
                "partner_field",
                f"the {label} column needs the partner_field widget to keep"
                " showing a name once the row is readonly",
            )

    def test_display_name_stays_available_but_hidden(self):
        arch = self._invoice_list_arch()
        display_name = arch.findall(".//field[@name='invoice_partner_display_name']")
        self.assertTrue(
            display_name,
            "invoice_partner_display_name must stay in the list: the widget"
            " falls back to it when partner_id is not set",
        )
        for column in display_name:
            self.assertEqual(
                column.get("column_invisible"),
                "True",
                "the computed display name must not be a column of its own,"
                " otherwise it is the one shown and it cannot be edited",
            )

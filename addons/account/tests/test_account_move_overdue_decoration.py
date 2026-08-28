from lxml import etree

from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestAccountMoveOverdueDecoration(AccountTestInvoicingCommon):
    def _move_form_arch(self):
        view = self.env["account.move"].get_view(
            view_id=self.env.ref("account.view_move_form").id,
            view_type="form",
        )
        return etree.fromstring(view["arch"])

    def test_overdue_due_date_is_flagged_on_the_invoice_form(self):
        arch = self._move_form_arch()
        due_date = arch.find(".//field[@name='invoice_date_due']")
        self.assertIsNotNone(due_date, "the form must still carry invoice_date_due")
        decoration = due_date.get("decoration-danger")
        self.assertTrue(
            decoration,
            "an overdue due date must be painted red on the invoice form",
        )
        self.assertIn(
            "payment_state",
            decoration,
            "a paid invoice must not be painted red",
        )

    def test_overdue_maturity_is_flagged_in_the_journal_items_tab(self):
        arch = self._move_form_arch()
        maturity = arch.find(".//field[@name='date_maturity']")
        self.assertIsNotNone(
            maturity, "the Journal Items tab must still carry date_maturity"
        )
        decoration = maturity.get("decoration-danger")
        self.assertTrue(
            decoration,
            "an overdue maturity date must be painted red in the Journal Items tab",
        )
        self.assertIn(
            "parent.payment_state",
            decoration,
            "a paid move must not have its maturity column painted red",
        )

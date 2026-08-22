from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestAccountMoveCatalog(AccountTestInvoicingCommon):
    def test_posted_move_is_readonly_for_catalog(self):
        move = self._create_invoice()
        self.assertFalse(move._is_readonly())

        move.action_post()
        self.assertTrue(move._is_readonly())

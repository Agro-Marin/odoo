from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestAccountMoveCatalog(AccountTestInvoicingCommon):
    def test_posted_move_is_readonly_for_catalog(self):
        """A posted move must be readonly for the product-catalog RPC route."""
        # The controller (product/controllers/catalog.py) gates every catalog
        # write on `_is_readonly()` alone, so a stale override here is a
        # direct RPC path to mutate an already-posted, hash-protected entry.
        move = self._create_invoice()
        self.assertFalse(move._is_readonly())

        move.action_post()
        self.assertTrue(move._is_readonly())

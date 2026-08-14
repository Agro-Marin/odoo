from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestAccountReconcileModel(AccountTestInvoicingCommon):
    def test_match_regex_without_a_param_raises_user_error(self):
        """An empty regex parameter must raise a clean UserError, not a bare TypeError from re.compile(None)."""
        with self.assertRaises(UserError):
            self.env["account.reconcile.model"].create(
                {
                    "name": "test_match_regex_without_a_param",
                    "match_label": "match_regex",
                }
            )

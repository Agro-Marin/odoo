from unittest.mock import patch

from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestResConfigSettings(AccountTestInvoicingCommon):
    def test_bank_statement_extract_checks_its_own_module(self):
        """The bank-statement-digitization checkbox must reflect
        account_bank_statement_extract's install state, not
        account_invoice_extract's.

        Regression: _compute_module_account_bank_statement_extract queried
        "account_invoice_extract" (copy-paste from the sibling compute),
        so the checkbox showed the wrong initial state and toggling it
        installed/uninstalled the wrong module.
        """
        config = self.env["res.config.settings"].create(
            {"module_account_extract": True}
        )
        queried_names = []
        real_get = self.env.registry["ir.module.module"]._get

        def spy_get(self_module, name):
            queried_names.append(name)
            return real_get(self_module, name)

        with patch(
            "odoo.addons.base.models.ir_module.IrModuleModule._get",
            spy_get,
            create=True,
        ):
            config._compute_module_account_bank_statement_extract()

        self.assertIn(
            "account_bank_statement_extract",
            queried_names,
            "the bank-statement compute must look up its own module",
        )
        self.assertNotIn(
            "account_invoice_extract",
            queried_names,
            "the bank-statement compute must not look up the invoice-extract module",
        )

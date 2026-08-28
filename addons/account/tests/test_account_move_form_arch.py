from lxml import etree

from odoo.tests import new_test_user, tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestAccountMoveFormArch(AccountTestInvoicingCommon):
    """Assertions on what `account.view_move_form` actually ships.

    Hoot cannot stand in for these: every test in `account_move_form.test.js`
    mounts its own inline arch, so the XML asserted here is never loaded there.
    """

    def _move_form_arch(self, user=None):
        env = self.env(user=user) if user else self.env
        view = env["account.move"].get_view(
            view_id=self.env.ref("account.view_move_form").id,
            view_type="form",
        )
        return etree.fromstring(view["arch"])

    def test_print_button_is_keyboard_reachable(self):
        arch = self._move_form_arch()
        buttons = arch.findall(".//button[@name='action_print_pdf']")
        self.assertEqual(
            len(buttons),
            2,
            "the header ships two mutually exclusive Print buttons",
        )
        for button in buttons:
            self.assertEqual(
                button.get("data-hotkey"),
                "p",
                "Print must be reachable by keyboard like every sibling header button",
            )

    def test_invoice_line_account_picker_excludes_cash_accounts(self):
        """Bank and cash accounts have no place on an invoice line.

        The node carries groups="account.group_account_readonly", and
        _postprocess_access_rights deletes it for a user without that group --
        admin included, since group_account_manager implies group_account_invoice
        and not group_account_readonly. The assertion therefore runs as an
        accountant, or it would pass on an empty result.
        """
        accountant = new_test_user(
            self.env,
            login="arch_accountant",
            groups="account.group_account_user",
        )
        self.assertTrue(accountant.has_group("account.group_account_readonly"))

        arch = self._move_form_arch(user=accountant)
        pickers = arch.findall(
            ".//field[@name='invoice_line_ids']//list[@name='journal_items']"
            "//field[@name='account_id']"
        )
        self.assertEqual(len(pickers), 1, "one account picker on the invoice line list")
        self.assertIn(
            "asset_cash",
            pickers[0].get("domain"),
            "cash and bank accounts must not be offered on an invoice line",
        )

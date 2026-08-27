from lxml import etree

from odoo.tests import tagged

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

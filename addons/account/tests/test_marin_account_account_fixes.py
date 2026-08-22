from odoo.tests import new_test_user, tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestMarinAccountAccountFixes(AccountTestInvoicingCommon):
    def test_display_name_code_does_not_leak_between_users(self):
        account = self.env["account.account"].search(
            [
                *self.env["account.account"]._check_company_domain(self.env.company),
                ("code", "!=", False),
            ],
            limit=1,
        )
        self.assertTrue(account, "precondition: the company has at least one account")
        code = account.with_company(self.env.company).code

        privileged = new_test_user(
            self.env,
            login="marin_acc_priv",
            groups="account.group_account_readonly",
            company_id=self.env.company.id,
        )
        plain = new_test_user(
            self.env,
            login="marin_acc_plain",
            groups="base.group_user",
            company_id=self.env.company.id,
        )
        self.assertTrue(privileged.has_group("account.group_account_readonly"))
        self.assertFalse(plain.has_group("account.group_account_readonly"))

        context = {"formatted_display_name": True}
        privileged_name = (
            account.with_user(privileged).with_context(**context).display_name
        )
        plain_name = account.with_user(plain).with_context(**context).display_name

        self.assertIn(
            code, privileged_name, "the group that may see the code still sees it"
        )
        self.assertNotIn(
            code,
            plain_name,
            "a user without the group must not be served the privileged user's name",
        )

from odoo.tests import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestTotpEnabledSearch(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.protected = new_test_user(cls.env, "totp_on", password="totp_on_pwd")
        cls.exposed = new_test_user(cls.env, "totp_off", password="totp_off_pwd")
        cls.env.cr.execute(
            "UPDATE res_users SET totp_secret = %s WHERE id = %s",
            ("A" * 32, cls.protected.id),
        )
        cls.protected.invalidate_recordset(["totp_secret", "totp_enabled"])

    def _search(self, domain):
        scope = [("id", "in", (self.protected | self.exposed).ids)]
        return self.env["res.users"].sudo().search(scope + domain)

    def test_the_users_without_two_factor_authentication_can_be_listed(self):
        for domain in (
            [("totp_enabled", "=", False)],
            [("totp_enabled", "!=", True)],
            [("totp_enabled", "not in", [True])],
        ):
            with self.subTest(domain=domain):
                self.assertEqual(self._search(domain), self.exposed)

    def test_the_users_with_two_factor_authentication_can_be_listed(self):
        for domain in (
            [("totp_enabled", "=", True)],
            [("totp_enabled", "!=", False)],
            [("totp_enabled", "in", [True])],
        ):
            with self.subTest(domain=domain):
                self.assertEqual(self._search(domain), self.protected)

from contextlib import contextmanager
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.mail.tests.common import MailCommon, mail_new_test_user
from odoo.addons.test_mail.models.test_mail_server_models import (
    TEST_PROVIDER_SMTP_HOST,
)


@tagged("-at_install", "post_install", "mail_tools", "res_users", "mail_server")
class TestPersonalMailServerSetup(MailCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param(
            "base_setup.default_external_email_server", "True"
        )
        cls.server_user = mail_new_test_user(
            cls.env,
            login="server_owner",
            name="Server Owner",
            email="server.owner@test.example.com",
            groups="base.group_user",
        )

    @contextmanager
    def _stub_setup_end_action(self):
        def end_action(self, smtp_server):
            return {"stub_server_id": smtp_server.id}

        with patch.object(
            type(self.env["res.users"]),
            "_get_mail_server_setup_end_action",
            end_action,
        ):
            yield

    def _setup(self, user, server_type):
        with self._stub_setup_end_action():
            return (
                self.env["res.users"]
                .with_user(user)
                .action_setup_outgoing_mail_server(server_type)
            )

    def _owned_server(self, user):
        return (
            self.env["ir.mail_server"]
            .sudo()
            .with_context(active_test=False)
            .search([("owner_user_id", "=", user.id)])
        )

    def test_setup_refuses_when_the_feature_is_off(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "base_setup.default_external_email_server", "False"
        )
        with self.assertRaises(UserError):
            self._setup(self.server_user, "default")

    def test_setup_refuses_a_portal_user(self):
        portal_user = self._create_portal_user()
        with self.assertRaises(UserError):
            self._setup(portal_user, "default")

    def test_setup_refuses_an_unknown_type(self):
        with self.assertRaises(UserError):
            self._setup(self.server_user, "not_a_server_type")

    def test_setup_refuses_an_address_it_cannot_own(self):
        for email, reason in (
            (False, "no address at all"),
            ("@test.example.com", "no local part"),
        ):
            with self.subTest(email=email):
                self.server_user.sudo().email = email
                with self.assertRaises(UserError, msg=reason):
                    self._setup(self.server_user, "test_provider")
        self.server_user.sudo().email = "server.owner@test.example.com"

    def test_setup_refuses_an_address_owned_by_an_alias_domain(self):
        alias_domain = self.env["mail.alias.domain"].sudo().search([], limit=1)
        self.server_user.sudo().email = alias_domain.default_from_email
        with self.assertRaises(UserError):
            self._setup(self.server_user, "test_provider")

    def test_setup_default_removes_the_personal_server(self):
        self.env["ir.mail_server"].sudo().create(self._server_vals(self.server_user))
        self.assertTrue(self._owned_server(self.server_user))

        action = self._setup(self.server_user, "default")

        self.assertFalse(self._owned_server(self.server_user))
        self.assertEqual(action["tag"], "display_notification")

    def test_setup_creates_an_inactive_server_for_the_owner(self):
        action = self._setup(self.server_user, "test_provider")

        server = self._owned_server(self.server_user)
        self.assertEqual(action["stub_server_id"], server.id)
        self.assertFalse(server.active, "it is activated by the OAuth callback")
        self.assertEqual(server.owner_user_id, self.server_user)
        self.assertEqual(server.from_filter, self.server_user.email_normalized)
        self.assertEqual(server.smtp_user, self.server_user.email_normalized)
        self.assertEqual(server.smtp_port, 587)
        self.assertEqual(server.smtp_encryption, "starttls")
        self.assertEqual(server.smtp_host, TEST_PROVIDER_SMTP_HOST)

    def test_setup_resumes_an_authorization_instead_of_replacing_it(self):
        self._setup(self.server_user, "test_provider")
        server = self._owned_server(self.server_user)
        server.write({"active": True, "from_filter": server.from_filter.upper()})
        self.server_user.invalidate_recordset(
            ["outgoing_mail_server_id", "outgoing_mail_server_type"]
        )

        action = self._setup(self.server_user, "test_provider")

        self.assertEqual(
            action["stub_server_id"], server.id, "the same server, still authorized"
        )
        self.assertTrue(server.exists())
        self.assertEqual(self._owned_server(self.server_user), server)

    def _server_vals(self, user):
        return {
            "name": "Owned by %s" % user.name,
            "smtp_host": "smtp.example.com",
            "smtp_user": user.email_normalized,
            "from_filter": user.email_normalized,
            "owner_user_id": user.id,
        }

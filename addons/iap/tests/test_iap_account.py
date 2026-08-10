import hashlib
from unittest.mock import patch

from odoo.exceptions import AccessError, UserError
from odoo.fields import Command
from odoo.tests import TransactionCase, tagged

from odoo.addons.iap.tools import iap_tools


@tagged("post_install", "-at_install")
class TestIapAccount(TransactionCase):
    """IAP account lifecycle, credit URLs and warning alert guards."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.service = cls.env["iap.service"].search(
            [("technical_name", "=", "reveal")],
            limit=1,
        )

    def test_create_defaults_name_to_service(self):
        """A new account without name takes the service name."""
        account = self.env["iap.account"].create({"service_id": self.service.id})
        self.assertEqual(account.name, self.service.name)
        self.assertTrue(account.account_token)

    def test_create_on_neutralized_db_disables_token(self):
        """Accounts born on a neutralized database get a disabled token."""
        self.env["ir.config_parameter"].sudo().set_param(
            "database.is_neutralized",
            True,
        )
        account = self.env["iap.account"].create({"service_id": self.service.id})
        self.assertTrue(account.account_token.endswith("+disabled"))

    def test_warning_threshold_must_be_positive(self):
        """A negative alert threshold is rejected."""
        account = self.env["iap.account"].create({"service_id": self.service.id})
        with self.assertRaises(UserError):
            account.warning_threshold = -1

    def test_warning_recipients_need_email(self):
        """Alert recipients without an email address are rejected."""
        account = self.env["iap.account"].create({"service_id": self.service.id})
        no_mail = self.env["res.users"].create(
            {
                "name": "No mail",
                "login": "nomail_iap",
            }
        )
        no_mail.email = False
        with self.assertRaises(UserError):
            account.write(
                {
                    "warning_threshold": 10,
                    "warning_user_ids": [Command.set(no_mail.ids)],
                }
            )

    def test_write_warning_fields_notifies_iap(self):
        """Changing alert settings pushes the config to the IAP endpoint."""
        account = self.env["iap.account"].create({"service_id": self.service.id})
        # The recipient must carry an email of its own: validate_warning_alerts
        # refuses the write otherwise, and base.user_admin only has one when the
        # database was built with demo data.
        recipient = self.env["res.users"].create(
            {
                "name": "Alert recipient",
                "login": "alert_iap",
                "email": "alert_iap@example.com",
            }
        )
        with patch.object(iap_tools, "iap_jsonrpc", return_value=True) as rpc:
            account.write(
                {
                    "warning_threshold": 25,
                    "warning_user_ids": [Command.set(recipient.ids)],
                }
            )
        self.assertTrue(rpc.called)
        called_kwargs = rpc.call_args.kwargs
        self.assertIn("/iap/1/update-warning-email-alerts", called_kwargs["url"])
        self.assertEqual(called_kwargs["params"]["warning_threshold"], 25)
        self.assertTrue(called_kwargs["params"]["warning_emails"][0]["email"])

    def test_get_creates_account_for_known_service(self):
        """get() returns an account bound to the requested service."""
        account = self.env["iap.account"].get("reveal")
        self.assertEqual(account.service_id, self.service)

    def test_get_unknown_service_raises(self):
        """get() refuses a technical name that matches no service."""
        with self.assertRaises(UserError):
            self.env["iap.account"].get("no_such_service_technical_name")

    def test_hash_iap_token_ignores_suffix(self):
        """Token hashing disregards the +suffix and hashes the base key."""
        expected = hashlib.sha1(b"abc").hexdigest()
        Account = self.env["iap.account"]
        self.assertEqual(Account._hash_iap_token("abc+disabled"), expected)
        self.assertEqual(Account._hash_iap_token("abc"), expected)

    def test_hash_iap_token_empty_raises(self):
        """An empty or suffix-only token cannot be hashed."""
        with self.assertRaises(UserError):
            self.env["iap.account"]._hash_iap_token("+disabled")

    def test_credits_url_carries_hashed_token(self):
        """The credit URL embeds the hashed token, never the raw one."""
        url = self.env["iap.account"].get_credits_url(
            "reveal",
            account_token="abc",
        )
        self.assertIn("service_name=reveal", url)
        self.assertIn(hashlib.sha1(b"abc").hexdigest(), url)
        self.assertNotIn("abc&", url)
        self.assertIn("hashed=1", url)

    def test_action_buy_credits_returns_url_action(self):
        """Buying credits opens the credit URL as an act_url action."""
        account = self.env["iap.account"].create({"service_id": self.service.id})
        action = account.action_buy_credits()
        self.assertEqual(action["type"], "ir.actions.act_url")
        self.assertIn("/iap/1/credit", action["url"])

    def test_get_credits_returns_balance(self):
        """get_credits relays the balance reported by the IAP server."""
        self.env["iap.account"].get("reveal")
        with patch.object(iap_tools, "iap_jsonrpc", return_value=42):
            self.assertEqual(self.env["iap.account"].get_credits("reveal"), 42)

    def test_get_credits_access_error_returns_minus_one(self):
        """An unreachable IAP server reports -1 credits instead of crashing."""
        self.env["iap.account"].get("reveal")
        with patch.object(
            iap_tools,
            "iap_jsonrpc",
            side_effect=AccessError("down"),
        ):
            self.assertEqual(self.env["iap.account"].get_credits("reveal"), -1)

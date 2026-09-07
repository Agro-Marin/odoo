from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged

from odoo.addons.sms.tools.sms_api import SmsApi


@tagged("post_install", "-at_install")
class TestSmsAccountWizardErrors(TransactionCase):
    """The account registration wizards must name the reason IAP gave.

    Every one of the three wizards funnels its status through
    ``ERROR_MESSAGES.get(status, ERROR_MESSAGES['unknown_error'])``, so a status
    missing from the dict reaches the user as the generic "contact Odoo support"
    sentence instead of the actual reason.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.account = cls.env["iap.account"].create(
            {
                "name": "SMS test account",
                "service_id": cls.env.ref("sms.iap_service_sms").id,
                "account_token": "test-token",
            }
        )

    def _assert_reason(self, wizard, action, api_method, status, expected_fragment):
        """Run ``action`` with IAP answering ``status``, return the error shown."""
        with patch.object(SmsApi, api_method, return_value={"state": status}):
            with self.assertRaises(ValidationError) as capture:
                getattr(wizard, action)()
        message = str(capture.exception)
        self.assertNotIn(
            "unknown error",
            message.lower(),
            f"{status} fell back to the generic message: {message}",
        )
        self.assertIn(expected_fragment, message)

    def test_phone_wizard_reports_country_not_supported(self):
        wizard = self.env["sms.account.phone"].create(
            {
                "account_id": self.account.id,
                "phone_number": "+32456998877",
            }
        )
        self._assert_reason(
            wizard,
            "action_send_verification_code",
            "_send_verification_sms",
            "country_not_supported",
            "sender registration legislation",
        )

    def test_phone_wizard_reports_inactive_database(self):
        wizard = self.env["sms.account.phone"].create(
            {
                "account_id": self.account.id,
                "phone_number": "+32456998877",
            }
        )
        self._assert_reason(
            wizard,
            "action_send_verification_code",
            "_send_verification_sms",
            "not_active_db",
            "not activated",
        )

    def test_code_wizard_reports_inactive_database(self):
        wizard = self.env["sms.account.code"].create(
            {
                "account_id": self.account.id,
                "verification_code": "123456",
            }
        )
        self._assert_reason(
            wizard,
            "action_register",
            "_verify_account",
            "not_active_db",
            "not activated",
        )

    def test_sender_wizard_reports_country_not_supported(self):
        wizard = self.env["sms.account.sender"].create(
            {
                "account_id": self.account.id,
                "sender_name": "AgroMarin",
            }
        )
        self._assert_reason(
            wizard,
            "action_set_sender_name",
            "_set_sender_name",
            "country_not_supported",
            "sender registration legislation",
        )

    def test_unknown_status_still_falls_back(self):
        """The fallback must stay in place for statuses we really do not know."""
        wizard = self.env["sms.account.phone"].create(
            {
                "account_id": self.account.id,
                "phone_number": "+32456998877",
            }
        )
        with patch.object(
            SmsApi,
            "_send_verification_sms",
            return_value={"state": "a_status_iap_never_sends"},
        ):
            with self.assertRaises(ValidationError) as capture:
                wizard.action_send_verification_code()
        self.assertIn("unknown error", str(capture.exception).lower())

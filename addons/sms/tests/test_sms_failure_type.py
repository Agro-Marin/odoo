from odoo.tests import tagged

from odoo.addons.sms.tests.common import SMSCommon


@tagged("post_install", "-at_install")
class TestSmsDatabaseNonActive(SMSCommon):
    """An IAP ``not_active_db`` must reach the user as its own failure type.

    Without a mapping in ``PROVIDER_TO_SMS_FAILURE_TYPE`` the send loop falls to
    ``_action_update_from_provider_error``, which finds no ``sms_not_active_db``
    in ``DELIVERY_ERRORS`` and settles on ``unknown`` -- so the user reads
    "Unknown error" next to a raw provider string.
    """

    def _send_one_sms(self, sim_error):
        """Post an SMS to a partner and return (sms, notification)."""
        with self.mockSMSGateway(sim_error=sim_error):
            message = self.partner_employee._message_sms(body="Test body")
        notification = message.notification_ids
        self.assertEqual(len(notification), 1)
        sms = self.env["sms.sms"].sudo().search([("id", "=", notification.sms_id_int)])
        self.assertEqual(len(sms), 1)
        return sms, notification

    def test_not_active_db_has_its_own_failure_type(self):
        sms, notification = self._send_one_sms("not_active_db")
        self.assertEqual(sms.state, "error")
        self.assertEqual(sms.failure_type, "sms_database_non_active")
        self.assertEqual(notification.notification_status, "exception")
        self.assertEqual(notification.failure_type, "sms_database_non_active")

    def test_failure_type_label_is_readable(self):
        """The selection must carry a label, not just the technical key."""
        for model in ("sms.sms", "mail.notification"):
            labels = dict(
                self.env[model].fields_get(["failure_type"])["failure_type"][
                    "selection"
                ]
            )
            self.assertEqual(
                labels.get("sms_database_non_active"),
                "Database non active",
                f"{model}.failure_type is missing the label",
            )

    def test_unmapped_provider_error_still_falls_back(self):
        """Statuses we do not map must keep landing on ``unknown``."""
        sms, notification = self._send_one_sms("a_status_iap_never_sends")
        self.assertEqual(sms.failure_type, "unknown")
        self.assertEqual(notification.failure_type, "unknown")
        self.assertEqual(notification.failure_reason, "a_status_iap_never_sends")

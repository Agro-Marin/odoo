from unittest.mock import patch

from odoo.tests import tagged

from odoo.addons.sms.tests.common import SMSCommon

BUS_SEND = "odoo.addons.bus.models.mixin_bus_listener.MixinBusListener._bus_send"


@tagged("post_install", "-at_install")
class TestSmsNoCreditNotification(SMSCommon):
    """Running out of IAP credits must reach the user who pressed Send.

    ``sms.composer`` sends inside the user's own request on three paths
    (``_action_send_sms_numbers``, a mass send with ``mass_force_send``, and
    ``sms.sms.resend_failed``), and none of them surfaced the reason: the wizard
    just closed.
    """

    def _iap_notifications(self, bus_send):
        """The ``iap_notification`` payloads out of a patched ``_bus_send``."""
        return [
            call.args[2]
            for call in bus_send.call_args_list
            if len(call.args) > 1 and call.args[1] == "iap_notification"
        ]

    def test_insufficient_credit_notifies_the_sender(self):
        composer = (
            self.env["sms.composer"]
            .with_context(
                default_composition_mode="numbers",
            )
            .create(
                {
                    "body": "Test body",
                    "numbers": self.test_numbers[0],
                }
            )
        )
        with patch(BUS_SEND, autospec=True) as bus_send:
            with self.mockSMSGateway(sim_error="credit"):
                composer.action_send_sms()

        notifications = self._iap_notifications(bus_send)
        self.assertEqual(len(notifications), 1, "expected exactly one bus message")
        self.assertEqual(notifications[0]["type"], "no_credit")
        self.assertIn("get_credits_url", notifications[0])
        self.assertIn("SMS", notifications[0]["title"])

    def test_one_notification_per_send_not_per_sms(self):
        """A batch of failures must not flood the sender's browser."""
        composer = (
            self.env["sms.composer"]
            .with_context(
                default_composition_mode="numbers",
            )
            .create(
                {
                    "body": "Test body",
                    "numbers": ",".join(self.test_numbers),
                }
            )
        )
        with patch(BUS_SEND, autospec=True) as bus_send:
            with self.mockSMSGateway(sim_error="credit"):
                composer.action_send_sms()

        self.assertEqual(len(self._iap_notifications(bus_send)), 1)

    def test_successful_send_notifies_nothing(self):
        composer = (
            self.env["sms.composer"]
            .with_context(
                default_composition_mode="numbers",
            )
            .create(
                {
                    "body": "Test body",
                    "numbers": self.test_numbers[0],
                }
            )
        )
        with patch(BUS_SEND, autospec=True) as bus_send:
            with self.mockSMSGateway():
                composer.action_send_sms()

        self.assertEqual(self._iap_notifications(bus_send), [])

    def test_other_failures_notify_nothing(self):
        """Only a credit failure gets the "buy more credits" treatment."""
        composer = (
            self.env["sms.composer"]
            .with_context(
                default_composition_mode="numbers",
            )
            .create(
                {
                    "body": "Test body",
                    "numbers": self.test_numbers[0],
                }
            )
        )
        with patch(BUS_SEND, autospec=True) as bus_send:
            with self.mockSMSGateway(sim_error="server_error"):
                composer.action_send_sms()

        self.assertEqual(self._iap_notifications(bus_send), [])

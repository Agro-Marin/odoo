from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestIapAccountNotifications(TransactionCase):
    """Bus payload shape of iap.account's IAP -> mail notification helpers."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.service = cls.env["iap.service"].search(
            [("technical_name", "=", "reveal")],
            limit=1,
        )

    def _bus_send_and_capture(self, method, *args, **kwargs):
        """Call ``method`` on iap.account with res.users._bus_send mocked, and
        return the (channel, params) it was called with."""
        with patch(
            "odoo.addons.bus.models.mixin_bus_listener.MixinBusListener._bus_send",
            autospec=True,
        ) as bus_send:
            getattr(self.env["iap.account"], method)(*args, **kwargs)
        bus_send.assert_called_once()
        _self, channel, params = bus_send.call_args.args
        return channel, params

    def test_send_success_notification(self):
        channel, params = self._bus_send_and_capture(
            "_send_success_notification", "All good", title="Done"
        )
        self.assertEqual(channel, "iap_notification")
        self.assertEqual(
            params,
            {"message": "All good", "type": "success", "title": "Done"},
        )

    def test_send_error_notification(self):
        channel, params = self._bus_send_and_capture(
            "_send_error_notification", "Something broke"
        )
        self.assertEqual(channel, "iap_notification")
        self.assertEqual(params, {"message": "Something broke", "type": "danger"})

    def test_send_status_notification_without_title(self):
        """title is omitted from params entirely when not provided."""
        _channel, params = self._bus_send_and_capture(
            "_send_status_notification", "msg", "success"
        )
        self.assertNotIn("title", params)

    def test_send_no_credit_notification(self):
        channel, params = self._bus_send_and_capture(
            "_send_no_credit_notification",
            service_name=self.service.technical_name,
            title="Not enough credits",
        )
        self.assertEqual(channel, "iap_notification")
        self.assertEqual(params["type"], "no_credit")
        self.assertEqual(params["title"], "Not enough credits")
        self.assertIn("get_credits_url", params)
        self.assertEqual(
            params["get_credits_url"],
            self.env["iap.account"].get_credits_url(self.service.technical_name),
        )

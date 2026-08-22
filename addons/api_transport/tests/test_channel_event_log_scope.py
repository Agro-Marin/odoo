from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestChannelEventLogScope(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.outbound = cls.env["api.endpoint.outbound"].create(
            {
                "name": "Scope Probe Out",
                "code": "scope_probe_out",
                "endpoint_url": "https://example.invalid/out",
                "auth_type": "none",
            }
        )

    def _log(self, channel, direction):
        return self.env["api.event.log"].create(
            {
                "direction": direction,
                "channel_id": f"{channel._name},{channel.id}",
                "request_method": "POST",
                "request_url": "https://example.invalid/probe",
            }
        )

    def test_a_channel_sees_its_own_rows(self):
        row = self._log(self.outbound, "outbound")

        self.assertIn(row, self.outbound.event_log_ids)

    def test_a_channel_does_not_see_the_other_directions_rows(self):
        stray = self._log(self.outbound, "inbound")

        self.assertNotIn(stray, self.outbound.event_log_ids)

    def test_each_model_scopes_itself_to_its_own_direction(self):
        for model, direction in (
            ("api.endpoint.outbound", "outbound"),
            ("api.endpoint.inbound", "inbound"),
        ):
            with self.subTest(model=model):
                domain = self.env[model]._api_event_log_domain()
                self.assertIn(("direction", "=", direction), domain)

    def test_a_channel_without_a_direction_refuses_rather_than_reads_everything(self):
        with patch.object(type(self.outbound), "_api_event_direction", None):
            with self.assertRaises(NotImplementedError):
                self.outbound._api_event_log_domain()

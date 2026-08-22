"""Each channel's event log, and the direction that separates the two halves.

'_compute_event_log_ids' existed twice, once per endpoint model, identical but for the
'direction' literal and the name of a local variable. Measured with ADR-0045's algorithm
over this module's Python it was the only duplicated run in production code -- and it
measured nine lines rather than fifteen, because the differing variable name splits the
run, which is the blind spot that ADR documents.

It now lives on 'api.channel.mixin', which the manifest already describes as "behaviour
shared by both endpoint models". Pinned here is what the two copies had to agree on and
nothing checked: that a channel sees its own rows and not the other direction's.

Shaped around one fact worth knowing before reading it: 'api.endpoint.inbound' is an
AbstractModel and owns no table. Its concrete user is 'remote.device' in agromarin/remote,
so the record-level assertions run on the outbound endpoint and the inbound side is
checked through the domain it builds.
"""

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
        """The direction clause is the whole difference between the two former copies.

        The reference already names the channel, so a lost direction clause would stay
        invisible until an inbound channel and an outbound one shared an id -- which,
        being separate sequences, they routinely do.
        """
        stray = self._log(self.outbound, "inbound")

        self.assertNotIn(stray, self.outbound.event_log_ids)

    def test_each_model_scopes_itself_to_its_own_direction(self):
        """Both directions are declared, and each reaches the shared domain.

        Asserted through the domain because the inbound model is abstract: there is no
        record to compute a field on, but there is a declaration to get wrong.
        """
        for model, direction in (
            ("api.endpoint.outbound", "outbound"),
            ("api.endpoint.inbound", "inbound"),
        ):
            with self.subTest(model=model):
                domain = self.env[model]._api_event_log_domain()
                self.assertIn(("direction", "=", direction), domain)

    def test_a_channel_without_a_direction_refuses_rather_than_reads_everything(self):
        """An absent direction would widen the domain to every channel's rows.

        Refusing is the safe failure: a model that inherits the mixin and forgets the
        declaration gets an error naming itself, not another channel's traffic.
        """
        with patch.object(type(self.outbound), "_api_event_direction", None):
            with self.assertRaises(NotImplementedError):
                self.outbound._api_event_log_domain()

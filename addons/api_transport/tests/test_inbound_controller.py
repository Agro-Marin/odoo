"""Tests for InboundController's endpoint-identifier field mapping."""

from odoo.tests.common import TransactionCase

from ..controllers.inbound_controller import InboundController


class TestInboundControllerFieldMap(TransactionCase):
    """t23731: the dead `"webhook.subscription": "webhook_uuid"` dict entry
    was removed from `_get_identifier_field` (the model no longer exists).
    The fallback behavior for every other/unknown model must be unaffected.
    """

    def setUp(self):
        super().setUp()
        self.controller = InboundController()

    def test_known_model_still_maps_correctly(self):
        self.assertEqual(
            self.controller._get_identifier_field("remote.device"), "identifier"
        )

    def test_unknown_model_falls_back_to_identifier(self):
        # A model absent from field_map falls back to the "identifier" default,
        # same as any other unmapped model name.
        self.assertEqual(
            self.controller._get_identifier_field("webhook.subscription"),
            "identifier",
        )
        self.assertEqual(
            self.controller._get_identifier_field("some.other.model"),
            "identifier",
        )

import os
import unittest
from unittest.mock import MagicMock, patch

from odoo.tests import TransactionCase, new_test_user, tagged

from ..models.ir_websocket import MAX_CHANNEL_LENGTH, MAX_SUBSCRIBED_CHANNELS
from .common import WebsocketCase


@tagged("-at_install", "post_install")
@unittest.skipIf(
    os.getenv("ODOO_FAKETIME_TEST_MODE"), "This test cannot work with faketime"
)
class TestIrWebsocket(WebsocketCase):
    def test_only_allow_string_channels_from_frontend(self):
        # Client-controlled garbage is rejected on the quiet warning path
        # (no traceback), see `WebsocketConnectionHandler._serve_forever`.
        with self.assertLogs("odoo.addons.bus.websocket", level="WARNING") as log:
            ws = self.websocket_connect()
            # The invalid channel is rejected before any dispatch is
            # triggered: waiting for one would just burn the 5s timeout (and
            # now fail loudly).
            self.subscribe(
                ws,
                [("odoo", "discuss.channel", 5)],
                self.env["bus.bus"]._bus_last_id(),
                wait_for_dispatch=False,
            )
            # The rejection is asynchronous: wait until the subscribe message
            # has been processed (frames are handled in order, so a completed
            # ping/pong round-trip implies it was).
            ws.ping()
            ws.recv_data_frame(control_frame=True)  # pong
        self.assertIn("bus.Bus only string channels are allowed.", log.output[0])

    def test_build_bus_channel_list(self):
        test_user = new_test_user(
            self.env,
            login="test_user",
            password="Password!1",
            groups="base.group_system",
        )
        mock_wsrequest = MagicMock()
        mock_wsrequest.session.uid = test_user.id
        with patch("odoo.addons.bus.models.ir_websocket.wsrequest", new=mock_wsrequest):
            ir_websocket_model = self.env["ir.websocket"].with_user(test_user)
            channels = set(ir_websocket_model._build_bus_channel_list(["test_channel"]))
        expected_channels = {
            "test_channel",
            test_user.partner_id,
            self.env.ref("base.group_system"),
            self.env.ref("base.group_user"),
        }
        self.assertTrue(
            expected_channels.issubset(channels),
            f"The channels list is missing some expected values: {expected_channels - channels}.",
        )


@tagged("-at_install", "post_install")
class TestBuildBusChannelList(TransactionCase):
    """``_build_bus_channel_list`` must not need an ambient request.

    It used to branch on ``(request or wsrequest).session.uid``, which made a
    plain model method unusable from a test, a cron or a shell: with neither
    global bound, werkzeug raises ``RuntimeError: object is not bound``.
    ``env.user`` carries the same information (``_authenticate`` binds the
    public user exactly when the session has no uid).
    """

    def test_callable_without_any_request_bound(self):
        channels = self.env["ir.websocket"]._build_bus_channel_list(["custom"])
        self.assertIn("custom", channels)
        self.assertIn("broadcast", channels)

    def test_logged_in_user_gets_their_partner_channel(self):
        user = new_test_user(self.env, login="bus_chan_user")
        channels = self.env["ir.websocket"].with_user(user)._build_bus_channel_list([])
        self.assertIn(user.partner_id, channels)

    def test_public_user_gets_no_partner_channel(self):
        public = self.env.ref("base.public_user")
        channels = (
            self.env["ir.websocket"].with_user(public)._build_bus_channel_list([])
        )
        self.assertNotIn(public.partner_id, channels)


@tagged("-at_install", "post_install")
class TestSubscribeDataValidation(TransactionCase):
    """``_prepare_subscribe_data`` handles raw, client-controlled input.

    Plain ``TransactionCase``: none of this needs a websocket server, and running
    it without one keeps the assertions free of interference from the serving
    threads a ``WebsocketCase`` leaves alive.
    """

    def test_channel_count_is_capped(self):
        """An unbounded channel list retained ~24 bytes of server memory per byte
        on the wire, from a possibly anonymous connection."""
        channels = [f"c{i}" for i in range(MAX_SUBSCRIBED_CHANNELS + 1)]
        with self.assertRaises(ValueError) as err:
            self.env["ir.websocket"]._prepare_subscribe_data(channels, 0)
        self.assertIn("limited to", str(err.exception))
        # The boundary itself is still accepted.
        self.env["ir.websocket"]._prepare_subscribe_data(
            channels[:MAX_SUBSCRIBED_CHANNELS], 0
        )

    def test_channel_length_is_capped(self):
        with self.assertRaises(ValueError) as err:
            self.env["ir.websocket"]._prepare_subscribe_data(
                ["x" * (MAX_CHANNEL_LENGTH + 1)], 0
            )
        self.assertIn("characters", str(err.exception))
        self.env["ir.websocket"]._prepare_subscribe_data(["x" * MAX_CHANNEL_LENGTH], 0)

    def test_last_zero_skips_the_max_id_query(self):
        """``last == 0`` cannot be out of range, so the clamp query is skipped.

        Subscribes are frequent -- the worker re-sends one on every channel
        change -- and this was one wasted round trip on each of them.
        """
        bus = self.env["bus.bus"]
        with patch.object(type(bus), "_bus_last_id", wraps=bus._bus_last_id) as last_id:
            self.env["ir.websocket"]._prepare_subscribe_data([], 0)
            last_id.assert_not_called()
            self.env["ir.websocket"]._prepare_subscribe_data([], 1)
            last_id.assert_called_once()

    def test_out_of_range_last_is_clamped(self):
        """A watermark from another (or restored) database falls back to the
        lookback window rather than skipping every existing notification."""
        # Derived from the real maximum, not a literal: whatever rows earlier
        # tests left behind, this is out of range by construction.
        beyond = self.env["bus.bus"].sudo()._bus_last_id() + 1000
        data = self.env["ir.websocket"]._prepare_subscribe_data([], beyond)
        self.assertEqual(data["last"], 0)

    def test_in_range_last_is_preserved(self):
        self.env["bus.bus"]._sendone("some_channel", "type", "message")
        self.env.cr.precommit.run()  # create the bus.bus rows
        in_range = self.env["bus.bus"].sudo()._bus_last_id()
        data = self.env["ir.websocket"]._prepare_subscribe_data([], in_range)
        self.assertEqual(data["last"], in_range)

    def test_negative_last_is_clamped_to_zero(self):
        data = self.env["ir.websocket"]._prepare_subscribe_data([], -5)
        self.assertEqual(data["last"], 0)

    def test_unsubscribable_channels_are_filtered(self):
        """``_is_subscribable_channel`` is the central place to deny a channel."""
        IrWebsocketModel = type(self.env["ir.websocket"])
        with patch.object(
            IrWebsocketModel,
            "_is_subscribable_channel",
            lambda self, channel: channel != "denied",
        ):
            data = self.env["ir.websocket"]._prepare_subscribe_data(
                ["allowed", "denied"], 0
            )
        self.assertIn("allowed", data["channels"])
        self.assertNotIn("denied", data["channels"])

    def test_every_channel_is_subscribable_by_default(self):
        data = self.env["ir.websocket"]._prepare_subscribe_data(["a", "b"], 0)
        self.assertIn("a", data["channels"])
        self.assertIn("b", data["channels"])

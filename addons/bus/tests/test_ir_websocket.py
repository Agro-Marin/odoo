import os
import unittest
from unittest.mock import MagicMock, patch

from odoo.tests import TransactionCase, new_test_user, tagged

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

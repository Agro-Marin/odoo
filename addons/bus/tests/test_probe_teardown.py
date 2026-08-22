import time
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from odoo.db import PoolError
from odoo.tests import BaseCase, tagged

from ..websocket import ConnectionState, Websocket


@tagged("-at_install", "post_install")
class TestTerminateTeardownRobustness(BaseCase):
    def _make_ws(self):
        ws = Websocket.__new__(Websocket)
        ws._clock = time.monotonic
        ws.state = ConnectionState.OPEN
        ws._db = "somedb"
        ws._session = MagicMock()
        ws._cookies = {}
        ws._channels = set()
        ws._close_sent = False
        ws._close_received = False
        sock = MagicMock()
        sock.recv.return_value = b""
        ws._Websocket__socket = sock
        ws._Websocket__selector = MagicMock()
        ws._Websocket__cmd_queue = MagicMock()
        return ws

    def test_pool_error_during_teardown_is_swallowed(self):
        ws = self._make_ws()
        with (
            patch(
                "odoo.addons.bus.websocket.acquire_cursor",
                side_effect=PoolError("pool exhausted during teardown"),
            ),
            patch.object(Websocket, "_trigger_lifecycle_event", lambda self, ev: None),
            patch("odoo.addons.bus.websocket.dispatch"),
        ):
            ws._terminate()
        ws._Websocket__socket.close.assert_called_once()
        self.assertEqual(ws.state, ConnectionState.CLOSED)

    def test_transport_error_path_does_not_escape(self):
        ws = self._make_ws()
        with (
            patch(
                "odoo.addons.bus.websocket.acquire_cursor",
                side_effect=PoolError("pool exhausted"),
            ),
            patch.object(Websocket, "_trigger_lifecycle_event", lambda self, ev: None),
            patch("odoo.addons.bus.websocket.dispatch"),
        ):
            ws._handle_transport_error(OSError("connection reset"))
        self.assertEqual(ws.state, ConnectionState.CLOSED)

    def test_drain_deadline_bounds_peer_streaming_after_shutdown(self):
        ws = self._make_ws()
        now = [0.0]
        ws._clock = lambda: now[0]
        recv_calls = [0]

        def endless_recv(bufsize):
            recv_calls[0] += 1
            now[0] += 1.0
            return b"x" * 16

        ws._Websocket__socket.recv = endless_recv
        with (
            patch(
                "odoo.addons.bus.websocket.acquire_cursor",
                side_effect=PoolError("irrelevant"),
            ),
            patch.object(Websocket, "_trigger_lifecycle_event", lambda self, ev: None),
            patch("odoo.addons.bus.websocket.dispatch"),
        ):
            ws._terminate()
        self.assertLessEqual(recv_calls[0], 7)
        ws._Websocket__socket.close.assert_called_once()
        self.assertEqual(ws.state, ConnectionState.CLOSED)

    def test_on_websocket_closed_invoked_on_happy_path(self):
        ws = self._make_ws()
        env = MagicMock()

        @contextmanager
        def fake_acquire_cursor(db):
            yield MagicMock()

        with (
            patch("odoo.addons.bus.websocket.acquire_cursor", fake_acquire_cursor),
            patch.object(Websocket, "_trigger_lifecycle_event", lambda self, ev: None),
            patch.object(Websocket, "new_env", return_value=env),
            patch("odoo.addons.bus.websocket.dispatch"),
        ):
            ws._terminate()
        env["ir.websocket"]._on_websocket_closed.assert_called_once_with(ws._cookies)
        self.assertEqual(ws.state, ConnectionState.CLOSED)

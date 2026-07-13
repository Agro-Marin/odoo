import time
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from odoo.db import PoolError
from odoo.tests import BaseCase, tagged

from ..websocket import ConnectionState, Websocket


@tagged("-at_install", "post_install")
class TestTerminateTeardownRobustness(BaseCase):
    """``_terminate`` must always run to completion.

    Application-level teardown (CLOSE lifecycle callbacks and the
    ``ir.websocket._on_websocket_closed`` hook) acquires a cursor and can raise
    -- most notably ``PoolError`` under pool exhaustion, precisely when many
    sockets terminate together. Such a failure must be swallowed and logged, not
    propagated: otherwise it escapes the event loop (killing the serving thread)
    and skips ``_on_websocket_closed`` inconsistently.

    Regression test for the teardown hardening in ``Websocket._terminate``.
    """

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
        # ``_terminate`` drains the socket with ``while self.__socket.recv(4096):
        # pass``. A bare MagicMock returns a truthy value on every call, so the
        # loop never ends and the accumulating call records exhaust all memory.
        # An empty read signals an orderly shutdown and exits the loop.
        sock.recv.return_value = b""
        ws._Websocket__socket = sock
        ws._Websocket__selector = MagicMock()
        ws._Websocket__cmd_queue = MagicMock()
        return ws

    def test_pool_error_during_teardown_is_swallowed(self):
        """A PoolError acquiring the teardown cursor does NOT escape
        ``_terminate``; the socket is still closed and the state reaches
        CLOSED."""
        ws = self._make_ws()
        with (
            patch(
                "odoo.addons.bus.websocket.acquire_cursor",
                side_effect=PoolError("pool exhausted during teardown"),
            ),
            patch.object(Websocket, "_trigger_lifecycle_event", lambda self, ev: None),
            patch("odoo.addons.bus.websocket.dispatch"),
        ):
            ws._terminate()  # must not raise
        ws._Websocket__socket.close.assert_called_once()
        self.assertEqual(ws.state, ConnectionState.CLOSED)

    def test_transport_error_path_does_not_escape(self):
        """The full transport-error path (OSError -> _disconnect -> _terminate)
        must not propagate a teardown PoolError out of
        ``_handle_transport_error`` (which runs inside the event loop's except
        handler)."""
        ws = self._make_ws()
        with (
            patch(
                "odoo.addons.bus.websocket.acquire_cursor",
                side_effect=PoolError("pool exhausted"),
            ),
            patch.object(Websocket, "_trigger_lifecycle_event", lambda self, ev: None),
            patch("odoo.addons.bus.websocket.dispatch"),
        ):
            ws._handle_transport_error(OSError("connection reset"))  # must not raise
        self.assertEqual(ws.state, ConnectionState.CLOSED)

    def test_on_websocket_closed_invoked_on_happy_path(self):
        """When a cursor can be acquired, ``_on_websocket_closed`` is called with
        the stored cookies -- the hook is not skipped on the normal path."""
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

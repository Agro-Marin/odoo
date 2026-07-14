import time
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from odoo.tests import BaseCase, tagged

from ..websocket import (
    ConnectionState,
    ProtocolError,
    Websocket,
)


@tagged("-at_install", "post_install")
class TestTransportErrorTeardown(BaseCase):
    """A failure while emitting the close frame must not escape the event loop.

    ``_handle_transport_error`` runs *outside* the ``get_messages`` try/except.
    For a non-abnormal close code it calls ``_disconnect`` -> ``_send_close_frame``
    -> ``sendall``, which can raise ``BrokenPipeError`` when the peer misbehaved
    (triggering the transport error) and then vanished. If that escaped, it would
    propagate out of the serving thread and skip ``_terminate``, leaking the
    websocket in ``ImDispatch._channels_to_ws`` and never calling
    ``_on_websocket_closed``. It must fall back to a hard ``_terminate`` instead.
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
        # The teardown drain loop is ``while self.__socket.recv(4096): pass``;
        # an empty read signals an orderly shutdown and exits the loop.
        sock.recv.return_value = b""
        # Emitting the close frame fails as if the peer already went away.
        sock.sendall.side_effect = BrokenPipeError("peer gone")
        ws._Websocket__socket = sock
        ws._Websocket__selector = MagicMock()
        ws._Websocket__cmd_queue = MagicMock()
        ws._timeout_manager = MagicMock()
        return ws

    def test_registry_load_failure_during_server_error_does_not_escape(self):
        """The SERVER_ERROR diagnostic path loads the registry to detect a
        concurrent reload; that load itself can fail (database dropped,
        connection refused). Since ``_handle_transport_error`` runs inside the
        event loop's except handler, a second exception escaping here would
        kill the serving thread without ``_terminate`` — it must be swallowed
        and the normal close handshake must proceed."""
        ws = self._make_ws()
        ws._Websocket__socket.sendall = MagicMock()  # close frame sends fine
        with (
            patch(
                "odoo.addons.bus.websocket.Registry",
                side_effect=Exception("database gone"),
            ),
            self.assertLogs("odoo.addons.bus.websocket", level="ERROR"),
        ):
            ws._handle_transport_error(RuntimeError("boom"))  # must not raise
        # The close handshake was initiated normally (SERVER_ERROR close frame).
        ws._Websocket__socket.sendall.assert_called_once()
        self.assertEqual(ws.state, ConnectionState.CLOSING)

    def test_registry_reload_suppresses_error_log(self):
        """When the registry was concurrently reloaded, the unhandled
        exception is expected fallout: it is logged as a single warning, not
        a full traceback."""
        ws = self._make_ws()
        ws._Websocket__socket.sendall = MagicMock()
        registry_before = MagicMock(registry_sequence=1)
        registry_before.check_signaling.return_value = MagicMock(registry_sequence=2)
        with (
            patch(
                "odoo.addons.bus.websocket.Registry", return_value=registry_before
            ),
            self.assertLogs("odoo.addons.bus.websocket", level="WARNING") as capture,
        ):
            ws._handle_transport_error(RuntimeError("boom"))
        self.assertTrue(
            any("registry has been reloaded" in line for line in capture.output)
        )
        self.assertFalse(any("ERROR" in line for line in capture.output))
        self.assertEqual(ws.state, ConnectionState.CLOSING)

    def test_send_close_frame_failure_falls_back_to_terminate(self):
        ws = self._make_ws()

        @contextmanager
        def fake_acquire_cursor(db):
            yield MagicMock()

        with (
            patch.object(Websocket, "_trigger_lifecycle_event", lambda self, ev: None),
            patch("odoo.addons.bus.websocket.acquire_cursor", fake_acquire_cursor),
            patch.object(Websocket, "new_env", return_value=MagicMock()),
            patch("odoo.addons.bus.websocket.dispatch") as dispatch_mock,
        ):
            # A protocol error maps to a non-abnormal close code, so the close
            # frame is actually emitted (and here fails).
            ws._handle_transport_error(ProtocolError("bad frame"))  # must not raise
        ws._Websocket__socket.sendall.assert_called_once()  # close frame was attempted
        dispatch_mock.unsubscribe.assert_called_once_with(ws)  # _terminate ran
        ws._Websocket__socket.close.assert_called_once()
        self.assertEqual(ws.state, ConnectionState.CLOSED)

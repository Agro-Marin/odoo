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

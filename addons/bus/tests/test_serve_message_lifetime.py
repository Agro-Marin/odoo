import gc
import weakref
from unittest.mock import MagicMock, patch

from odoo.tests import BaseCase, tagged

from .. import websocket as websocket_module
from ..websocket import WebsocketConnectionHandler


@tagged("-at_install", "post_install")
class TestServeMessageLifetime(BaseCase):
    def _reachable_between_messages(self):
        built = []
        observed = []

        class _Request:
            def __init__(self, db, httprequest, ws):
                self.registry = object()

            def __enter__(self):
                built.append(weakref.ref(self))
                return self

            def __exit__(self, *args):
                return False

            def serve_websocket_message(self, message):
                pass

        def messages():
            yield b"ping"
            gc.collect()
            observed.append(built[0]() is not None)

        ws = MagicMock()
        ws.get_messages.return_value = messages()
        httprequest = MagicMock()
        httprequest.user_agent = None

        with patch.object(websocket_module, "WebsocketRequest", _Request):
            WebsocketConnectionHandler._serve_forever(
                ws, "db", httprequest, WebsocketConnectionHandler._VERSION
            )
        self.assertEqual(len(built), 1, "exactly one request should be built")
        self.assertEqual(
            len(observed), 1, "the loop should have asked for a 2nd message"
        )
        return observed[0]

    def test_request_is_released_between_messages(self):
        self.assertFalse(
            self._reachable_between_messages(),
            "the served request is still reachable while the loop waits for the "
            "next message: it is pinning its registry and environment for as "
            "long as the socket stays open. Serve each message from its own "
            "frame (WebsocketConnectionHandler._serve_message) instead of "
            "binding it in the serve loop.",
        )

    def test_sentinel_messages_build_no_request(self):
        built = []

        class _Request:
            def __init__(self, db, httprequest, ws):
                built.append(message_seen[0])

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def serve_websocket_message(self, message):
                pass

        message_seen = [None]

        def messages():
            for msg in (b"\x00", b"ping"):
                message_seen[0] = msg
                yield msg

        ws = MagicMock()
        ws.get_messages.return_value = messages()
        httprequest = MagicMock()
        httprequest.user_agent = None

        with patch.object(websocket_module, "WebsocketRequest", _Request):
            WebsocketConnectionHandler._serve_forever(
                ws, "db", httprequest, WebsocketConnectionHandler._VERSION
            )
        self.assertEqual(built, [b"ping"], "only the non-sentinel message is served")

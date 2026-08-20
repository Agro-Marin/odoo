import gc
import weakref
from unittest.mock import MagicMock, patch

from odoo.tests import BaseCase, tagged

from .. import websocket as websocket_module
from ..websocket import WebsocketConnectionHandler


@tagged("-at_install", "post_install")
class TestServeMessageLifetime(BaseCase):
    """A served request must not outlive the message it served.

    ``_serve_forever`` blocks in ``websocket.get_messages()`` between messages,
    and an idle socket can sit there for hours. ``WebsocketRequest`` holds
    ``self.registry`` and ``self.env``, and ``__exit__`` only pops the request
    stack -- it clears neither. So a request still reachable from the serving
    frame pins its registry for the whole idle period, and once that registry
    leaves ``Registry.registries`` (LRU eviction, or an idle drop) this is the
    reference that keeps it alive: the memory the eviction was meant to reclaim
    is never returned.

    ``_serve_forever`` therefore serves each message from ``_serve_message``, so
    the release is structural. This test fails if a later edit inlines that call
    back into the loop.

    The observation has to happen *at the blocking point* -- from inside the
    message generator, between two messages -- not after the loop returns.
    Once ``_serve_forever`` returns, its frame dies and the leaked local goes
    with it, so a check placed after the loop passes either way.
    """

    def _reachable_between_messages(self):
        """Serve one message, then report whether its request is still
        reachable at the point where the real loop blocks for the next one.
        """
        built = []
        observed = []

        class _Request:
            def __init__(self, db, httprequest, ws):
                # Stand-in for the registry/environment a real request holds.
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
            # The serve loop is suspended here: this is exactly where it waits
            # for the next frame, holding whatever the previous iteration left
            # bound. Sample reachability now.
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
        """The request built for a message is unreachable once it is served."""
        self.assertFalse(
            self._reachable_between_messages(),
            "the served request is still reachable while the loop waits for the "
            "next message: it is pinning its registry and environment for as "
            "long as the socket stays open. Serve each message from its own "
            "frame (WebsocketConnectionHandler._serve_message) instead of "
            "binding it in the serve loop.",
        )

    def test_sentinel_messages_build_no_request(self):
        """The keep-alive sentinel is skipped before a request is built."""
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

import json
import time
from collections import deque
from unittest.mock import patch

try:
    from websocket import ABNF
    from websocket._abnf import VALID_CLOSE_STATUS
    from websocket._exceptions import WebSocketProtocolException
except ImportError:
    pass

from odoo.tests import common
from odoo.tests.common import BaseCase

from ..websocket import CloseCode, Opcode, RateLimitExceededError, Websocket
from .common import WebsocketCase
from .test_websocket_protocol import _client_frame


@common.tagged("-at_install", "post_install")
class TestRateLimiterUnit(BaseCase):
    """Deterministic unit tests for ``Websocket._limit_rate``, driven by an
    injected clock so the limiter arithmetic is covered without real
    ``time.sleep`` calls or socket round-trips (the over-the-wire tests below
    remain as end-to-end smoke tests). This is what the ``clock`` injection on
    ``Websocket`` was added for.
    """

    BURST = 4
    DELAY = 1.0

    def _make_ws(self, clock):
        ws = Websocket.__new__(Websocket)
        ws._clock = clock
        # Instance attributes shadow the config-derived class attributes so the
        # test is independent of the deployment's configured limits.
        ws.RL_DELAY = self.DELAY
        ws.RL_CONTROL_FACTOR = Websocket.RL_CONTROL_FACTOR
        ws._incoming_frame_timestamps = deque(maxlen=self.BURST)
        ws._incoming_control_frame_timestamps = deque(
            maxlen=self.BURST * Websocket.RL_CONTROL_FACTOR
        )
        return ws

    def test_burst_is_allowed_then_blocks_within_the_window(self):
        now = [0.0]
        ws = self._make_ws(lambda: now[0])
        # A full burst at the same instant is accepted.
        for _ in range(self.BURST):
            ws._limit_rate(Opcode.TEXT)
        # One more within ``DELAY * BURST`` trips the limiter.
        with self.assertRaises(RateLimitExceededError):
            ws._limit_rate(Opcode.TEXT)

    def test_respecting_the_rate_never_blocks(self):
        now = [0.0]
        ws = self._make_ws(lambda: now[0])
        # Exactly one data frame per ``DELAY`` is the sustainable rate.
        for _ in range(self.BURST * 3):
            ws._limit_rate(Opcode.TEXT)
            now[0] += self.DELAY

    def test_control_frames_use_a_separate_larger_budget(self):
        now = [0.0]
        ws = self._make_ws(lambda: now[0])
        # Exhaust the data budget: it must not affect the control budget.
        for _ in range(self.BURST):
            ws._limit_rate(Opcode.TEXT)
        for _ in range(self.BURST * Websocket.RL_CONTROL_FACTOR):
            ws._limit_rate(Opcode.PING)
        # The control budget is ``RL_CONTROL_FACTOR`` times larger, but a flood
        # beyond it still trips the (separate) control limiter.
        with self.assertRaises(RateLimitExceededError):
            ws._limit_rate(Opcode.PING)


@common.tagged("post_install", "-at_install")
class TestWebsocketRateLimiting(WebsocketCase):
    def setUp(self):
        super().setUp()
        # Small limits: the tests must not sleep for seconds per request nor
        # be sensitive to scheduling latency. Patched before any connection
        # is opened (the limiter deques are sized at connection time).
        self.startPatcher(patch.object(Websocket, "RL_BURST", 4))
        self.startPatcher(patch.object(Websocket, "RL_DELAY", 0.05))

    def assert_alive(self, ws):
        """Assert the server did not close the connection: a full ping/pong
        round-trip still succeeds (client-side ``ws.connected`` cannot see a
        server-initiated close)."""
        ws.ping()
        opcode, _frame = ws.recv_data_frame(control_frame=True)
        self.assertEqual(opcode, ABNF.OPCODE_PONG)

    def assert_rate_limited(self, ws):
        """Assert the server closed the connection with TRY_LATER."""
        if 1013 not in VALID_CLOSE_STATUS:
            # Websocket client's close codes are not up to date. Indeed, the
            # 1013 close code results in a protocol exception while it is a
            # valid, registered close code ("TRY LATER") :
            # https://www.iana.org/assignments/websocket/websocket.xhtml
            with self.assertRaises(WebSocketProtocolException) as cm:
                self.assert_close_with_code(ws, CloseCode.TRY_LATER)
            self.assertEqual(str(cm.exception), "Invalid close opcode.")
        else:
            self.assert_close_with_code(ws, CloseCode.TRY_LATER)

    def test_rate_limiting_base_ok(self):
        ws = self.websocket_connect()
        for _ in range(Websocket.RL_BURST + 1):
            ws.send(json.dumps({"event_name": "test_rate_limiting"}))
            time.sleep(Websocket.RL_DELAY * 1.25)
        self.assert_alive(ws)

    def test_rate_limiting_base_ko(self):
        ws = self.websocket_connect()
        for _ in range(Websocket.RL_BURST + 1):
            ws.send(json.dumps({"event_name": "test_rate_limiting"}))
        self.assert_rate_limited(ws)

    def test_rate_limiting_opening_burst(self):
        ws = self.websocket_connect()

        # burst is allowed
        for _ in range(Websocket.RL_BURST // 2):
            ws.send(json.dumps({"event_name": "test_rate_limiting"}))

        # as long as the rate is respected afterwards
        for _ in range(Websocket.RL_BURST):
            time.sleep(Websocket.RL_DELAY * 2)
            ws.send(json.dumps({"event_name": "test_rate_limiting"}))

        self.assert_alive(ws)

    def test_rate_limiting_start_ok_end_ko(self):
        ws = self.websocket_connect()

        # first requests are legit and should be accepted
        for _ in range(Websocket.RL_BURST + 1):
            ws.send(json.dumps({"event_name": "test_rate_limiting"}))
            time.sleep(Websocket.RL_DELAY)

        # those requests are illicit and should not be accepted.
        for _ in range(Websocket.RL_BURST * 2):
            ws.send(json.dumps({"event_name": "test_rate_limiting"}))
        self.assert_rate_limited(ws)

    def test_control_frames_do_not_count_against_data_budget(self):
        """A PING burst (e.g. a well-behaved client answering keep-alive)
        must not trip the data-message rate limit."""
        ws = self.websocket_connect()
        # More pings than the data burst allows, back to back.
        for _ in range(Websocket.RL_BURST * 2):
            ws.ping()
            opcode, _frame = ws.recv_data_frame(control_frame=True)
            self.assertEqual(opcode, ABNF.OPCODE_PONG)
        self.assert_alive(ws)

    def test_continuation_frames_do_not_count_against_data_budget(self):
        """A fragmented message counts once (at the frame that begins it),
        no matter how many continuation frames it spans."""
        ws = self.websocket_connect()
        message = json.dumps({"event_name": "test_rate_limiting"}).encode()
        fragments = [message[i : i + 2] for i in range(0, len(message), 2)]
        self.assertGreater(len(fragments), Websocket.RL_BURST)
        ws.sock.sendall(_client_frame(Opcode.TEXT, fragments[0], fin=False))
        for fragment in fragments[1:-1]:
            ws.sock.sendall(_client_frame(Opcode.CONTINUE, fragment, fin=False))
        ws.sock.sendall(_client_frame(Opcode.CONTINUE, fragments[-1], fin=True))
        self.assert_alive(ws)

    def test_control_frame_flood_is_rate_limited(self):
        """Control frames have their own (generous) budget: a PING flood
        cannot bypass rate limiting entirely."""
        ws = self.websocket_connect()
        for _ in range(Websocket.RL_BURST * Websocket.RL_CONTROL_FACTOR + 1):
            ws.ping()
        self.assert_rate_limited(ws)

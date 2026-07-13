import base64
import json
import os
import struct
from unittest.mock import MagicMock, patch

from werkzeug.exceptions import BadRequest, ServiceUnavailable

from odoo.db import PoolError
from odoo.http import SessionExpiredException
from odoo.tests.common import BaseCase, tagged

try:
    from websocket import ABNF, WebSocketConnectionClosedException
except ImportError:
    ABNF = WebSocketConnectionClosedException = None

from .. import websocket as websocket_module
from ..websocket import (
    MAX_TRY_ON_POOL_ERROR,
    CloseCode,
    CloseFrame,
    ConnectionClosedError,
    ConnectionState,
    ControlCommand,
    Frame,
    InvalidCloseCodeError,
    NotificationDispatchState,
    Opcode,
    PayloadTooLargeError,
    PollablePriorityQueue,
    ProtocolError,
    TimeoutManager,
    UpgradeRequired,
    Websocket,
    WebsocketConnectionHandler,
    _follow_session_chain,
    acquire_cursor,
)
from .common import WebsocketCase


class _ManualClock:
    """Deterministic, injectable clock for dispatch-state tests."""

    def __init__(self, now=0.0):
        self.now = now

    def __call__(self):
        return self.now


class _FakeSocket:
    """Minimal socket stand-in feeding queued bytes to ``Websocket``.

    ``recv`` drains the buffer (returning ``b""`` when empty, which the codec
    treats as a peer disconnect); ``sendall`` captures outgoing bytes.
    """

    def __init__(self, data=b""):
        self._buf = bytearray(data)
        self.sent = bytearray()

    def recv(self, n):
        if not self._buf:
            return b""
        chunk = bytes(self._buf[:n])
        del self._buf[:n]
        return chunk

    def sendall(self, data):
        self.sent.extend(data)


def _client_frame(
    opcode, payload=b"", *, fin=True, rsv1=False, masked=True, seven_bit_len=None
):
    """Build the bytes of a client→server WebSocket frame.

    Uses an all-zero masking key (identity mask) so payloads stay readable.
    ``seven_bit_len``/``masked``/``rsv1`` allow crafting malformed frames.
    """
    b0 = (0x80 if fin else 0) | (0x40 if rsv1 else 0) | int(opcode)
    out = bytearray([b0])
    length = len(payload) if seven_bit_len is None else seven_bit_len
    mask_bit = 0x80 if masked else 0
    if length < 126:
        out.append(mask_bit | length)
    elif length < 65536:
        out.append(mask_bit | 126)
        out += struct.pack("!H", length)
    else:
        out.append(mask_bit | 127)
        out += struct.pack("!Q", length)
    if masked:
        out += b"\x00\x00\x00\x00"
    out += payload
    return bytes(out)


@tagged("-at_install", "post_install")
class TestHandshakeValidation(BaseCase):
    """Tests for ``WebsocketConnectionHandler._assert_handshake_validity``.

    These cover the error branches that integration tests skip because
    ``websocket-client`` always sends valid handshakes.
    """

    def _valid_headers(self):
        """Return a minimal set of valid WebSocket handshake headers."""
        return {
            "connection": "Upgrade",
            "host": "localhost:8069",
            "sec-websocket-key": base64.b64encode(b"0123456789abcdef").decode(),
            "sec-websocket-version": "13",
            "upgrade": "websocket",
            "origin": "http://localhost:8069",
        }

    def test_valid_handshake_succeeds(self):
        """A well-formed handshake does not raise."""
        WebsocketConnectionHandler._assert_handshake_validity(self._valid_headers())

    def test_missing_required_header(self):
        """Each required header, when absent, triggers BadRequest."""
        for header in WebsocketConnectionHandler._REQUIRED_HANDSHAKE_HEADERS:
            headers = self._valid_headers()
            del headers[header]
            with self.assertRaises(BadRequest, msg=f"Missing {header!r} should raise"):
                WebsocketConnectionHandler._assert_handshake_validity(headers)

    def test_wrong_upgrade_value(self):
        """Upgrade header must be 'websocket' (case-insensitive)."""
        headers = self._valid_headers()
        headers["upgrade"] = "h2c"
        with self.assertRaises(BadRequest):
            WebsocketConnectionHandler._assert_handshake_validity(headers)

    def test_wrong_connection_value(self):
        """Connection header must contain 'upgrade'."""
        headers = self._valid_headers()
        headers["connection"] = "keep-alive"
        with self.assertRaises(BadRequest):
            WebsocketConnectionHandler._assert_handshake_validity(headers)

    def test_unsupported_version(self):
        """An unsupported WebSocket version triggers UpgradeRequired (426)."""
        headers = self._valid_headers()
        headers["sec-websocket-version"] = "8"
        with self.assertRaises(UpgradeRequired):
            WebsocketConnectionHandler._assert_handshake_validity(headers)

    def test_key_not_valid_base64(self):
        """A non-base64 key triggers BadRequest."""
        headers = self._valid_headers()
        headers["sec-websocket-key"] = "not!valid!base64"
        with self.assertRaises(BadRequest):
            WebsocketConnectionHandler._assert_handshake_validity(headers)

    def test_key_wrong_decoded_length(self):
        """A base64 key that decodes to != 16 bytes triggers BadRequest."""
        headers = self._valid_headers()
        headers["sec-websocket-key"] = base64.b64encode(b"short").decode()
        with self.assertRaises(BadRequest):
            WebsocketConnectionHandler._assert_handshake_validity(headers)

    def test_handshake_response_has_correct_status(self):
        """A valid handshake produces a 101 Switching Protocols response."""
        headers = self._valid_headers()
        response = WebsocketConnectionHandler._get_handshake_response(headers)
        self.assertEqual(response.status_code, 101)
        self.assertEqual(response.headers["Upgrade"], "websocket")
        self.assertEqual(response.headers["Connection"], "Upgrade")
        self.assertIn("Sec-WebSocket-Accept", response.headers)


@tagged("-at_install", "post_install")
class TestFrameClasses(BaseCase):
    """Tests for Frame and CloseFrame construction and __slots__."""

    def test_frame_has_slots(self):
        """Frame uses __slots__ and does not have __dict__."""
        frame = Frame(Opcode.TEXT, b"hello")
        self.assertFalse(hasattr(frame, "__dict__"))
        self.assertEqual(frame.opcode, Opcode.TEXT)
        self.assertEqual(frame.payload, b"hello")
        self.assertTrue(frame.fin)

    def test_frame_defaults(self):
        """Frame defaults: fin=True, rsv1/2/3=False, payload=b''."""
        frame = Frame(Opcode.PING)
        self.assertEqual(frame.payload, b"")
        self.assertTrue(frame.fin)
        self.assertFalse(frame.rsv1)
        self.assertFalse(frame.rsv2)
        self.assertFalse(frame.rsv3)

    def test_close_frame_valid_code(self):
        """CloseFrame with a valid code constructs successfully."""
        frame = CloseFrame(CloseCode.CLEAN, "goodbye")
        self.assertEqual(frame.code, CloseCode.CLEAN)
        self.assertEqual(frame.reason, "goodbye")
        self.assertEqual(frame.opcode, Opcode.CLOSE)
        # Payload starts with the 2-byte code
        self.assertEqual(len(frame.payload), 2 + len(b"goodbye"))

    def test_close_frame_no_reason(self):
        """CloseFrame with None reason has a 2-byte payload (code only)."""
        frame = CloseFrame(CloseCode.GOING_AWAY, None)
        self.assertEqual(len(frame.payload), 2)

    def test_close_frame_invalid_code(self):
        """CloseFrame with an invalid code raises InvalidCloseCodeError."""
        with self.assertRaises(InvalidCloseCodeError):
            CloseFrame(9999, "bad code")

    def test_close_frame_reserved_code_accepted(self):
        """Codes in the 3000-4999 reserved range are accepted."""
        frame = CloseFrame(4001, "custom")
        self.assertEqual(frame.code, 4001)

    def test_close_frame_has_slots(self):
        """CloseFrame inherits __slots__ and has no __dict__."""
        frame = CloseFrame(CloseCode.CLEAN, None)
        self.assertFalse(hasattr(frame, "__dict__"))

    def test_close_frame_reason_truncated(self):
        """An oversized reason (e.g. ``str(exc)``) is truncated so the control
        payload fits the 125-byte RFC 6455 limit instead of making the close
        frame unsendable."""
        frame = CloseFrame(CloseCode.CLEAN, "x" * 500)
        self.assertEqual(len(frame.payload), 2 + CloseFrame.MAX_REASON_LENGTH)
        self.assertEqual(frame.reason, "x" * CloseFrame.MAX_REASON_LENGTH)

    def test_close_frame_reason_truncation_keeps_utf8_valid(self):
        """Truncation must not split a multi-byte UTF-8 sequence (peers reject
        invalid UTF-8 close reasons with INCONSISTENT_DATA)."""
        frame = CloseFrame(CloseCode.CLEAN, "é" * 100)  # 200 bytes encoded
        self.assertLessEqual(len(frame.payload), 125)
        # 123 // 2 = 61 whole chars; the dangling half-é byte is dropped.
        self.assertEqual(frame.reason, "é" * 61)
        frame.payload[2:].decode("utf-8")  # must not raise


@tagged("-at_install", "post_install")
class TestFollowSessionChain(BaseCase):
    """Tests for ``_follow_session_chain`` session rotation resolution."""

    def _make_session(self, sid, next_sid=None):
        """Create a dict-like session mock."""
        session = {"sid": sid}
        if next_sid is not None:
            session["next_sid"] = next_sid
        # Make it behave like an object with .sid attribute for initial_session
        return session

    def _make_store(self, sessions):
        """Create a session store mock that returns sessions by sid."""
        store = MagicMock()
        store.get = MagicMock(side_effect=sessions.get)
        return store

    def test_direct_session_no_chain(self):
        """A session without next_sid returns immediately."""
        session = self._make_session("abc")
        sessions = {"abc": session}
        initial = MagicMock()
        initial.sid = "abc"
        with patch("odoo.addons.bus.websocket.root") as mock_root:
            mock_root.session_store = self._make_store(sessions)
            result = _follow_session_chain(initial)
        self.assertEqual(result["sid"], "abc")

    def test_one_hop_chain(self):
        """A session that rotated once follows the next_sid."""
        old = self._make_session("old", next_sid="new")
        new = self._make_session("new")
        sessions = {"old": old, "new": new}
        initial = MagicMock()
        initial.sid = "old"
        with patch("odoo.addons.bus.websocket.root") as mock_root:
            mock_root.session_store = self._make_store(sessions)
            result = _follow_session_chain(initial)
        self.assertEqual(result["sid"], "new")

    def test_missing_session_raises(self):
        """A missing session in the chain raises SessionExpiredException."""
        initial = MagicMock()
        initial.sid = "gone"
        with patch("odoo.addons.bus.websocket.root") as mock_root:
            mock_root.session_store = self._make_store({})  # empty store
            with self.assertRaises(SessionExpiredException):
                _follow_session_chain(initial)

    def test_chain_exceeds_limit_raises(self):
        """A chain longer than 10 hops raises SessionExpiredException."""
        sessions = {}
        for i in range(15):
            sessions[f"s{i}"] = self._make_session(f"s{i}", next_sid=f"s{i + 1}")
        sessions["s15"] = self._make_session("s15")  # terminal
        initial = MagicMock()
        initial.sid = "s0"
        with patch("odoo.addons.bus.websocket.root") as mock_root:
            mock_root.session_store = self._make_store(sessions)
            with self.assertRaises(SessionExpiredException):
                _follow_session_chain(initial)


@tagged("-at_install", "post_install")
class TestAcquireCursor(BaseCase):
    """Tests for ``acquire_cursor`` retry logic on PoolError."""

    def test_succeeds_on_first_try(self):
        """When no PoolError occurs, the cursor is yielded directly."""
        mock_cr = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_cr)
        mock_cm.__exit__ = MagicMock(return_value=False)
        mock_registry = MagicMock()
        mock_registry.cursor.return_value = mock_cm

        with (
            patch("odoo.addons.bus.websocket.Registry", return_value=mock_registry),
            patch("time.sleep"),
        ):
            with acquire_cursor("testdb") as cr:
                self.assertIs(cr, mock_cr)

    def test_retries_on_transient_pool_error(self):
        """A transient PoolError is retried; cursor is obtained on second attempt."""
        mock_cr = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_cr)
        mock_cm.__exit__ = MagicMock(return_value=False)

        call_count = 0

        def cursor_side_effect():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise PoolError("pool exhausted")
            return mock_cm

        mock_registry = MagicMock()
        mock_registry.cursor.side_effect = cursor_side_effect

        with (
            patch("odoo.addons.bus.websocket.Registry", return_value=mock_registry),
            patch("time.sleep"),
        ):
            with acquire_cursor("testdb") as cr:
                self.assertIs(cr, mock_cr)
        self.assertEqual(call_count, 2)

    def test_raises_after_max_retries(self):
        """After MAX_TRY_ON_POOL_ERROR failures, PoolError propagates."""
        mock_registry = MagicMock()
        mock_registry.cursor.side_effect = PoolError("always busy")

        with (
            patch("odoo.addons.bus.websocket.Registry", return_value=mock_registry),
            patch("time.sleep"),
        ):
            with self.assertRaises(PoolError):
                with acquire_cursor("testdb"):
                    pass  # pragma: no cover

    def test_no_backoff_sleep_after_final_attempt(self):
        """When every attempt fails, no backoff sleep runs after the last one:
        the delays grow exponentially and the final sleep alone would stall
        the caller for several extra seconds before raising."""
        mock_registry = MagicMock()
        mock_registry.cursor.side_effect = PoolError("always busy")

        with (
            patch("odoo.addons.bus.websocket.Registry", return_value=mock_registry),
            patch("time.sleep") as mock_sleep,
        ):
            with self.assertRaises(PoolError):
                with acquire_cursor("testdb"):
                    pass  # pragma: no cover
        # Only the sleeps *between* attempts remain (the sleep(0) thread
        # yields are filtered out).
        backoff_sleeps = [
            call for call in mock_sleep.call_args_list if call.args[0] > 0
        ]
        self.assertEqual(len(backoff_sleeps), MAX_TRY_ON_POOL_ERROR - 1)

    def test_pool_error_from_body_not_swallowed(self):
        """A PoolError raised by the caller *after* the cursor is yielded must
        propagate untouched — it must NOT be caught and retried by
        ``acquire_cursor`` (the whole reason for its explicit __enter__/__exit__
        protocol instead of ``suppress(PoolError)``)."""
        mock_cr = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_cr)
        mock_cm.__exit__ = MagicMock(return_value=False)
        mock_registry = MagicMock()
        mock_registry.cursor.return_value = mock_cm

        with (
            patch("odoo.addons.bus.websocket.Registry", return_value=mock_registry),
            patch("time.sleep"),
        ):
            with self.assertRaises(PoolError):
                with acquire_cursor("testdb"):
                    raise PoolError("raised by caller body")
        # The cursor was acquired exactly once: the body's PoolError was not
        # swallowed and retried.
        self.assertEqual(mock_registry.cursor.call_count, 1)
        mock_cm.__exit__.assert_called_once()


@tagged("-at_install", "post_install")
class TestNotificationDispatchState(BaseCase):
    """Tests for the notification dedup / hold-back state machine.

    This is the module's subtlest logic (out-of-order commits, holding the
    low-water-mark id back so lower ids committed late are not skipped) and was
    previously only reachable through a live websocket. See
    ``Websocket.MAX_NOTIFICATION_HISTORY_SEC``.
    """

    def _make_state(self, retention_sec=10, now=100.0):
        clock = _ManualClock(now)
        return NotificationDispatchState(retention_sec, clock=clock), clock

    def test_initialize_last_id_only_adopts_client_value_once(self):
        state, _clock = self._make_state()
        state.initialize_last_id(5)
        self.assertEqual(state.last_id, 5)
        # Later client values are ignored: the server is authoritative.
        state.initialize_last_id(99)
        self.assertEqual(state.last_id, 5)

    def test_dispatched_ids_are_held_as_ignore_ids(self):
        state, _clock = self._make_state()
        state.record_dispatched([3, 7])
        self.assertEqual(state.last_id, 0)
        self.assertEqual(state.ignore_ids, [3, 7])

    def test_out_of_order_lower_id_is_still_held(self):
        """A lower id arriving after a higher one is inserted in id order and
        held; last_id does not advance while any id is still fresh."""
        state, clock = self._make_state()
        state.record_dispatched([3, 7])
        clock.now = 101.0
        state.record_dispatched([6])
        self.assertEqual(state.ignore_ids, [3, 6, 7])
        self.assertEqual(state.last_id, 0)

    def test_last_id_advances_past_contiguous_expired_prefix(self):
        state, clock = self._make_state()
        state.record_dispatched([3, 6, 7])
        # 11s later, every id has aged past the 10s retention.
        clock.now = 111.0
        state.record_dispatched([])
        self.assertEqual(state.last_id, 7)
        self.assertEqual(state.ignore_ids, [])

    def test_recent_low_id_blocks_trimming_of_older_higher_id(self):
        """The key invariant: an id cannot be forgotten while a *smaller* id is
        still held, otherwise ``id > last_id`` would re-fetch it."""
        state, clock = self._make_state()
        state.record_dispatched([6])  # id 6, old
        clock.now = 108.0
        state.record_dispatched([3])  # id 3, recent, lower
        clock.now = 109.0
        state.record_dispatched([])
        # id 3 is still fresh -> the scan stops at it -> nothing trimmed, even
        # though id 6 is old.
        self.assertEqual(state.last_id, 0)
        self.assertEqual(state.ignore_ids, [3, 6])
        # Once id 3 also expires, both are dropped and last_id jumps to 6.
        clock.now = 200.0
        state.record_dispatched([])
        self.assertEqual(state.last_id, 6)
        self.assertEqual(state.ignore_ids, [])

    def test_history_is_capped(self):
        """The history is bounded: when more than MAX_HISTORY_LENGTH ids are
        dispatched within the retention window, the oldest (lowest) ids are
        dropped and last_id advances past them so they cannot be re-fetched.
        """
        state, _clock = self._make_state()
        with patch.object(NotificationDispatchState, "MAX_HISTORY_LENGTH", 4):
            state.record_dispatched([1, 2, 3, 4])
            self.assertEqual(state.ignore_ids, [1, 2, 3, 4])
            with self.assertLogs("odoo.addons.bus.websocket", level="DEBUG") as log:
                state.record_dispatched([5, 6])
            self.assertIn("history capped", log.output[0])
            # The two lowest ids were dropped and last_id advanced past them.
            self.assertEqual(state.ignore_ids, [3, 4, 5, 6])
            self.assertEqual(state.last_id, 2)

    def test_cap_does_not_bite_below_limit(self):
        """Ids within the retention window are never dropped while the
        history is below the cap."""
        state, clock = self._make_state()
        with patch.object(NotificationDispatchState, "MAX_HISTORY_LENGTH", 4):
            state.record_dispatched([1, 2, 3])
            clock.now = 105.0
            state.record_dispatched([4])
            self.assertEqual(state.ignore_ids, [1, 2, 3, 4])
            self.assertEqual(state.last_id, 0)


@tagged("-at_install", "post_install")
class TestFrameCodec(BaseCase):
    """Tests for frame parsing, protocol errors and fragmented reassembly.

    ``websocket-client`` only ever sends well-formed, unfragmented frames, so
    these paths were entirely untested. Drives a bare ``Websocket`` fed by a
    fake socket (no DB, no selector)."""

    def _make_ws(self, incoming=b""):
        ws = Websocket.__new__(Websocket)
        sock = _FakeSocket(incoming)
        # Assign the name-mangled private socket attribute used by the codec.
        ws._Websocket__socket = sock
        ws._timeout_manager = TimeoutManager()
        ws.state = ConnectionState.OPEN
        ws._close_sent = False
        ws._close_received = False
        # Bypass rate limiting for codec tests.
        ws._limit_rate = lambda opcode: None
        return ws, sock

    # --- successful parsing / reassembly ---

    def test_single_text_frame(self):
        ws, _ = self._make_ws(_client_frame(Opcode.TEXT, b"hello"))
        self.assertEqual(ws._process_next_message(), "hello")

    def test_fragmented_text_message_is_reassembled(self):
        data = _client_frame(Opcode.TEXT, b"Hello ", fin=False) + _client_frame(
            Opcode.CONTINUE, b"World", fin=True
        )
        ws, _ = self._make_ws(data)
        self.assertEqual(ws._process_next_message(), "Hello World")

    def test_control_frame_interleaved_in_fragmented_message(self):
        """A PING arriving mid-fragment is answered with a PONG, then the
        fragmented data message still reassembles correctly."""
        data = (
            _client_frame(Opcode.TEXT, b"Hello ", fin=False)
            + _client_frame(Opcode.PING, b"ka", fin=True)
            + _client_frame(Opcode.CONTINUE, b"World", fin=True)
        )
        ws, sock = self._make_ws(data)
        self.assertEqual(ws._process_next_message(), "Hello World")
        # A PONG (opcode 0x0A) was sent in response to the interleaved PING.
        self.assertTrue(sock.sent)
        self.assertEqual(sock.sent[0] & 0x0F, int(Opcode.PONG))

    # --- protocol errors in _get_next_frame ---

    def test_reserved_bit_set_raises(self):
        ws, _ = self._make_ws(_client_frame(Opcode.TEXT, b"x", rsv1=True))
        with self.assertRaises(ProtocolError):
            ws._process_next_message()

    def test_unmasked_client_frame_raises(self):
        ws, _ = self._make_ws(_client_frame(Opcode.TEXT, b"x", masked=False))
        with self.assertRaises(ProtocolError):
            ws._process_next_message()

    def test_invalid_opcode_raises(self):
        # 0x03 is a reserved (non-existent) opcode.
        frame = bytes([0x80 | 0x03, 0x80, 0, 0, 0, 0])
        ws, _ = self._make_ws(frame)
        with self.assertRaises(ProtocolError):
            ws._process_next_message()

    def test_oversized_control_frame_raises(self):
        # Control frame declaring a 7-bit length > 125.
        ws, _ = self._make_ws(_client_frame(Opcode.CLOSE, b"", seven_bit_len=126))
        with self.assertRaises(ProtocolError):
            ws._process_next_message()

    def test_fragmented_control_frame_raises(self):
        ws, _ = self._make_ws(_client_frame(Opcode.PING, b"x", fin=False))
        with self.assertRaises(ProtocolError):
            ws._process_next_message()

    def test_payload_too_large_single_frame_raises(self):
        # Declared 64-bit length exceeds MESSAGE_MAX_SIZE; raises before the
        # payload is read.
        frame = (
            bytes([0x80 | int(Opcode.TEXT), 0x80 | 127])
            + struct.pack("!Q", Websocket.MESSAGE_MAX_SIZE + 1)
            + b"\x00\x00\x00\x00"
        )
        ws, _ = self._make_ws(frame)
        with self.assertRaises(PayloadTooLargeError):
            ws._process_next_message()

    def test_unexpected_top_level_continuation_raises(self):
        ws, _ = self._make_ws(_client_frame(Opcode.CONTINUE, b"x", fin=True))
        with self.assertRaises(ProtocolError):
            ws._process_next_message()

    def test_data_frame_where_continuation_expected_raises(self):
        data = _client_frame(Opcode.TEXT, b"a", fin=False) + _client_frame(
            Opcode.TEXT, b"b", fin=True
        )
        ws, _ = self._make_ws(data)
        with self.assertRaises(ProtocolError):
            ws._process_next_message()

    def test_payload_too_large_during_reassembly_raises(self):
        ws, _ = self._make_ws(
            _client_frame(Opcode.TEXT, b"12345", fin=False)
            + _client_frame(Opcode.CONTINUE, b"67890", fin=True)
        )
        ws.MESSAGE_MAX_SIZE = 8  # each fragment fits, the sum does not
        with self.assertRaises(PayloadTooLargeError):
            ws._process_next_message()

    def test_truncated_frame_raises_connection_closed(self):
        # Header claims 5 payload bytes but only 2 are provided.
        truncated = _client_frame(Opcode.TEXT, b"hello")[:-3]
        ws, _ = self._make_ws(truncated)
        with self.assertRaises(ConnectionClosedError):
            ws._process_next_message()


def _parse_server_frame(data):
    """Parse the first (unmasked) server frame from ``data``, returning
    ``(opcode, payload)``."""
    first_byte, second_byte = data[0], data[1]
    opcode = Opcode(first_byte & 0x0F)
    length = second_byte & 0x7F
    offset = 2
    if length == 126:
        length = struct.unpack("!H", data[2:4])[0]
        offset = 4
    elif length == 127:
        length = struct.unpack("!Q", data[2:10])[0]
        offset = 10
    return opcode, bytes(data[offset : offset + length])


@tagged("-at_install", "post_install")
class TestCloseFrameHandling(BaseCase):
    """Unit tests for the close-handshake answer in ``_handle_control_frame``
    (RFC 6455 §5.5.1 / §7.4), driven through a fake socket."""

    def _make_ws(self, incoming=b""):
        ws = Websocket.__new__(Websocket)
        sock = _FakeSocket(incoming)
        ws._Websocket__socket = sock
        ws._timeout_manager = TimeoutManager()
        ws.state = ConnectionState.OPEN
        ws._close_sent = False
        ws._close_received = False
        ws._limit_rate = lambda opcode: None
        # ``_send_frame`` terminates right after answering a received close;
        # stub the TCP teardown out, it needs the real selector/queue.
        ws._terminate = MagicMock()
        return ws, sock

    def _assert_close_answer(self, sock, expected_code, expected_reason=None):
        opcode, payload = _parse_server_frame(sock.sent)
        self.assertEqual(opcode, Opcode.CLOSE)
        self.assertEqual(struct.unpack("!H", payload[:2])[0], expected_code)
        if expected_reason is not None:
            self.assertEqual(payload[2:].decode(), expected_reason)

    def test_legal_close_is_echoed(self):
        """A legal close code and reason are echoed back to the peer."""
        payload = struct.pack("!H", CloseCode.CLEAN) + b"bye"
        ws, sock = self._make_ws(_client_frame(Opcode.CLOSE, payload))
        ws._process_next_message()
        self._assert_close_answer(sock, CloseCode.CLEAN, "bye")
        ws._terminate.assert_called_once()

    def test_reserved_range_close_code_is_echoed(self):
        """Codes in the 3000-4999 reserved range are legal on the wire."""
        payload = struct.pack("!H", 4242)
        ws, sock = self._make_ws(_client_frame(Opcode.CLOSE, payload))
        ws._process_next_message()
        self._assert_close_answer(sock, 4242)

    def test_invalid_close_code_answered_with_protocol_error(self):
        """An illegal close code (here: below 1000) must be answered with
        1002 PROTOCOL_ERROR, not echoed (the echo would raise
        InvalidCloseCodeError and hard-terminate the connection)."""
        for bad_code in (999, 1005, 1006, 1015, 2999):
            ws, sock = self._make_ws(
                _client_frame(Opcode.CLOSE, struct.pack("!H", bad_code))
            )
            ws._process_next_message()
            self._assert_close_answer(sock, CloseCode.PROTOCOL_ERROR)
            ws._terminate.assert_called_once()

    def test_one_byte_close_payload_answered_with_protocol_error(self):
        """A 1-byte close payload is malformed per RFC 6455 §5.5.1 and must
        be answered with 1002 PROTOCOL_ERROR instead of hard-terminating."""
        ws, sock = self._make_ws(_client_frame(Opcode.CLOSE, b"\x01"))
        ws._process_next_message()
        self._assert_close_answer(sock, CloseCode.PROTOCOL_ERROR)

    def test_invalid_utf8_close_reason_answered_with_inconsistent_data(self):
        """A close reason that is not valid UTF-8 is answered with 1007."""
        payload = struct.pack("!H", CloseCode.CLEAN) + b"\xff\xfe"
        ws, sock = self._make_ws(_client_frame(Opcode.CLOSE, payload))
        ws._process_next_message()
        self._assert_close_answer(sock, CloseCode.INCONSISTENT_DATA)

    def test_empty_close_payload_answered_with_clean(self):
        ws, sock = self._make_ws(_client_frame(Opcode.CLOSE))
        ws._process_next_message()
        self._assert_close_answer(sock, CloseCode.CLEAN)


@tagged("-at_install", "post_install")
class TestOpenConnection(BaseCase):
    """Unit tests for ``WebsocketConnectionHandler.open_connection`` ordering
    and gating (no HTTP stack)."""

    def test_service_unavailable_when_websocket_disabled(self):
        """When ``websocket_allowed`` is False (e.g. test mode) the handshake
        is refused with 503 before any processing."""
        request = MagicMock()
        with patch.object(
            WebsocketConnectionHandler, "websocket_allowed", return_value=False
        ):
            with self.assertRaises(ServiceUnavailable):
                WebsocketConnectionHandler.open_connection(request, "19.0-5")

    def test_public_configuration_runs_after_handshake_validation(self):
        """Regression for the orphaned-session leak: the public-session
        downgrade (and its session-store save) must run only *after* the
        handshake was validated, so a malformed handshake persists nothing.
        """
        request = MagicMock()
        with (
            patch.object(
                WebsocketConnectionHandler, "websocket_allowed", return_value=True
            ),
            patch.object(
                WebsocketConnectionHandler,
                "_get_handshake_response",
                side_effect=BadRequest("bad handshake"),
            ),
            patch.object(
                WebsocketConnectionHandler, "_handle_public_configuration"
            ) as public_config_mock,
        ):
            with self.assertRaises(BadRequest):
                WebsocketConnectionHandler.open_connection(request, "19.0-5")
        public_config_mock.assert_not_called()


@tagged("-at_install", "post_install")
class TestTrustedOrigin(BaseCase):
    """Unit tests for the CSWSH origin policy (``_is_trusted_origin`` /
    ``_normalize_origin``)."""

    def _request(self, scheme, host):
        request = MagicMock()
        request.httprequest.scheme = scheme
        request.httprequest.host = host
        return request

    def test_matching_origin_is_trusted(self):
        request = self._request("http", "example.com:8069")
        self.assertTrue(
            WebsocketConnectionHandler._is_trusted_origin(
                "http://example.com:8069", request
            )
        )

    def test_default_port_is_normalized(self):
        request = self._request("https", "example.com")
        self.assertTrue(
            WebsocketConnectionHandler._is_trusted_origin(
                "https://example.com:443", request
            )
        )

    def test_mismatched_origin_is_not_trusted(self):
        request = self._request("http", "example.com:8069")
        self.assertFalse(
            WebsocketConnectionHandler._is_trusted_origin(
                "http://attacker.example.com", request
            )
        )

    def test_scheme_mismatch_is_not_trusted(self):
        request = self._request("https", "example.com")
        self.assertFalse(
            WebsocketConnectionHandler._is_trusted_origin("http://example.com", request)
        )

    def test_allowlisted_origin_is_trusted(self):
        request = self._request("http", "example.com:8069")
        with patch.dict(
            os.environ,
            {"ODOO_BUS_TRUSTED_ORIGINS": "https://cdn.example.com, http://x.test:9000"},
        ):
            self.assertTrue(
                WebsocketConnectionHandler._is_trusted_origin(
                    "http://x.test:9000", request
                )
            )
            self.assertFalse(
                WebsocketConnectionHandler._is_trusted_origin(
                    "http://not-listed.test", request
                )
            )


@tagged("-at_install", "post_install")
class TestControlCommandPriority(BaseCase):
    def test_queued_close_beats_pending_dispatch(self):
        """A queued CLOSE command is processed before an earlier-queued
        DISPATCH: closing must never be delayed by pending notification
        work."""
        queue = PollablePriorityQueue()
        try:
            queue.put((ControlCommand.DISPATCH, 1, None))
            queue.put((ControlCommand.CLOSE, 2, {"code": CloseCode.CLEAN}))
            command, _, data = queue.get()
            self.assertIs(command, ControlCommand.CLOSE)
            self.assertEqual(data["code"], CloseCode.CLEAN)
            command, _, _data = queue.get()
            self.assertIs(command, ControlCommand.DISPATCH)
        finally:
            queue.close()


@tagged("post_install", "-at_install")
class TestCloseCodesOverWire(WebsocketCase):
    """Close-code matrix asserted over a real socket: the documented close
    code must reach the peer for each error family (the JS worker's
    reconnection strategy keys off these codes, see
    ``websocket_worker_constants.js``)."""

    def test_invalid_utf8_text_frame_closes_1007(self):
        ws = self.websocket_connect()
        ws.send(b"\xff\xfe\xfd", opcode=ABNF.OPCODE_TEXT)
        self.assert_close_with_code(ws, CloseCode.INCONSISTENT_DATA)

    def test_oversized_frame_closes_1009(self):
        self.startPatcher(patch.object(Websocket, "MESSAGE_MAX_SIZE", 1024))
        ws = self.websocket_connect()
        ws.send("x" * 2048)
        self.assert_close_with_code(ws, CloseCode.MESSAGE_TOO_BIG)

    def test_protocol_violation_closes_1002(self):
        # RSV1 set without any negotiated extension is a protocol error.
        ws = self.websocket_connect()
        ws.sock.sendall(_client_frame(Opcode.TEXT, b"x", rsv1=True))
        self.assert_close_with_code(ws, CloseCode.PROTOCOL_ERROR)

    def test_invalid_close_code_answered_with_1002(self):
        ws = self.websocket_connect()
        ws.sock.sendall(_client_frame(Opcode.CLOSE, struct.pack("!H", 999)))
        self.assert_close_with_code(ws, CloseCode.PROTOCOL_ERROR, "Invalid close code")

    def test_one_byte_close_payload_answered_with_1002(self):
        ws = self.websocket_connect()
        ws.sock.sendall(_client_frame(Opcode.CLOSE, b"\x01"))
        self.assert_close_with_code(
            ws, CloseCode.PROTOCOL_ERROR, "Malformed closing frame"
        )

    def test_legal_close_code_and_reason_echoed(self):
        ws = self.websocket_connect()
        ws.sock.sendall(
            _client_frame(Opcode.CLOSE, struct.pack("!H", CloseCode.CLEAN) + b"bye")
        )
        self.assert_close_with_code(ws, CloseCode.CLEAN, "bye")

    def test_malformed_envelope_keeps_connection_alive(self):
        """Non-JSON text, top-level non-dict JSON and a missing event_name
        are rejected on the quiet warning path and must not kill the
        connection (see ``WebsocketConnectionHandler._serve_forever``)."""
        self.startPatcher(patch.object(Websocket, "RL_BURST", 100))
        ws = self.websocket_connect()
        for message in ("not-json{", json.dumps(["top-level-list"]), json.dumps({})):
            with self.assertLogs(
                "odoo.addons.bus.websocket", level="WARNING"
            ) as capture:
                ws.send(message)
                # Frames are handled in order: once the pong arrives, the
                # malformed message above has been processed.
                ws.ping()
                ws.recv_data_frame(control_frame=True)  # pong
            self.assertTrue(
                any("Invalid websocket request" in line for line in capture.output),
                f"message {message!r} should be rejected with a warning",
            )
        # The connection survived: a ping/pong round-trip still works.
        ws.ping()
        opcode, _ = ws.recv_data_frame(control_frame=True)
        self.assertEqual(opcode, ABNF.OPCODE_PONG)

    def test_kill_now_terminates_without_close_handshake(self):
        ws = self.websocket_connect()
        server_ws = next(
            websocket
            for websocket in list(websocket_module._websocket_instances)
            if websocket.state is ConnectionState.OPEN
        )
        server_ws.close(CloseCode.KILL_NOW)
        # No close frame: the TCP connection is dropped outright.
        with self.assertRaises(WebSocketConnectionClosedException):
            ws.recv_data_frame(control_frame=True)

    def test_kick_all_sends_going_away(self):
        ws = self.websocket_connect()
        websocket_module._kick_all()
        self.assert_close_with_code(ws, CloseCode.GOING_AWAY)

    def test_server_pings_after_inactivity_timeout(self):
        self.startPatcher(patch.object(TimeoutManager, "INACTIVITY_TIMEOUT", 0))
        # TIMEOUT also bounds the selector poll: keep it small so the idle
        # loop notices the elapsed inactivity quickly.
        self.startPatcher(patch.object(TimeoutManager, "TIMEOUT", 0.2))
        ws = self.websocket_connect(ping_after_connect=False)
        opcode, _ = ws.recv_data_frame(control_frame=True)
        self.assertEqual(opcode, ABNF.OPCODE_PING)

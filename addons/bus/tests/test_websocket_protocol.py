import base64
import struct
from unittest.mock import MagicMock, patch

from werkzeug.exceptions import BadRequest

from odoo.db import PoolError
from odoo.http import SessionExpiredException
from odoo.tests.common import BaseCase, tagged

from ..websocket import (
    CloseCode,
    CloseFrame,
    ConnectionClosedError,
    ConnectionState,
    Frame,
    InvalidCloseCodeError,
    NotificationDispatchState,
    Opcode,
    PayloadTooLargeError,
    ProtocolError,
    TimeoutManager,
    UpgradeRequired,
    Websocket,
    WebsocketConnectionHandler,
    _follow_session_chain,
    acquire_cursor,
)


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

    def test_initialize_last_id_only_adopts_client_value_once(self):
        state = NotificationDispatchState(10)
        state.initialize_last_id(5)
        self.assertEqual(state.last_id, 5)
        # Later client values are ignored: the server is authoritative.
        state.initialize_last_id(99)
        self.assertEqual(state.last_id, 5)

    def test_dispatched_ids_are_held_as_ignore_ids(self):
        state = NotificationDispatchState(10)
        state.record_dispatched([3, 7], now=100.0)
        self.assertEqual(state.last_id, 0)
        self.assertEqual(state.ignore_ids, [3, 7])

    def test_out_of_order_lower_id_is_still_held(self):
        """A lower id arriving after a higher one is inserted in id order and
        held; last_id does not advance while any id is still fresh."""
        state = NotificationDispatchState(10)
        state.record_dispatched([3, 7], now=100.0)
        state.record_dispatched([6], now=101.0)
        self.assertEqual(state.ignore_ids, [3, 6, 7])
        self.assertEqual(state.last_id, 0)

    def test_last_id_advances_past_contiguous_expired_prefix(self):
        state = NotificationDispatchState(10)
        state.record_dispatched([3, 6, 7], now=100.0)
        # 11s later, every id has aged past the 10s retention.
        state.record_dispatched([], now=111.0)
        self.assertEqual(state.last_id, 7)
        self.assertEqual(state.ignore_ids, [])

    def test_recent_low_id_blocks_trimming_of_older_higher_id(self):
        """The key invariant: an id cannot be forgotten while a *smaller* id is
        still held, otherwise ``id > last_id`` would re-fetch it."""
        state = NotificationDispatchState(10)
        state.record_dispatched([6], now=100.0)  # id 6, old
        state.record_dispatched([3], now=108.0)  # id 3, recent, lower
        state.record_dispatched([], now=109.0)
        # id 3 is still fresh -> the scan stops at it -> nothing trimmed, even
        # though id 6 is old.
        self.assertEqual(state.last_id, 0)
        self.assertEqual(state.ignore_ids, [3, 6])
        # Once id 3 also expires, both are dropped and last_id jumps to 6.
        state.record_dispatched([], now=200.0)
        self.assertEqual(state.last_id, 6)
        self.assertEqual(state.ignore_ids, [])


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
        ws._limit_rate = lambda: None  # bypass rate limiting for codec tests
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
        ws, _ = self._make_ws(
            _client_frame(Opcode.CLOSE, b"", seven_bit_len=126)
        )
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

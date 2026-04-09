import base64
import time
from unittest.mock import MagicMock, PropertyMock, patch

from werkzeug.exceptions import BadRequest

from odoo.db import PoolError
from odoo.http import SessionExpiredException
from odoo.tests.common import BaseCase, tagged

from ..websocket import (
    CloseCode,
    CloseFrame,
    ConnectionState,
    Frame,
    InvalidCloseCodeError,
    Opcode,
    UpgradeRequired,
    WebsocketConnectionHandler,
    _follow_session_chain,
    acquire_cursor,
)


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
        self.assertEqual(len(frame.payload), 2 + len("goodbye".encode()))

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
        store.get = MagicMock(side_effect=lambda sid: sessions.get(sid))
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

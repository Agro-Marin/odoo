from unittest.mock import MagicMock, patch

from odoo.tests import TransactionCase, tagged

from ..models.bus import (
    ImDispatch,
    channel_with_db,
    get_notify_payloads,
    hashable,
)


@tagged("-at_install", "post_install")
class TestHashable(TransactionCase):
    """Tests for the ``hashable()`` utility."""

    def test_list_to_tuple(self):
        self.assertEqual(hashable([1, 2, 3]), (1, 2, 3))

    def test_tuple_passthrough(self):
        val = (1, 2)
        self.assertIs(hashable(val), val)

    def test_string_passthrough(self):
        val = "channel"
        self.assertIs(hashable(val), val)

    def test_int_passthrough(self):
        self.assertEqual(hashable(42), 42)

    def test_nested_list(self):
        """Outer list is converted; inner lists remain (hashable isn't recursive)."""
        result = hashable([[1], [2]])
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)


@tagged("-at_install", "post_install")
class TestChannelWithDb(TransactionCase):
    """Tests for ``channel_with_db()``."""

    def test_string_channel(self):
        self.assertEqual(channel_with_db("mydb", "broadcast"), ("mydb", "broadcast"))

    def test_model_channel(self):
        partner = self.env.user.partner_id
        result = channel_with_db("mydb", partner)
        self.assertEqual(result, ("mydb", "res.partner", partner.id))

    def test_model_with_subchannel(self):
        partner = self.env.user.partner_id
        result = channel_with_db("mydb", (partner, "typing"))
        self.assertEqual(result, ("mydb", "res.partner", partner.id, "typing"))

    def test_pre_qualified_tuple_passthrough(self):
        """Pre-qualified tuples (not Model-based) pass through unchanged."""
        val = ("mydb", "res.partner", 42)
        result = channel_with_db("mydb", val)
        self.assertIs(result, val)


@tagged("-at_install", "post_install")
class TestGetNotifyPayloads(TransactionCase):
    """Tests for ``get_notify_payloads()`` payload splitting."""

    def test_empty_channels(self):
        self.assertEqual(get_notify_payloads([]), [])

    def test_single_channel_never_split(self):
        """A single channel is never split, even if large."""
        fat_channel = ("db", "x" * 10000, 1)
        payloads = get_notify_payloads([fat_channel])
        self.assertEqual(len(payloads), 1)

    def test_small_payload_not_split(self):
        channels = [("db", "model", i) for i in range(5)]
        payloads = get_notify_payloads(channels)
        self.assertEqual(len(payloads), 1)

    def test_large_payload_split(self):
        """Many channels exceeding the max length are split into multiple payloads."""
        channels = [("db", "model_name", i) for i in range(2000)]
        payloads = get_notify_payloads(channels)
        self.assertGreater(len(payloads), 1)
        # All sub-payloads should be valid JSON
        from ..tools import orjson

        for payload in payloads:
            parsed = orjson.loads(payload)
            self.assertIsInstance(parsed, list)


@tagged("-at_install", "post_install")
class TestImDispatchChannelManagement(TransactionCase):
    """Tests for ``ImDispatch`` subscribe/unsubscribe channel bookkeeping."""

    def _make_dispatch(self):
        """Create a fresh ImDispatch without starting the thread."""
        d = ImDispatch()
        # Reset channel state to isolate from the module-level singleton.
        d._channels_to_ws = {}
        return d

    def _make_ws(self):
        """Create a minimal mock websocket with the interface ImDispatch expects."""
        ws = MagicMock()
        ws._channels = set()

        def subscribe_side_effect(channels, last):
            ws._channels = channels

        ws.subscribe.side_effect = subscribe_side_effect
        ws.trigger_notification_dispatching = MagicMock()
        return ws

    def test_subscribe_adds_channels(self):
        d = self._make_dispatch()
        ws = self._make_ws()
        d.subscribe(["ch1", "ch2"], last=0, db="testdb", websocket=ws)
        # ws._channels should now have the qualified channels
        self.assertEqual(len(ws._channels), 2)
        # The dispatch map should have entries
        self.assertEqual(len(d._channels_to_ws), 2)
        for channel_set in d._channels_to_ws.values():
            self.assertIn(ws, channel_set)

    def test_subscribe_replaces_channels(self):
        d = self._make_dispatch()
        ws = self._make_ws()
        d.subscribe(["ch1", "ch2"], last=0, db="testdb", websocket=ws)
        d.subscribe(["ch2", "ch3"], last=1, db="testdb", websocket=ws)
        # ch1 should be removed, ch3 added
        self.assertEqual(len(ws._channels), 2)
        all_channels = set(d._channels_to_ws.keys())
        ch1_key = hashable(channel_with_db("testdb", "ch1"))
        ch3_key = hashable(channel_with_db("testdb", "ch3"))
        self.assertNotIn(ch1_key, all_channels)
        self.assertIn(ch3_key, all_channels)

    def test_unsubscribe_removes_all_channels(self):
        d = self._make_dispatch()
        ws = self._make_ws()
        d.subscribe(["ch1", "ch2"], last=0, db="testdb", websocket=ws)
        d.unsubscribe(ws)
        # All channel sets should be empty or removed
        for channel_set in d._channels_to_ws.values():
            self.assertNotIn(ws, channel_set)

    def test_unsubscribe_cleans_empty_sets(self):
        d = self._make_dispatch()
        ws = self._make_ws()
        d.subscribe(["ch_only"], last=0, db="testdb", websocket=ws)
        self.assertEqual(len(d._channels_to_ws), 1)
        d.unsubscribe(ws)
        # The channel key should be deleted since no websockets remain
        self.assertEqual(len(d._channels_to_ws), 0)

    def test_multiple_websockets_same_channel(self):
        d = self._make_dispatch()
        ws1 = self._make_ws()
        ws2 = self._make_ws()
        d.subscribe(["shared"], last=0, db="testdb", websocket=ws1)
        d.subscribe(["shared"], last=0, db="testdb", websocket=ws2)
        key = hashable(channel_with_db("testdb", "shared"))
        self.assertEqual(len(d._channels_to_ws[key]), 2)
        d.unsubscribe(ws1)
        # ws2 still subscribed
        self.assertEqual(len(d._channels_to_ws[key]), 1)
        self.assertIn(ws2, d._channels_to_ws[key])

    def test_dispatch_to_all_triggers_every_websocket_once(self):
        """``_dispatch_to_all`` (the LISTEN-reconnect catch-up) wakes each
        subscribed websocket exactly once, even when subscribed to several
        channels."""
        d = self._make_dispatch()
        ws1 = self._make_ws()
        ws2 = self._make_ws()
        d._channels_to_ws = {
            ("testdb", "ch1"): {ws1, ws2},
            ("testdb", "ch2"): {ws1},
        }
        d._dispatch_to_all()
        ws1.trigger_notification_dispatching.assert_called_once()
        ws2.trigger_notification_dispatching.assert_called_once()

    def test_dispatch_to_all_without_subscribers(self):
        """``_dispatch_to_all`` on an empty subscription map is a no-op."""
        d = self._make_dispatch()
        d._dispatch_to_all()
        self.assertEqual(d._channels_to_ws, {})


@tagged("-at_install", "post_install")
class TestImDispatchPayloadParsing(TransactionCase):
    """Tests for ``ImDispatch._parse_imbus_payload`` robustness.

    A malformed NOTIFY payload on the imbus channel (foreign NOTIFY,
    custom ``ODOO_NOTIFY_FUNCTION``, ...) must be skipped, not kill the
    dispatch loop for every database.
    """

    def test_valid_payload(self):
        self.assertEqual(
            ImDispatch._parse_imbus_payload('[["db", "ch1"], ["db", "ch2"]]'),
            [["db", "ch1"], ["db", "ch2"]],
        )

    def test_malformed_json_is_skipped(self):
        with self.assertLogs("odoo.addons.bus.models.bus", "WARNING"):
            self.assertEqual(ImDispatch._parse_imbus_payload("{not json"), [])

    def test_non_list_payload_is_skipped(self):
        with self.assertLogs("odoo.addons.bus.models.bus", "WARNING"):
            self.assertEqual(ImDispatch._parse_imbus_payload('{"foo": 1}'), [])


@tagged("-at_install", "post_install")
class TestSendPgNotify(TransactionCase):
    """Tests for ``_send_pg_notify()`` retry logic."""

    def test_retry_on_first_failure(self):
        """First failure closes connection and retries; second attempt succeeds."""
        from ..models.bus import _send_pg_notify

        call_count = 0

        def mock_execute(query, params):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("transient error")

        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_conn.execute = mock_execute

        with (
            patch(
                "odoo.addons.bus.models.bus._get_notify_conn_locked",
                return_value=mock_conn,
            ),
            patch("odoo.addons.bus.models.bus._close_notify_conn_locked") as mock_close,
        ):
            _send_pg_notify(["payload1"])
            # Connection was closed on first failure
            mock_close.assert_called_once()
            # Second attempt succeeded
            self.assertEqual(call_count, 2)

    def test_raises_on_second_failure(self):
        """If both attempts fail, the exception propagates."""
        from ..models.bus import _send_pg_notify

        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_conn.execute.side_effect = Exception("persistent error")

        with (
            patch(
                "odoo.addons.bus.models.bus._get_notify_conn_locked",
                return_value=mock_conn,
            ),
            patch("odoo.addons.bus.models.bus._close_notify_conn_locked"),
        ):
            with self.assertRaisesRegex(Exception, "persistent error"):
                _send_pg_notify(["payload1"])
        # Both attempts were made before giving up.
        self.assertEqual(mock_conn.execute.call_count, 2)

from unittest.mock import MagicMock, patch

import psycopg

from odoo.libs.json import loads as json_loads
from odoo.tests import TransactionCase, tagged
from odoo.tests.common import BaseCase

from ..models import bus as bus_module
from ..models.bus import (
    ImDispatch,
    _send_pg_notify,
    channel_with_db,
    get_notify_payloads,
    hashable,
    json_dump,
)


@tagged("-at_install", "post_install")
class TestHashable(BaseCase):
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
        """Nested lists are recursively converted to tuples."""
        self.assertEqual(hashable([[1], [2]]), ((1,), (2,)))

    def test_deeply_nested_list(self):
        self.assertEqual(hashable([1, [2, [3, []]]]), (1, (2, (3, ()))))

    def test_json_roundtrip_produces_same_key(self):
        """The subscribe side (channel objects) and the dispatch side (the
        same channels after a JSON round trip through the NOTIFY payload)
        must produce identical dict keys."""
        channel = ["db", "model", 1, ["a", ["b"]]]
        roundtripped = json_loads(json_dump(channel))
        self.assertEqual(hashable(channel), hashable(roundtripped))


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
class TestGetNotifyPayloads(BaseCase):
    """Tests for ``get_notify_payloads()`` payload packing."""

    def test_empty_channels(self):
        self.assertEqual(get_notify_payloads([]), [])

    def test_small_payload_not_split(self):
        channels = [("db", "model", i) for i in range(5)]
        payloads = get_notify_payloads(channels)
        self.assertEqual(len(payloads), 1)

    def test_large_payload_split(self):
        """Many channels exceeding the max length are split into multiple
        payloads, each under the limit and all channels preserved in order."""
        channels = [("db", "model_name", i) for i in range(2000)]
        payloads = get_notify_payloads(channels)
        self.assertGreater(len(payloads), 1)
        parsed = []
        for payload in payloads:
            self.assertLess(len(payload.encode()), bus_module.NOTIFY_PAYLOAD_MAX_LENGTH)
            chunk = json_loads(payload)
            self.assertIsInstance(chunk, list)
            parsed.extend(chunk)
        self.assertEqual(parsed, json_loads(json_dump(channels)))

    def test_exact_boundary(self):
        """Packing switches payloads exactly when the encoded size would no
        longer be strictly under the limit."""
        # json_dump(("db", "ch", 1)) == '["db","ch",1]' -> 13 bytes; a payload
        # of k such items encodes to (item_len+1)*k + 1 bytes ("[" + items
        # joined by k-1 commas + "]").
        item_len = len(json_dump(("db", "ch", 1)).encode())
        self.assertEqual(item_len, 13)
        channels = [("db", "ch", 1)] * 3
        size_3 = (item_len + 1) * 3 + 1  # encoded size of a 3-item payload
        # At the exact boundary, a 3-item payload is NOT strictly under the
        # limit, so packing flushes after the 2nd item.
        with patch.object(bus_module, "NOTIFY_PAYLOAD_MAX_LENGTH", size_3):
            self.assertEqual(
                [len(json_loads(p)) for p in get_notify_payloads(channels)], [2, 1]
            )
        # One byte more of headroom and all 3 fit in a single payload.
        with patch.object(bus_module, "NOTIFY_PAYLOAD_MAX_LENGTH", size_3 + 1):
            self.assertEqual(
                [len(json_loads(p)) for p in get_notify_payloads(channels)], [3]
            )

    def test_single_oversized_channel_skipped(self):
        """A channel that cannot fit in a payload on its own is dropped with
        a warning instead of being emitted as a guaranteed-failing NOTIFY."""
        fat_channel = ("db", "x" * 10000, 1)
        with self.assertLogs("odoo.addons.bus.models.bus", "WARNING"):
            self.assertEqual(get_notify_payloads([fat_channel]), [])

    def test_oversized_channel_skipped_others_kept(self):
        """Dropping an oversized channel does not affect its neighbours."""
        small_before = ("db", "before", 1)
        fat_channel = ("db", "x" * 10000, 1)
        small_after = ("db", "after", 2)
        with self.assertLogs("odoo.addons.bus.models.bus", "WARNING"):
            payloads = get_notify_payloads([small_before, fat_channel, small_after])
        self.assertEqual(len(payloads), 1)
        self.assertEqual(
            json_loads(payloads[0]), [["db", "before", 1], ["db", "after", 2]]
        )


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

    def test_collect_websockets_matches_subscription(self):
        """Dispatch-side channels (nested JSON lists) map to the same key as
        subscribe-side channels."""
        d = self._make_dispatch()
        ws = self._make_ws()
        d.subscribe(["ch1"], last=0, db="testdb", websocket=ws)
        # The dispatch loop receives the channel as a JSON list.
        self.assertEqual(d._collect_websockets([["testdb", "ch1"]]), {ws})
        self.assertEqual(d._collect_websockets([["testdb", "other"]]), set())

    def test_collect_websockets_nested_list_channel(self):
        """A channel containing nested lists (from a NOTIFY payload) must not
        raise and must match the equivalent subscription."""
        d = self._make_dispatch()
        ws = self._make_ws()
        nested_channel = ["testdb", "res.partner", 1, ["sub", ["deep"]]]
        # channel_with_db passes non-str/Model channels through unchanged, so
        # the subscribe side stores hashable(nested_channel) as the key.
        d.subscribe([nested_channel], last=0, db="testdb", websocket=ws)
        roundtripped = json_loads(json_dump(nested_channel))
        self.assertEqual(d._collect_websockets([roundtripped]), {ws})

    def test_collect_websockets_unhashable_channel_skipped(self):
        """A channel that cannot be hashed (e.g. contains a JSON object) is
        warned about and skipped; the remaining channels still dispatch."""
        d = self._make_dispatch()
        ws = self._make_ws()
        d.subscribe(["ch1"], last=0, db="testdb", websocket=ws)
        with self.assertLogs("odoo.addons.bus.models.bus", "WARNING"):
            websockets = d._collect_websockets(
                [["testdb", {"bad": "channel"}], ["testdb", "ch1"]]
            )
        self.assertEqual(websockets, {ws})

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

    def test_dispatch_to_all_staggers_wakeups(self):
        """``_dispatch_to_all`` pauses between chunks of websockets so a
        reconnect catch-up cannot stampede the cursor pool."""
        d = self._make_dispatch()
        websockets = [self._make_ws() for _ in range(5)]
        d._channels_to_ws = {
            ("testdb", f"ch{i}"): {ws} for i, ws in enumerate(websockets)
        }
        mock_stop = MagicMock()
        mock_stop.wait.return_value = False
        with (
            patch.object(bus_module, "DISPATCH_CATCHUP_CHUNK_SIZE", 2),
            patch.object(bus_module, "stop_event", mock_stop),
        ):
            d._dispatch_to_all()
        for ws in websockets:
            ws.trigger_notification_dispatching.assert_called_once()
        # 5 websockets in chunks of 2 -> a pause before the 3rd and 5th.
        self.assertEqual(mock_stop.wait.call_count, 2)

    def test_dispatch_to_all_aborts_on_shutdown(self):
        """``_dispatch_to_all`` stops waking websockets when the server shuts
        down mid-catch-up."""
        d = self._make_dispatch()
        websockets = [self._make_ws() for _ in range(5)]
        d._channels_to_ws = {
            ("testdb", f"ch{i}"): {ws} for i, ws in enumerate(websockets)
        }
        mock_stop = MagicMock()
        mock_stop.wait.return_value = True  # stop_event set during the pause
        with (
            patch.object(bus_module, "DISPATCH_CATCHUP_CHUNK_SIZE", 2),
            patch.object(bus_module, "stop_event", mock_stop),
        ):
            d._dispatch_to_all()
        triggered = sum(
            ws.trigger_notification_dispatching.call_count for ws in websockets
        )
        self.assertEqual(triggered, 2, "only the first chunk should have been woken")


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
class TestSendPgNotify(BaseCase):
    """Tests for ``_send_pg_notify()`` error handling."""

    def _run_with_conn(self, mock_conn, payloads):
        with (
            patch.object(bus_module, "_get_notify_conn_locked", return_value=mock_conn),
            patch.object(bus_module, "_close_notify_conn_locked") as mock_close,
        ):
            _send_pg_notify(payloads)
        return mock_close

    def test_retry_on_connection_failure(self):
        """A connection-level failure closes the connection and retries; the
        second attempt succeeds."""
        call_count = 0

        def mock_execute(query, params):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise psycopg.OperationalError("transient connection drop")

        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_conn.execute = mock_execute

        mock_close = self._run_with_conn(mock_conn, ["payload1"])
        # Connection was closed on first failure
        mock_close.assert_called_once()
        # Second attempt succeeded
        self.assertEqual(call_count, 2)

    def test_retry_resumes_at_failed_payload(self):
        """On retry, already-sent payloads are not replayed: delivery resumes
        at the payload that failed."""
        executed = []
        failed = False

        def mock_execute(query, params):
            nonlocal failed
            if params[0] == "payload2" and not failed:
                failed = True
                raise psycopg.OperationalError("transient connection drop")
            executed.append(params[0])

        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_conn.execute = mock_execute

        self._run_with_conn(mock_conn, ["payload1", "payload2", "payload3"])
        self.assertEqual(executed, ["payload1", "payload2", "payload3"])

    def test_raises_on_second_connection_failure(self):
        """If both attempts fail at the connection level, the exception
        propagates (the postcommit ``notify()`` wrapper catches it)."""
        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_conn.execute.side_effect = psycopg.OperationalError("persistent error")

        with (
            patch.object(bus_module, "_get_notify_conn_locked", return_value=mock_conn),
            patch.object(bus_module, "_close_notify_conn_locked"),
        ):
            with self.assertRaisesRegex(psycopg.OperationalError, "persistent error"):
                _send_pg_notify(["payload1"])
        # Both attempts were made before giving up.
        self.assertEqual(mock_conn.execute.call_count, 2)

    def test_poison_payload_skipped_others_sent(self):
        """A payload PostgreSQL rejects is warned about and skipped; the
        remaining payloads are still delivered and nothing is raised."""
        executed = []

        def mock_execute(query, params):
            if params[0] == "poison":
                raise psycopg.ProgrammingError("payload string too long")
            executed.append(params[0])

        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_conn.execute = mock_execute

        with self.assertLogs("odoo.addons.bus.models.bus", "WARNING"):
            mock_close = self._run_with_conn(
                mock_conn, ["payload1", "poison", "payload3"]
            )
        self.assertEqual(executed, ["payload1", "payload3"])
        # The connection is fine; it must not have been cycled.
        mock_close.assert_not_called()

    def test_error_with_dead_connection_is_retried(self):
        """A non-connection exception that leaves the connection closed is
        treated as connection-level: cycle the connection and retry the same
        payload instead of dropping it."""
        executed = []
        failed = False

        def mock_execute(query, params):
            nonlocal failed
            if not failed:
                failed = True
                mock_conn.closed = True
                raise psycopg.ProgrammingError("error that killed the connection")
            executed.append(params[0])

        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_conn.execute = mock_execute

        def close_side_effect():
            mock_conn.closed = False  # simulate reconnect on next get

        with (
            patch.object(bus_module, "_get_notify_conn_locked", return_value=mock_conn),
            patch.object(
                bus_module,
                "_close_notify_conn_locked",
                side_effect=close_side_effect,
            ),
        ):
            _send_pg_notify(["payload1"])
        self.assertEqual(executed, ["payload1"])


@tagged("-at_install", "post_install")
class TestNotifyForkSafety(BaseCase):
    """Tests for ``_reset_notify_state_in_child`` (fork safety of the
    persistent notify connection)."""

    def test_reset_drops_connection_without_closing(self):
        old_conn = bus_module._notify_conn
        old_lock = bus_module._notify_lock
        mock_conn = MagicMock()
        bus_module._notify_conn = mock_conn
        try:
            bus_module._reset_notify_state_in_child()
            # The inherited connection is dropped, NOT closed: close() would
            # send a libpq Terminate on the socket shared with the parent.
            self.assertIsNone(bus_module._notify_conn)
            mock_conn.close.assert_not_called()
            # ... and parked so it can never be garbage collected.
            self.assertIn(mock_conn, bus_module._notify_conns_inherited_from_parent)
        finally:
            bus_module._notify_conns_inherited_from_parent.remove(mock_conn)
            bus_module._notify_conn = old_conn
            bus_module._notify_lock = old_lock

    def test_reset_recreates_potentially_held_lock(self):
        """The lock may be held by a parent thread at fork time; the child
        must get a fresh, unlocked one."""
        old_conn = bus_module._notify_conn
        old_lock = bus_module._notify_lock
        try:
            bus_module._notify_conn = None
            bus_module._notify_lock.acquire()  # simulate lock held at fork
            bus_module._reset_notify_state_in_child()
            self.assertIsNot(bus_module._notify_lock, old_lock)
            self.assertTrue(
                bus_module._notify_lock.acquire(blocking=False),
                "the recreated lock must be unlocked",
            )
            bus_module._notify_lock.release()
        finally:
            old_lock.release()
            bus_module._notify_conn = old_conn
            bus_module._notify_lock = old_lock


@tagged("-at_install", "post_install")
class TestNotifyPostcommit(TransactionCase):
    """The postcommit ``notify()`` hook must never propagate an exception:
    the transaction is already committed and ``Callbacks.run()`` would skip
    every remaining postcommit hook."""

    def test_postcommit_notify_never_raises(self):
        Bus = self.env["bus.bus"]
        Bus._sendone("resilience_channel", "test_type", {})
        self.env.cr.precommit.run()
        with patch.object(
            bus_module, "_send_pg_notify", side_effect=Exception("NOTIFY down")
        ):
            with self.assertLogs("odoo.addons.bus.models.bus", "ERROR") as logs:
                self.env.cr.postcommit.run()  # must not raise
        self.assertTrue(any("imbus NOTIFY" in line for line in logs.output))

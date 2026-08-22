import time
from unittest.mock import MagicMock, patch

from odoo.tests import BaseCase, TransactionCase, tagged

from ..models.bus import (
    MAX_NOTIFICATION_BYTES_PER_POLL,
    MAX_NOTIFICATIONS_PER_POLL,
    NOTIFICATION_HOLD_BACK_SECONDS,
    channel_with_db,
    json_dump,
)
from ..websocket import ConnectionState, NotificationDispatchState, Websocket


@tagged("-at_install", "post_install")
class TestPollBounds(TransactionCase):
    CHANNEL = "test_poll_bounds"

    def _seed(self, count, body_size=32):
        channel = json_dump(channel_with_db(self.env.cr.dbname, self.CHANNEL))
        message = json_dump({"type": "probe", "payload": {"body": "x" * body_size}})
        self.env.cr.execute(
            """
            INSERT INTO bus_bus (channel, message, create_date)
            SELECT %s, %s, (now() at time zone 'utc') FROM generate_series(1, %s)
            RETURNING id
            """,
            (channel, message, count),
        )
        return sorted(row[0] for row in self.env.cr.fetchall())

    def test_poll_is_capped_by_count(self):
        ids = self._seed(MAX_NOTIFICATIONS_PER_POLL + 25)
        notifications = self.env["bus.bus"]._poll([self.CHANNEL], last=ids[0] - 1)
        self.assertEqual(len(notifications), MAX_NOTIFICATIONS_PER_POLL)
        self.assertEqual(
            [n["id"] for n in notifications], ids[:MAX_NOTIFICATIONS_PER_POLL]
        )

    def test_poll_batch_reports_truncation(self):
        ids = self._seed(30)
        _notifications, truncated = self.env["bus.bus"]._poll_batch(
            [self.CHANNEL], last=ids[0] - 1, limit=10
        )
        self.assertTrue(truncated)
        notifications, truncated = self.env["bus.bus"]._poll_batch(
            [self.CHANNEL], last=ids[0] - 1, limit=30
        )
        self.assertEqual(len(notifications), 30)
        self.assertFalse(
            truncated, "a batch that consumed every match is not truncated"
        )

    def test_poll_is_capped_by_payload_bytes(self):
        body = 8 * 1024
        expected_max = MAX_NOTIFICATION_BYTES_PER_POLL // body + 1
        ids = self._seed(MAX_NOTIFICATIONS_PER_POLL - 1, body_size=body)
        notifications, truncated = self.env["bus.bus"]._poll_batch(
            [self.CHANNEL], last=ids[0] - 1
        )
        self.assertTrue(truncated)
        self.assertLess(
            len(notifications),
            MAX_NOTIFICATIONS_PER_POLL,
            "the count cap was not what stopped this batch",
        )
        self.assertLessEqual(len(notifications), expected_max)

    def test_a_single_oversized_notification_is_still_returned(self):
        ids = self._seed(2, body_size=MAX_NOTIFICATION_BYTES_PER_POLL + 1000)
        notifications, truncated = self.env["bus.bus"]._poll_batch(
            [self.CHANNEL], last=ids[0] - 1
        )
        self.assertEqual([n["id"] for n in notifications], ids[:1])
        self.assertTrue(truncated, "the second notification is still waiting")

    def test_backlog_drains_completely_across_batches(self):
        ids = self._seed(1000)
        state = NotificationDispatchState(NOTIFICATION_HOLD_BACK_SECONDS)
        state.initialize_last_id(ids[0] - 1)
        delivered, rounds = [], 0
        while True:
            rounds += 1
            self.assertLess(rounds, 200, "draining the backlog did not terminate")
            notifications, truncated = self.env["bus.bus"]._poll_batch(
                [self.CHANNEL], state.last_id, state.ignore_ids, limit=50
            )
            if not notifications:
                break
            state.record_dispatched([n["id"] for n in notifications])
            delivered.extend(n["id"] for n in notifications)
            if not truncated:
                break
        self.assertEqual(delivered, ids, "backlog must arrive exactly once, in order")
        self.assertGreater(
            rounds, 1, "this backlog was supposed to need several rounds"
        )

    def test_drain_is_lossless_past_the_dispatch_history_cap(self):
        count = NotificationDispatchState.MAX_HISTORY_LENGTH + 1000
        ids = self._seed(count)
        state = NotificationDispatchState(NOTIFICATION_HOLD_BACK_SECONDS)
        state.initialize_last_id(ids[0] - 1)
        delivered, rounds = [], 0
        while True:
            rounds += 1
            self.assertLess(rounds, 500, "draining the backlog did not terminate")
            notifications, truncated = self.env["bus.bus"]._poll_batch(
                [self.CHANNEL], state.last_id, state.ignore_ids
            )
            if not notifications:
                break
            state.record_dispatched([n["id"] for n in notifications])
            delivered.extend(n["id"] for n in notifications)
            if not truncated:
                break
        self.assertEqual(delivered, ids, "the history cap must not eat a notification")
        self.assertGreater(
            state.last_id,
            0,
            "this backlog was supposed to push last_id past the history cap",
        )


@tagged("-at_install", "post_install")
class TestDispatchRearm(BaseCase):
    def _make_ws(self, notifications, truncated):
        ws = Websocket.__new__(Websocket)
        ws._clock = time.monotonic
        ws.state = ConnectionState.OPEN
        ws._db = "somedb"
        ws._channels = {("somedb", "chan")}
        ws._waiting_for_dispatch = False
        ws._dispatch_state = NotificationDispatchState(NOTIFICATION_HOLD_BACK_SECONDS)
        session = MagicMock()
        session.db = "somedb"
        session.sid = "sid"
        session.uid = None
        ws._session = session
        ws._session_validated_until = float("inf")
        ws._validated_session_sid = "sid"
        env = MagicMock()
        env.__getitem__.return_value._poll_batch.return_value = (
            notifications,
            truncated,
        )
        self._env = env
        return ws

    def _dispatch(self, ws):
        cursor = MagicMock()
        cursor.__enter__.return_value = MagicMock()
        with (
            patch("odoo.addons.bus.websocket.acquire_cursor", return_value=cursor),
            patch.object(Websocket, "new_env", return_value=self._env),
            patch.object(Websocket, "_send") as send,
            patch.object(Websocket, "trigger_notification_dispatching") as rearm,
        ):
            ws._dispatch_bus_notifications()
        return send, rearm

    def test_truncated_batch_rearms(self):
        ws = self._make_ws([{"id": 1, "message": {}}], truncated=True)
        send, rearm = self._dispatch(ws)
        send.assert_called_once()
        rearm.assert_called_once_with()

    def test_complete_batch_does_not_rearm(self):
        ws = self._make_ws([{"id": 1, "message": {}}], truncated=False)
        send, rearm = self._dispatch(ws)
        send.assert_called_once()
        rearm.assert_not_called()

    def test_empty_batch_neither_sends_nor_rearms(self):
        ws = self._make_ws([], truncated=False)
        send, rearm = self._dispatch(ws)
        send.assert_not_called()
        rearm.assert_not_called()

"""``_poll`` must never return an unbounded batch.

An unbounded ``id > last`` returned the whole retained backlog of a channel in
one frame. That frame could not be written inside ``FRAME_RECEIVE_TIMEOUT``,
which bounds the *whole* ``sendall``, so a slow client was dropped with
ABNORMAL_CLOSURE having received nothing and reconnected onto the identical
backlog -- with nothing logged. These tests pin the bounds and, more importantly,
pin that bounding them loses nothing: a backlog must still drain completely.
"""

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
        """Insert ``count`` notifications on ``self.CHANNEL`` and return their ids."""
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
        """More matching rows than the cap yields exactly the cap, in id order."""
        ids = self._seed(MAX_NOTIFICATIONS_PER_POLL + 25)
        notifications = self.env["bus.bus"]._poll([self.CHANNEL], last=ids[0] - 1)
        self.assertEqual(len(notifications), MAX_NOTIFICATIONS_PER_POLL)
        self.assertEqual(
            [n["id"] for n in notifications], ids[:MAX_NOTIFICATIONS_PER_POLL]
        )

    def test_poll_batch_reports_truncation(self):
        """``truncated`` distinguishes "there is more" from "that was all"."""
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
        """Few but huge messages are cut by the byte budget, not the count."""
        # ~8 KiB of body each: the byte budget bites long before the count does.
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
        """One message bigger than the whole byte budget must not yield nothing.

        The budget is checked *after* appending, so a batch is never empty. If it
        were checked first, such a notification would return an empty batch,
        ``_dispatch_bus_notifications`` would return early without advancing the
        watermark, and the re-arm would spin on it forever.
        """
        ids = self._seed(2, body_size=MAX_NOTIFICATION_BYTES_PER_POLL + 1000)
        notifications, truncated = self.env["bus.bus"]._poll_batch(
            [self.CHANNEL], last=ids[0] - 1
        )
        self.assertEqual([n["id"] for n in notifications], ids[:1])
        self.assertTrue(truncated, "the second notification is still waiting")

    def test_backlog_drains_completely_across_batches(self):
        """The whole point: bounding the batch must not lose a notification.

        Replays what ``_dispatch_bus_notifications`` does -- poll, record, poll
        again from the same state -- and asserts the backlog comes out exactly
        once each, in order, and that the loop terminates.
        """
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
        """A backlog long enough to overflow ``MAX_HISTORY_LENGTH`` still drains.

        Bounding the batch means a large backlog now routinely reaches the
        history cap (``MAX_NOTIFICATIONS_PER_POLL`` ids per round, so the cap is
        crossed after ten of them), where ``record_dispatched`` advances
        ``last_id`` past ids it drops. That is safe for a *backlog* -- every row
        is already committed, so there is no late commit to skip -- but it is
        the interaction most likely to silently lose rows, so pin it.
        """
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
    """A truncated batch must re-arm, or the remainder is never sent."""

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
        # Skip re-validation: this test is about the batching, not the session
        # TTL, which ``test_websocket_caryall`` already covers.
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
        """No spurious extra poll on the common single-notification path."""
        ws = self._make_ws([{"id": 1, "message": {}}], truncated=False)
        send, rearm = self._dispatch(ws)
        send.assert_called_once()
        rearm.assert_not_called()

    def test_empty_batch_neither_sends_nor_rearms(self):
        ws = self._make_ws([], truncated=False)
        send, rearm = self._dispatch(ws)
        send.assert_not_called()
        rearm.assert_not_called()

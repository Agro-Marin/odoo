from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


@tagged("-at_install", "post_install")
class TestBusSend(TransactionCase):
    """Tests for ``BusListenerMixin._bus_send()`` and channel resolution."""

    def test_send_single_record(self):
        """Sending on a single partner record creates one bus notification."""
        partner = self.env.user.partner_id
        with patch.object(type(self.env["bus.bus"]), "_sendone") as mock_sendone:
            partner._bus_send("test_notif", {"key": "value"})
            mock_sendone.assert_called_once()
            _target, notif_type, message = mock_sendone.call_args[0]
            self.assertEqual(notif_type, "test_notif")
            self.assertEqual(message, {"key": "value"})

    def test_send_multiple_records(self):
        """Sending on a multi-record set dispatches one notification per record."""
        partners = self.env["res.partner"].create(
            [{"name": f"bus multi {i}"} for i in range(3)]
        )
        with patch.object(type(self.env["bus.bus"]), "_sendone") as mock_sendone:
            partners._bus_send("multi_notif", {})
            self.assertEqual(mock_sendone.call_count, len(partners))

    def test_send_empty_recordset_is_noop(self):
        """Calling _bus_send on an empty recordset does nothing."""
        empty = self.env["res.partner"].browse()
        with patch.object(type(self.env["bus.bus"]), "_sendone") as mock_sendone:
            empty._bus_send("noop", {})
            mock_sendone.assert_not_called()

    def test_send_with_subchannel(self):
        """The subchannel parameter wraps the target in a tuple."""
        partner = self.env.user.partner_id
        with patch.object(type(self.env["bus.bus"]), "_sendone") as mock_sendone:
            partner._bus_send("typed", {"data": 1}, subchannel="sub")
            mock_sendone.assert_called_once()
            target = mock_sendone.call_args[0][0]
            # Target should be (record, subchannel)
            self.assertIsInstance(target, tuple)
            self.assertEqual(len(target), 2)
            self.assertEqual(target[1], "sub")

    def test_channel_chain_resolution_user_to_partner(self):
        """res.users._bus_channel() delegates to partner_id; _bus_send follows."""
        user = self.env.user
        with patch.object(type(self.env["bus.bus"]), "_sendone") as mock_sendone:
            user._bus_send("user_notif", {})
            mock_sendone.assert_called_once()
            target = mock_sendone.call_args[0][0]
            # The target should be the partner, not the user
            self.assertEqual(target._name, "res.partner")
            self.assertEqual(target.id, user.partner_id.id)

    def test_channel_chain_cycle_detection(self):
        """A cycle in _bus_channel() overrides raises RecursionError."""
        # Own test data: independent of pre-existing partner count/order.
        partner_a, partner_b = self.env["res.partner"].create(
            [{"name": "bus cycle a"}, {"name": "bus cycle b"}]
        )

        def cyclic_bus_channel(self_rec):
            # Alternate between two records so the equality check never
            # terminates the hop loop.
            return partner_b if self_rec == partner_a else partner_a

        with patch.object(type(partner_a), "_bus_channel", cyclic_bus_channel):
            with self.assertRaises(RecursionError):
                partner_a._bus_send("cycle_test", {})

    def test_empty_channel_record_skipped(self):
        """If _bus_channel() resolves to an empty recordset, the record is skipped."""
        partner = self.env.user.partner_id
        with (
            patch.object(type(partner), "_bus_channel", lambda self: self.browse()),
            patch.object(type(self.env["bus.bus"]), "_sendone") as mock_sendone,
        ):
            partner._bus_send("skip_test", {})
            mock_sendone.assert_not_called()


@tagged("-at_install", "post_install")
class TestBusPoll(TransactionCase):
    """Tests for ``bus.bus._poll()``."""

    def test_poll_returns_notifications_after_last(self):
        """Polling with a valid last id returns only newer notifications."""
        Bus = self.env["bus.bus"]
        Bus.search([]).unlink()
        Bus._sendone("test_channel", "type_a", {"seq": 1})
        Bus._sendone("test_channel", "type_b", {"seq": 2})
        self.env.cr.precommit.run()
        last_id = Bus._bus_last_id()
        Bus._sendone("test_channel", "type_c", {"seq": 3})
        self.env.cr.precommit.run()
        notifications = Bus._poll(["test_channel"], last=last_id)
        self.assertEqual(len(notifications), 1)
        self.assertEqual(notifications[0]["message"]["type"], "type_c")

    def test_poll_with_zero_last_uses_time_window(self):
        """Polling with last=0 returns recent notifications (within TIMEOUT window)."""
        Bus = self.env["bus.bus"]
        Bus.search([]).unlink()
        Bus._sendone("fresh_channel", "recent", {"data": True})
        self.env.cr.precommit.run()
        notifications = Bus._poll(["fresh_channel"], last=0)
        self.assertGreaterEqual(len(notifications), 1)

    def test_poll_ignores_other_channels(self):
        """Notifications on other channels are not returned."""
        Bus = self.env["bus.bus"]
        Bus.search([]).unlink()
        Bus._sendone("channel_a", "a_notif", {})
        Bus._sendone("channel_b", "b_notif", {})
        self.env.cr.precommit.run()
        notifications = Bus._poll(["channel_a"], last=0)
        types = [n["message"]["type"] for n in notifications]
        self.assertIn("a_notif", types)
        self.assertNotIn("b_notif", types)

    def test_bus_last_id_empty_table(self):
        """_bus_last_id returns 0 when the table is empty."""
        self.env["bus.bus"].search([]).unlink()
        self.assertEqual(self.env["bus.bus"]._bus_last_id(), 0)


@tagged("-at_install", "post_install")
class TestEnsureHooks(TransactionCase):
    """Tests for ``BusBus._ensure_hooks()`` precommit/postcommit registration."""

    def test_hooks_register_once_per_transaction(self):
        """Multiple _sendone calls in the same transaction register hooks only once."""
        Bus = self.env["bus.bus"]
        Bus.search([]).unlink()
        # Send multiple notifications in the same transaction
        Bus._sendone("ch1", "type_a", {"seq": 1})
        Bus._sendone("ch2", "type_b", {"seq": 2})
        Bus._sendone("ch1", "type_c", {"seq": 3})
        # Before precommit: nothing in the DB yet
        self.assertEqual(Bus.search_count([]), 0)
        # After precommit: all three created in a single batch
        self.env.cr.precommit.run()
        self.assertEqual(Bus.search_count([]), 3)

    def test_postcommit_deduplicates_channels(self):
        """Same channel sent multiple times produces one NOTIFY channel entry."""
        Bus = self.env["bus.bus"]
        Bus._sendone("same_channel", "type_a", {})
        Bus._sendone("same_channel", "type_b", {})
        Bus._sendone("other_channel", "type_c", {})
        self.env.cr.precommit.run()
        # The postcommit data should have deduplicated "same_channel"
        channels = list(self.env.cr.postcommit.data.get("bus.bus.channels", []))
        # Count distinct dbname-qualified channel tuples
        same_channel_entries = [
            c for c in channels if isinstance(c, tuple) and c[-1] == "same_channel"
        ]
        self.assertEqual(
            len(same_channel_entries),
            1,
            "OrderedSet should deduplicate identical channels",
        )

    def test_precommit_creates_records_then_clears(self):
        """After precommit runs, the hook data is consumed and won't re-fire."""
        Bus = self.env["bus.bus"]
        Bus.search([]).unlink()
        Bus._sendone("ch", "t", {})
        self.env.cr.precommit.run()
        count_after_first = Bus.search_count([])
        # Running precommit again should not create duplicates
        self.env.cr.precommit.run()
        self.assertEqual(Bus.search_count([]), count_after_first)

    def test_notify_payload_sent_on_postcommit(self):
        """Postcommit triggers _send_pg_notify with the accumulated channels."""
        Bus = self.env["bus.bus"]
        Bus._sendone("notify_test", "t", {})
        self.env.cr.precommit.run()
        with patch("odoo.addons.bus.models.bus._send_pg_notify") as mock_notify:
            self.env.cr.postcommit.run()
            mock_notify.assert_called_once()
            payloads = mock_notify.call_args[0][0]
            self.assertIsInstance(payloads, list)
            self.assertGreater(len(payloads), 0)

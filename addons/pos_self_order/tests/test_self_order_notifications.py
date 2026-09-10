from odoo import fields
from odoo.tests import tagged

from odoo.addons.point_of_sale.tests.common import CommonPosTest


@tagged("post_install", "-at_install")
class TestSelfOrderNotifications(CommonPosTest):
    """point_of_sale owns SYNCHRONISATION for the transitions it performs;
    pos_self_order's override must add its own message, not repeat that one."""

    def setUp(self):
        super().setUp()
        self.config = self.pos_config_usd
        self.config.open_ui()
        self.session = self.config.current_session_id

    def _order_values(self):
        return [
            {
                "session_id": self.session.id,
                "config_id": self.config.id,
                "user_id": self.env.uid,
                "state": "draft",
                "amount_total": 0,
                "amount_tax": 0,
                "amount_paid": 0,
                "amount_return": 0,
                "lines": [],
                "payment_ids": [],
                "date_order": fields.Datetime.to_string(fields.Datetime.now()),
            }
        ]

    def _messages_of(self, kind, run):
        bus = self.env.cr.precommit.data
        before = len(bus.get("bus.bus.values", []))
        result = run()
        sent = bus.get("bus.bus.values", [])[before:]
        return result, [m for m in sent if kind in m["message"]]

    def test_one_sync_from_ui_sends_one_synchronisation(self):
        _result, messages = self._messages_of(
            "SYNCHRONISATION",
            lambda: self.env["pos.order"].sync_from_ui(self._order_values()),
        )
        self.assertEqual(len(messages), 1)

    def test_sync_from_ui_also_announces_the_order_state(self):
        _result, messages = self._messages_of(
            "ORDER_STATE_CHANGED",
            lambda: self.env["pos.order"].sync_from_ui(self._order_values()),
        )
        self.assertEqual(len(messages), 1)

    def test_removing_an_order_from_the_ui_deletes_it(self):
        result = self.env["pos.order"].sync_from_ui(self._order_values())
        order_id = result["pos.order"][0]["id"]
        self.env["pos.order"].remove_from_ui([order_id])
        self.assertFalse(
            self.env["pos.order"].browse(order_id).exists(),
            "remove_from_ui must remove the order, not merely cancel it",
        )

    def test_removing_a_self_order_keeps_it_cancelled(self):
        values = self._order_values()
        values[0]["source"] = "mobile"
        result = self.env["pos.order"].sync_from_ui(values)
        order = self.env["pos.order"].browse(result["pos.order"][0]["id"])
        _result, messages = self._messages_of(
            "SYNCHRONISATION",
            lambda: self.env["pos.order"].remove_from_ui([order.id]),
        )
        self.assertTrue(
            order.exists(),
            "an order the customer placed stays in their history",
        )
        self.assertEqual(order.state, "cancel")
        self.assertEqual(len(messages), 1)

    def test_removing_an_order_from_the_ui_sends_one_synchronisation(self):
        result = self.env["pos.order"].sync_from_ui(self._order_values())
        order_id = result["pos.order"][0]["id"]
        _result, messages = self._messages_of(
            "SYNCHRONISATION",
            lambda: self.env["pos.order"].remove_from_ui([order_id]),
        )
        self.assertEqual(
            len(messages),
            1,
            "the other devices have to learn the order is gone",
        )

    def test_cancelling_an_order_sends_one_synchronisation(self):
        result = self.env["pos.order"].sync_from_ui(self._order_values())
        order = self.env["pos.order"].browse(result["pos.order"][0]["id"])
        _result, messages = self._messages_of(
            "SYNCHRONISATION", order.action_pos_order_cancel
        )
        self.assertEqual(len(messages), 1)

import json
from datetime import datetime, timedelta

from freezegun import freeze_time

try:
    import websocket as ws
except ImportError:
    ws = None

from odoo.tests import new_test_user, tagged

from odoo.addons.bus.models.bus import channel_with_db, json_dump
from odoo.addons.bus.tests.common import WebsocketCase
from odoo.addons.mail.models.mail_presence import AWAY_TIMER


@tagged("-at_install", "post_install")
class TestIrWebsocket(WebsocketCase):
    def test_notify_on_status_change(self):
        bob = new_test_user(self.env, login="bob_user", groups="base.group_user")
        session = self.authenticate("bob_user", "bob_user")
        websocket = self.websocket_connect(cookie=f"session_id={session.sid};")
        self.subscribe(
            websocket,
            [f"odoo-presence-res.partner_{bob.partner_id.id}"],
            self.env["bus.bus"]._bus_last_id(),
        )
        self.env["mail.presence"]._update_presence(bob)
        self.trigger_notification_dispatching([(bob.partner_id, "presence")])
        message = json.loads(websocket.recv())[0]["message"]
        self.assertEqual(message["type"], "bus.bus/im_status_updated")
        self.assertEqual(message["payload"]["im_status"], "online")
        self.assertEqual(message["payload"]["presence_status"], "online")
        self.assertEqual(message["payload"]["partner_id"], bob.partner_id.id)
        away_timer_later = datetime.now() + timedelta(seconds=AWAY_TIMER + 1)
        with freeze_time(away_timer_later):
            self.env["mail.presence"]._update_presence(bob, (AWAY_TIMER + 1) * 1000)
            self.trigger_notification_dispatching([(bob.partner_id, "presence")])
            message = json.loads(websocket.recv())[0]["message"]
            self.assertEqual(message["type"], "bus.bus/im_status_updated")
            self.assertEqual(message["payload"]["im_status"], "away")
            self.assertEqual(message["payload"]["presence_status"], "away")
            self.assertEqual(message["payload"]["partner_id"], bob.partner_id.id)
        ten_minutes_later = datetime.now() + timedelta(minutes=10)
        with freeze_time(ten_minutes_later):
            self.env["mail.presence"]._update_presence(bob)
            self.trigger_notification_dispatching([(bob.partner_id, "presence")])
            message = json.loads(websocket.recv())[0]["message"]
            self.assertEqual(message["type"], "bus.bus/im_status_updated")
            self.assertEqual(message["payload"]["im_status"], "online")
            self.assertEqual(message["payload"]["presence_status"], "online")
            self.assertEqual(message["payload"]["partner_id"], bob.partner_id.id)
        ten_minutes_later = datetime.now() + timedelta(minutes=10)
        with freeze_time(ten_minutes_later):
            self.env["mail.presence"]._update_presence(bob)
            self.trigger_notification_dispatching([(bob.partner_id, "presence")])
            timeout_occurred = False
            websocket.settimeout(1)
            try:
                websocket.recv()
            except ws._exceptions.WebSocketTimeoutException:
                timeout_occurred = True
            self.assertTrue(timeout_occurred)

    def test_receive_missed_presences_on_subscribe(self):
        bob = new_test_user(self.env, login="bob_user", groups="base.group_user")
        session = self.authenticate("bob_user", "bob_user")
        websocket = self.websocket_connect(cookie=f"session_id={session.sid};")
        self.env["mail.presence"]._update_presence(bob)
        self.env.cr.precommit.run()
        self.subscribe(
            websocket,
            [f"odoo-presence-res.partner_{bob.partner_id.id}"],
            self.env["bus.bus"]._bus_last_id(),
        )
        self.trigger_notification_dispatching([(bob.partner_id, "presence")])
        notification = json.loads(websocket.recv())[0]
        self._close_websockets()
        bus_record = self.env["bus.bus"].search([("id", "=", int(notification["id"]))])
        self.assertEqual(
            bus_record.channel,
            json_dump(channel_with_db(self.env.cr.dbname, bob.partner_id)),
        )
        self.assertEqual(notification["message"]["type"], "bus.bus/im_status_updated")
        self.assertEqual(notification["message"]["payload"]["im_status"], "online")
        self.assertEqual(
            notification["message"]["payload"]["presence_status"], "online"
        )
        self.assertEqual(
            notification["message"]["payload"]["partner_id"], bob.partner_id.id
        )

    def test_receive_others_missed_presences_on_subscribe(self):
        bob = new_test_user(self.env, login="bob_user", groups="base.group_user")
        away_user = new_test_user(self.env, login="idler", groups="base.group_user")
        session = self.authenticate("bob_user", "bob_user")
        websocket = self.websocket_connect(cookie=f"session_id={session.sid};")
        self.env["mail.presence"]._update_presence(away_user, (AWAY_TIMER + 1) * 1000)
        self.env.cr.precommit.run()
        self.subscribe(
            websocket,
            [f"odoo-presence-res.partner_{away_user.partner_id.id}"],
            self.env["bus.bus"]._bus_last_id(),
        )
        self.trigger_notification_dispatching([(away_user.partner_id, "presence")])
        notification = json.loads(websocket.recv())[0]
        self._close_websockets()
        bus_record = self.env["bus.bus"].search([("id", "=", int(notification["id"]))])
        self.assertEqual(
            bus_record.channel,
            json_dump(channel_with_db(self.env.cr.dbname, bob.partner_id)),
        )
        self.assertEqual(notification["message"]["type"], "bus.bus/im_status_updated")
        self.assertEqual(notification["message"]["payload"]["im_status"], "away")
        self.assertEqual(notification["message"]["payload"]["presence_status"], "away")
        self.assertEqual(
            notification["message"]["payload"]["partner_id"], away_user.partner_id.id
        )

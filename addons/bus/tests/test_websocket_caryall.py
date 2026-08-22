import gc
import json
import os
from collections import defaultdict
from datetime import timedelta
from threading import Event
from unittest.mock import patch
from weakref import WeakSet

from freezegun import freeze_time

from odoo import http
from odoo.api import Environment
from odoo.service.security import check_session
from odoo.tests import common, new_test_user
from odoo.tools import mute_logger

from .. import websocket as websocket_module
from ..models.bus import dispatch
from ..models.ir_websocket import IrWebsocket
from ..websocket import (
    CloseCode,
    Frame,
    Opcode,
    TimeoutManager,
    Websocket,
    WebsocketConnectionHandler,
)
from .common import WebsocketCase


class ManualClock:
    def __init__(self, now=0.0):
        self.now = now

    def __call__(self):
        return self.now

    def tick(self, seconds):
        self.now += seconds


@common.tagged("post_install", "-at_install")
class TestWebsocketCaryall(WebsocketCase):
    def test_lifecycle_hooks(self):
        events = []
        with patch.object(Websocket, "_Websocket__event_callbacks", defaultdict(set)):

            @Websocket.onopen
            def onopen(env, websocket):  # pylint: disable=unused-variable
                self.assertIsInstance(env, Environment)
                self.assertIsInstance(websocket, Websocket)
                events.append("open")

            @Websocket.onclose
            def onclose(env, websocket):  # pylint: disable=unused-variable
                self.assertIsInstance(env, Environment)
                self.assertIsInstance(websocket, Websocket)
                events.append("close")

            ws = self.websocket_connect()
            ws.close(CloseCode.CLEAN)
            self.wait_remaining_websocket_connections()
            self.assertEqual(events, ["open", "close"])

    def test_on_websocket_closed_runs_through_retrying(self):
        seen = []
        original_retrying = websocket_module.retrying

        def _spy(func, env):
            seen.append(getattr(func, "func", func).__name__)
            return original_retrying(func, env)

        with patch.object(websocket_module, "retrying", _spy):
            ws = self.websocket_connect()
            ws.close(CloseCode.CLEAN)
            self.wait_remaining_websocket_connections()
        self.assertIn("_on_websocket_closed", seen)

    def test_instances_weak_set(self):
        with patch.object(websocket_module, "_websocket_instances", WeakSet()):
            first_ws = self.websocket_connect()
            second_ws = self.websocket_connect()
            self.assertEqual(len(websocket_module._websocket_instances), 2)
            first_ws.close(CloseCode.CLEAN)
            second_ws.close(CloseCode.CLEAN)
            self.wait_remaining_websocket_connections()
            self._serve_forever_patch.stop()
            gc.collect()
            self.assertEqual(len(websocket_module._websocket_instances), 0)

    def test_timeout_manager_no_response_timeout(self):
        clock = ManualClock()
        timeout_manager = TimeoutManager(clock=clock)
        timeout_manager.acknowledge_frame_sent(Frame(Opcode.PING))
        clock.tick(TimeoutManager.TIMEOUT / 2)
        self.assertFalse(timeout_manager.has_frame_response_timed_out())
        clock.tick(TimeoutManager.TIMEOUT / 2)
        self.assertTrue(timeout_manager.has_frame_response_timed_out())

        clock = ManualClock()
        timeout_manager = TimeoutManager(clock=clock)
        timeout_manager.acknowledge_frame_sent(Frame(Opcode.CLOSE))
        clock.tick(TimeoutManager.TIMEOUT / 2)
        self.assertFalse(timeout_manager.has_frame_response_timed_out())
        clock.tick(TimeoutManager.TIMEOUT / 2)
        self.assertTrue(timeout_manager.has_frame_response_timed_out())

    def test_timeout_manager_overlapping_timeouts(self):
        clock = ManualClock()
        timeout_manager = TimeoutManager(clock=clock)
        timeout_manager.acknowledge_frame_sent(Frame(Opcode.CLOSE))
        timeout_manager.acknowledge_frame_sent(Frame(Opcode.PING))
        timeout_manager.acknowledge_frame_receipt(Frame(Opcode.PONG))
        clock.tick(timeout_manager.TIMEOUT + 1)
        self.assertTrue(timeout_manager.has_frame_response_timed_out())

    def test_timeout_manager_keep_alive_timeout(self):
        clock = ManualClock()
        timeout_manager = TimeoutManager(clock=clock)
        clock.tick(timeout_manager._keep_alive_timeout / 2)
        self.assertFalse(timeout_manager.has_keep_alive_timed_out())
        clock.tick(timeout_manager._keep_alive_timeout / 2 + 1)
        self.assertTrue(timeout_manager.has_keep_alive_timed_out())

    def test_timeout_manager_reset_wait_for(self):
        clock = ManualClock()
        timeout_manager = TimeoutManager(clock=clock)
        timeout_manager.acknowledge_frame_sent(Frame(Opcode.PING))
        timeout_manager.acknowledge_frame_receipt(Frame(Opcode.PONG))
        clock.tick(timeout_manager.TIMEOUT + 1)
        self.assertFalse(timeout_manager.has_frame_response_timed_out())

        timeout_manager.acknowledge_frame_sent(Frame(Opcode.CLOSE))
        timeout_manager.acknowledge_frame_receipt(Frame(Opcode.CLOSE))
        clock.tick(timeout_manager.TIMEOUT + 1)
        self.assertFalse(timeout_manager.has_frame_response_timed_out())

    def test_user_login(self):
        websocket = self.websocket_connect()
        new_test_user(self.env, login="test_user", password="Password!1")
        self.authenticate("test_user", "Password!1")
        self.subscribe(websocket, wait_for_dispatch=False)
        self.assert_close_with_code(websocket, CloseCode.SESSION_EXPIRED)

    def test_user_logout_incoming_message(self):
        new_test_user(self.env, login="test_user", password="Password!1")
        user_session = self.authenticate("test_user", "Password!1")
        websocket = self.websocket_connect(cookie=f"session_id={user_session.sid};")
        self.url_open("/web/session/logout")
        self.subscribe(websocket, wait_for_dispatch=False)
        self.assert_close_with_code(websocket, CloseCode.SESSION_EXPIRED)

    def test_user_logout_outgoing_message(self):
        self.startPatcher(patch.object(Websocket, "SESSION_VALIDITY_TTL", 0))
        new_test_user(self.env, login="test_user", password="Password!1")
        user_session = self.authenticate("test_user", "Password!1")
        websocket = self.websocket_connect(cookie=f"session_id={user_session.sid};")
        self.subscribe(websocket, ["channel1"], self.env["bus.bus"]._bus_last_id())
        self.url_open("/web/session/logout")
        self.env["bus.bus"]._sendone("channel1", "notif type", "message")
        self.trigger_notification_dispatching(["channel1"])
        self.assert_close_with_code(websocket, CloseCode.SESSION_EXPIRED)

    def test_channel_subscription_disconnect(self):
        websocket = self.websocket_connect()
        self.subscribe(websocket, ["my_channel"], self.env["bus.bus"]._bus_last_id())
        self.assertIn(
            (self.env.registry.db_name, "my_channel"), dispatch._channels_to_ws
        )
        websocket.close(CloseCode.CLEAN)
        self.wait_remaining_websocket_connections()
        self.assertNotIn(
            (self.env.registry.db_name, "my_channel"), dispatch._channels_to_ws
        )

    def test_channel_subscription_update(self):
        websocket = self.websocket_connect()
        self.subscribe(websocket, ["my_channel"], self.env["bus.bus"]._bus_last_id())
        self.assertIn(
            (self.env.registry.db_name, "my_channel"), dispatch._channels_to_ws
        )
        self.subscribe(websocket, ["my_channel_2"], self.env["bus.bus"]._bus_last_id())
        self.assertNotIn(
            (self.env.registry.db_name, "my_channel"), dispatch._channels_to_ws
        )

    def test_trigger_notification(self):
        websocket = self.websocket_connect()
        self.subscribe(websocket, ["my_channel"], self.env["bus.bus"]._bus_last_id())
        self.env["bus.bus"]._sendone("my_channel", "notif_type", "message")
        self.trigger_notification_dispatching(["my_channel"])
        notifications = json.loads(websocket.recv())
        self.assertEqual(1, len(notifications))
        self.assertEqual(notifications[0]["message"]["type"], "notif_type")
        self.assertEqual(notifications[0]["message"]["payload"], "message")
        self.env["bus.bus"]._sendone("my_channel", "notif_type", "another_message")
        self.trigger_notification_dispatching(["my_channel"])
        notifications = json.loads(websocket.recv())
        self.assertEqual(1, len(notifications))
        self.assertEqual(notifications[0]["message"]["type"], "notif_type")
        self.assertEqual(notifications[0]["message"]["payload"], "another_message")

    def test_malformed_subscribe_data_keeps_connection_alive(self):
        self.startPatcher(patch.object(Websocket, "RL_BURST", 100))
        websocket = self.websocket_connect()
        malformed_payloads = [
            "not-a-dict",
            {"last": 0},
            {"channels": "not-a-list"},
            {"channels": [1, 2]},
            {"channels": [], "last": "not-an-int"},
        ]
        for data in malformed_payloads:
            with self.assertLogs(
                "odoo.addons.bus.websocket", level="WARNING"
            ) as capture:
                websocket.send(json.dumps({"event_name": "subscribe", "data": data}))
                websocket.ping()
                websocket.recv_data_frame(control_frame=True)
            self.assertTrue(
                any("Invalid websocket request" in line for line in capture.output),
                f"payload {data!r} should be rejected with a warning",
            )
        self.subscribe(websocket, ["my_channel"], self.env["bus.bus"]._bus_last_id())
        self.env["bus.bus"]._sendone("my_channel", "notif_type", "message")
        self.trigger_notification_dispatching(["my_channel"])
        notifications = json.loads(websocket.recv())
        self.assertEqual(1, len(notifications))
        self.assertEqual(notifications[0]["message"]["payload"], "message")

    def test_subscribe_without_last_defaults_to_zero(self):
        self.env["bus.bus"].sudo().search([]).unlink()
        websocket = self.websocket_connect()
        self.subscribe(websocket, ["my_channel"])
        self.env["bus.bus"]._sendone("my_channel", "notif_type", "message")
        self.trigger_notification_dispatching(["my_channel"])
        notifications = json.loads(websocket.recv())
        self.assertEqual(1, len(notifications))
        self.assertEqual(notifications[0]["message"]["type"], "notif_type")

    def test_trigger_notification_unsupported_language(self):
        websocket = self.websocket_connect()
        self.session.context["lang"] = "fr_LU"
        http.root.session_store.save(self.session)
        self.subscribe(websocket, ["my_channel"], self.env["bus.bus"]._bus_last_id())
        self.env["bus.bus"]._sendone("my_channel", "notif_type", "message")
        self.trigger_notification_dispatching(["my_channel"])
        notifications = json.loads(websocket.recv())
        self.assertEqual(1, len(notifications))
        self.assertEqual(notifications[0]["message"]["type"], "notif_type")
        self.assertEqual(notifications[0]["message"]["payload"], "message")

    def test_subscribe_higher_last_notification_id(self):
        server_last_notification_id = (
            self.env["bus.bus"].sudo().search([], limit=1, order="id desc").id or 0
        )
        client_last_notification_id = server_last_notification_id + 1

        with patch.object(
            Websocket, "subscribe", side_effect=Websocket.subscribe, autospec=True
        ) as mock:
            websocket = self.websocket_connect()
            self.subscribe(websocket, ["my_channel"], client_last_notification_id)
            self.assertEqual(mock.call_args[0][2], 0)

    def test_subscribe_lower_last_notification_id(self):
        server_last_notification_id = (
            self.env["bus.bus"].sudo().search([], limit=1, order="id desc").id or 0
        )
        client_last_notification_id = server_last_notification_id - 1

        with patch.object(
            Websocket, "subscribe", side_effect=Websocket.subscribe, autospec=True
        ) as mock:
            websocket = self.websocket_connect()
            self.subscribe(websocket, ["my_channel"], client_last_notification_id)
            self.assertEqual(mock.call_args[0][2], client_last_notification_id)

    def test_subscribe_to_custom_channel(self):
        channel = self.env["res.partner"].create({"name": "John"})
        websocket = self.websocket_connect()
        with patch.object(
            IrWebsocket, "_build_bus_channel_list", return_value=[channel]
        ):
            self.subscribe(websocket, [], self.env["bus.bus"]._bus_last_id())
            channel._bus_send("notif_on_global_channel", "message")
            channel._bus_send(
                "notif_on_private_channel", "message", subchannel="PRIVATE"
            )
            self.trigger_notification_dispatching([channel, (channel, "PRIVATE")])
            notifications = json.loads(websocket.recv())
            self.assertEqual(len(notifications), 1)
            self.assertEqual(
                notifications[0]["message"]["type"], "notif_on_global_channel"
            )
            self.assertEqual(notifications[0]["message"]["payload"], "message")

        with patch.object(
            IrWebsocket, "_build_bus_channel_list", return_value=[(channel, "PRIVATE")]
        ):
            self.subscribe(websocket, [], self.env["bus.bus"]._bus_last_id())
            channel._bus_send("notif_on_global_channel", "message")
            channel._bus_send(
                "notif_on_private_channel", "message", subchannel="PRIVATE"
            )
            self.trigger_notification_dispatching([channel, (channel, "PRIVATE")])
            notifications = json.loads(websocket.recv())
            self.assertEqual(len(notifications), 1)
            self.assertEqual(
                notifications[0]["message"]["type"], "notif_on_private_channel"
            )
            self.assertEqual(notifications[0]["message"]["payload"], "message")

    def test_no_cursor_when_no_callback_for_lifecycle_event(self):
        with patch.object(Websocket, "_Websocket__event_callbacks", defaultdict(set)):
            with patch("odoo.addons.bus.websocket.acquire_cursor") as mock:
                self.websocket_connect()
                self.assertFalse(mock.called)

    def _connect_and_capture_server_session(self, cookie, **connect_kwargs):
        captured_sessions = []
        serve_forever_called_event = Event()
        original_serve_forever = WebsocketConnectionHandler._serve_forever

        def serve_forever(websocket, *args):
            captured_sessions.append(websocket._session)
            serve_forever_called_event.set()
            original_serve_forever(websocket, *args)

        with patch.object(
            WebsocketConnectionHandler, "_serve_forever", side_effect=serve_forever
        ):
            ws = self.websocket_connect(cookie=cookie, **connect_kwargs)
            self.assertTrue(
                serve_forever_called_event.wait(timeout=5),
                "The websocket should have been served",
            )
        return ws, captured_sessions[0]

    def test_mismatched_origin_downgrades_to_public_session(self):
        new_test_user(self.env, login="test_user", password="Password!1")
        user_session = self.authenticate("test_user", "Password!1")
        with mute_logger("odoo.addons.bus.websocket"):
            ws, server_session = self._connect_and_capture_server_session(
                cookie=f"session_id={user_session.sid};",
                origin="http://attacker.example.com",
            )
        self.assertNotEqual(server_session.sid, user_session.sid)
        self.assertFalse(server_session.uid)
        set_cookie = ws.getheaders().get("set-cookie")
        if set_cookie:
            self.assertTrue(set_cookie.startswith(f"session_id={user_session.sid}"))
            self.assertNotIn(server_session.sid, set_cookie)

    @patch.dict(os.environ, {"ODOO_BUS_PUBLIC_SAMESITE_WS": "True"})
    def test_mismatched_origin_downgrades_with_legacy_env_var(self):
        new_test_user(self.env, login="test_user", password="Password!1")
        user_session = self.authenticate("test_user", "Password!1")
        with mute_logger("odoo.addons.bus.websocket"):
            _ws, server_session = self._connect_and_capture_server_session(
                cookie=f"session_id={user_session.sid};",
                origin="http://attacker.example.com",
            )
        self.assertNotEqual(server_session.sid, user_session.sid)
        self.assertFalse(server_session.uid)

    def test_downgraded_connections_share_one_public_session(self):
        new_test_user(self.env, login="test_user", password="Password!1")
        user_session = self.authenticate("test_user", "Password!1")
        with mute_logger("odoo.addons.bus.websocket"):
            _ws1, session1 = self._connect_and_capture_server_session(
                cookie=f"session_id={user_session.sid};",
                origin="http://attacker.example.com",
            )
            _ws2, session2 = self._connect_and_capture_server_session(
                cookie=f"session_id={user_session.sid};",
                origin="http://attacker.example.com",
            )
        self.assertFalse(session1.uid)
        self.assertFalse(session2.uid)
        self.assertNotEqual(session1.sid, user_session.sid)
        self.assertEqual(
            session1.sid,
            session2.sid,
            "Downgraded connections must share one public session, not mint one each",
        )

    def test_matching_origin_keeps_session(self):
        new_test_user(self.env, login="test_user", password="Password!1")
        user_session = self.authenticate("test_user", "Password!1")
        _ws, server_session = self._connect_and_capture_server_session(
            cookie=f"session_id={user_session.sid};",
        )
        self.assertEqual(server_session.sid, user_session.sid)
        self.assertEqual(server_session.uid, user_session.uid)

    @patch.dict(
        os.environ,
        {
            "ODOO_BUS_TRUSTED_ORIGINS": "https://cdn.example.com, http://trusted.example.com:8080"
        },
    )
    def test_trusted_origin_allowlist_keeps_session(self):
        new_test_user(self.env, login="test_user", password="Password!1")
        user_session = self.authenticate("test_user", "Password!1")
        _ws, server_session = self._connect_and_capture_server_session(
            cookie=f"session_id={user_session.sid};",
            origin="http://trusted.example.com:8080",
        )
        self.assertEqual(server_session.sid, user_session.sid)
        self.assertEqual(server_session.uid, user_session.uid)

    def test_session_validity_cached_between_dispatches(self):
        self.startPatcher(patch.object(Websocket, "SESSION_VALIDITY_TTL", 1000))
        new_test_user(self.env, login="test_user", password="Password!1")
        user_session = self.authenticate("test_user", "Password!1")
        websocket = self.websocket_connect(cookie=f"session_id={user_session.sid};")
        with patch(
            "odoo.addons.bus.websocket.check_session", wraps=check_session
        ) as check_session_spy:
            self.subscribe(
                websocket, ["ttl_channel"], self.env["bus.bus"]._bus_last_id()
            )
            self.assertEqual(
                check_session_spy.call_count,
                1,
                "The post-subscribe dispatch should have validated the session",
            )
            self.env["bus.bus"]._sendone("ttl_channel", "notif_type", "message")
            self.trigger_notification_dispatching(["ttl_channel"])
            notifications = json.loads(websocket.recv())
            self.assertEqual(len(notifications), 1)
            self.assertEqual(
                check_session_spy.call_count,
                1,
                "A dispatch within the TTL should reuse the cached validation",
            )
            self.subscribe(
                websocket, ["ttl_channel"], self.env["bus.bus"]._bus_last_id()
            )
            self.assertEqual(
                check_session_spy.call_count,
                2,
                "A resubscribe should force an immediate re-validation",
            )

    def test_session_validity_ttl_zero_validates_every_dispatch(self):
        self.startPatcher(patch.object(Websocket, "SESSION_VALIDITY_TTL", 0))
        new_test_user(self.env, login="test_user", password="Password!1")
        user_session = self.authenticate("test_user", "Password!1")
        websocket = self.websocket_connect(cookie=f"session_id={user_session.sid};")
        with patch(
            "odoo.addons.bus.websocket.check_session", wraps=check_session
        ) as check_session_spy:
            self.subscribe(
                websocket, ["ttl_channel"], self.env["bus.bus"]._bus_last_id()
            )
            self.env["bus.bus"]._sendone("ttl_channel", "notif_type", "message")
            self.trigger_notification_dispatching(["ttl_channel"])
            json.loads(websocket.recv())
            self.assertEqual(
                check_session_spy.call_count,
                2,
                "Each dispatch should re-validate the session when the TTL is 0",
            )

    def test_trigger_on_websocket_closed(self):
        with patch(
            "odoo.addons.bus.models.ir_websocket.IrWebsocket._on_websocket_closed"
        ) as mock:
            ws = self.websocket_connect()
            ws.close(CloseCode.CLEAN)
            self.wait_remaining_websocket_connections()
            self.assertTrue(mock.called)

    def test_disconnect_when_version_outdated(self):
        with (
            patch.object(WebsocketConnectionHandler, "_VERSION", "17.0-1"),
            patch.object(
                self, "_WEBSOCKET_URL", f"{self._BASE_WEBSOCKET_URL}?version=17.0-0"
            ),
        ):
            websocket = self.websocket_connect(
                ping_after_connect=False, header={"User-Agent": "Chrome/126.0.0.0"}
            )
            self.assert_close_with_code(websocket, CloseCode.CLEAN, "OUTDATED_VERSION")

        with (
            patch.object(WebsocketConnectionHandler, "_VERSION", "17.0-1"),
            patch.object(self, "_WEBSOCKET_URL", self._BASE_WEBSOCKET_URL),
        ):
            websocket = self.websocket_connect(
                ping_after_connect=False, header={"User-Agent": "Chrome/126.0.0.0"}
            )
            self.assert_close_with_code(websocket, CloseCode.CLEAN, "OUTDATED_VERSION")
        with (
            patch.object(WebsocketConnectionHandler, "_VERSION", "17.0-1"),
            patch.object(self, "_WEBSOCKET_URL", self._BASE_WEBSOCKET_URL),
        ):
            websocket = self.websocket_connect()
            websocket.ping()
            websocket.recv_data_frame(control_frame=True)

    def test_websocket_terminates_after_closing_timeout(self):
        orig_disconnect = Websocket._disconnect
        orig_terminate = Websocket._terminate
        disconnect_done_event = Event()
        terminate_done_event = Event()

        def disconnect_wrapper(self, code):
            orig_disconnect(self, code)
            disconnect_done_event.set()

        def terminate_wrapper(self):
            orig_terminate(self)
            terminate_done_event.set()

        with (
            patch("odoo.addons.bus.websocket.TimeoutManager.KEEP_ALIVE_TIMEOUT", 0),
            patch.object(Websocket, "_disconnect", disconnect_wrapper),
            patch.object(Websocket, "_terminate", terminate_wrapper),
            freeze_time("2022-08-19") as frozen_time,
        ):
            ws = self.websocket_connect(ping_after_connect=False)
            ws.send(b"\x00")
            self.assertTrue(
                disconnect_done_event.wait(timeout=5),
                "Server should have initiated the closing handshake as the keep alive timeout is exceeded.",
            )
            frozen_time.tick(delta=timedelta(seconds=TimeoutManager.TIMEOUT + 1))
            ws.send(b"\x00")
            self.assertTrue(
                terminate_done_event.wait(timeout=5),
                "Server should have terminated the connection as it didn't receive any response.",
            )

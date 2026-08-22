import contextlib
import json
from unittest.mock import MagicMock, patch
from urllib.parse import urlsplit

import psycopg

from odoo.http import SESSION_ROTATION_INTERVAL, root
from odoo.tests import JsonRpcException, common
from odoo.tools import mute_logger

from ..websocket import CloseCode, InvalidDatabaseError, WebsocketRequest
from .common import WebsocketCase
from odoo.addons.base.tests.common import HttpCaseWithUserDemo


class TestWebsocketController(HttpCaseWithUserDemo):
    def test_websocket_peek(self):
        result = self.make_jsonrpc_request(
            "/websocket/peek_notifications",
            {
                "channels": [],
                "last": 0,
                "is_first_poll": True,
            },
        )

        self.assertIsNotNone(result)
        channels = result.get("channels")
        self.assertIsNotNone(channels)
        self.assertIsInstance(channels, list)
        notifications = result.get("notifications")
        self.assertIsNotNone(notifications)
        self.assertIsInstance(notifications, list)

        result = self.make_jsonrpc_request(
            "/websocket/peek_notifications",
            {
                "channels": [],
                "last": 0,
                "is_first_poll": False,
            },
        )

        self.assertIsNotNone(result)

    def test_websocket_peek_session_expired_login(self):
        self.make_jsonrpc_request(
            "/websocket/peek_notifications",
            {
                "channels": [],
                "last": 0,
                "is_first_poll": True,
            },
        )

        self.authenticate("admin", "admin")
        with self.assertRaisesRegex(JsonRpcException, "SessionExpired"):
            self.make_jsonrpc_request(
                "/websocket/peek_notifications",
                {
                    "channels": [],
                    "last": 0,
                    "is_first_poll": False,
                },
            )

    def test_websocket_peek_session_expired_logout(self):
        self.authenticate("demo", "demo")
        self.make_jsonrpc_request(
            "/websocket/peek_notifications",
            {
                "channels": [],
                "last": 0,
                "is_first_poll": True,
            },
        )
        self.url_open("/web/session/logout")
        with self.assertRaisesRegex(JsonRpcException, "SessionExpired"):
            self.make_jsonrpc_request(
                "/websocket/peek_notifications",
                {
                    "channels": [],
                    "last": 0,
                    "is_first_poll": False,
                },
            )

    def test_do_not_rotate_session(self):
        self.authenticate("admin", "admin")
        self.url_open("/odoo")
        original_session = self.opener.cookies["session_id"]
        original_session_obj = root.session_store.get(original_session)
        original_session_obj["create_time"] -= SESSION_ROTATION_INTERVAL
        root.session_store.save(original_session_obj)
        self.make_jsonrpc_request(
            "/websocket/peek_notifications",
            {
                "channels": [],
                "last": 0,
                "is_first_poll": True,
            },
        )
        self.assertEqual(self.opener.cookies["session_id"], original_session)
        self.url_open("/odoo")
        self.assertNotEqual(self.opener.cookies["session_id"], original_session)
        original_session = self.opener.cookies["session_id"]
        original_session_obj = root.session_store.get(original_session)
        original_session_obj["create_time"] -= SESSION_ROTATION_INTERVAL
        root.session_store.save(original_session_obj)
        self.make_jsonrpc_request("/websocket/on_closed")
        self.assertEqual(self.opener.cookies["session_id"], original_session)

    def test_has_missed_notifications_rejects_non_integer(self):
        for bad_value in ("1", None, 1.5, [1], {"id": 1}, True):
            with (
                self.subTest(bad_value=bad_value),
                mute_logger("odoo.http"),
                self.assertRaises(JsonRpcException),
            ):
                self.make_jsonrpc_request(
                    "/bus/has_missed_notifications",
                    {"last_notification_id": bad_value},
                )

    def test_has_missed_notifications_with_integer(self):
        result = self.make_jsonrpc_request(
            "/bus/has_missed_notifications", {"last_notification_id": 0}
        )
        self.assertTrue(result)

    def test_has_missed_notifications_semantics(self):
        self.env["bus.bus"]._sendone("some_channel", "notif_type", "message")
        self.env.cr.precommit.run()
        notification = self.env["bus.bus"].sudo().search([], order="id desc", limit=1)
        self.assertTrue(notification)
        self.assertFalse(
            self.make_jsonrpc_request(
                "/bus/has_missed_notifications",
                {"last_notification_id": notification.id},
            ),
            "An existing watermark id must not be reported as missed",
        )
        notification_id = notification.id
        notification.unlink()
        self.assertTrue(
            self.make_jsonrpc_request(
                "/bus/has_missed_notifications",
                {"last_notification_id": notification_id},
            ),
            "A GC'd watermark id must be reported as missed",
        )


class TestWebsocketWorkerBundle(HttpCaseWithUserDemo):
    def _get_bundle(self, headers=None):
        return self.url_open(
            "/bus/websocket_worker_bundle", headers=headers, allow_redirects=False
        )

    def test_etag_revalidation(self):
        response = self._get_bundle()
        if response.status_code in (301, 302, 303, 307, 308):
            self.skipTest("esbuild unavailable: degraded raw-file path in use")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/javascript", response.headers["Content-Type"])
        etag = response.headers.get("ETag")
        self.assertTrue(etag, "The bundle response must carry an ETag")
        conditional = self._get_bundle(headers={"If-None-Match": etag})
        self.assertEqual(conditional.status_code, 304)
        self.assertFalse(conditional.content)

    def test_cors_headers_echoed_only_for_this_host(self):
        host = urlsplit(self.base_url()).hostname
        origin = f"http://{host}:8072"
        response = self._get_bundle(headers={"Origin": origin})
        self.assertEqual(response.headers.get("Access-Control-Allow-Origin"), origin)
        self.assertEqual(
            response.headers.get("Access-Control-Allow-Credentials"), "true"
        )
        self.assertIn("Origin", response.headers.get("Vary", ""))

        response = self._get_bundle(headers={"Origin": "https://evil.example"})
        self.assertNotIn("Access-Control-Allow-Origin", response.headers)
        self.assertNotIn("Access-Control-Allow-Credentials", response.headers)
        self.assertIn("Origin", response.headers.get("Vary", ""))

        response = self._get_bundle()
        self.assertNotIn("Access-Control-Allow-Origin", response.headers)
        self.assertNotIn("Access-Control-Allow-Credentials", response.headers)


@common.tagged("-at_install", "post_install")
class TestInvalidDatabase(WebsocketCase):
    def test_invalid_database_closes_with_try_later(self):
        ws = self.websocket_connect()
        with (
            patch.object(
                WebsocketRequest,
                "serve_websocket_message",
                side_effect=InvalidDatabaseError,
            ),
            mute_logger("odoo.addons.bus.websocket"),
        ):
            ws.send(json.dumps({"event_name": "noop", "data": {}}))
            self.assert_close_with_code(ws, CloseCode.TRY_LATER)

    def test_the_registry_kept_is_the_one_check_signaling_returned(self):
        req = WebsocketRequest.__new__(WebsocketRequest)
        req.db = self.env.registry.db_name
        req.ws = MagicMock()
        req.ws._session = MagicMock()
        registry = self.env.registry
        reloaded = MagicMock(db_name=registry.db_name)

        with (
            patch.object(WebsocketRequest, "_get_session", return_value=MagicMock()),
            patch.object(registry, "check_signaling", return_value=reloaded),
            patch.object(WebsocketRequest, "_serve_ir_websocket", return_value=None),
            contextlib.suppress(Exception),
        ):
            req.serve_websocket_message(json.dumps({"event_name": "noop"}))

        self.assertIs(
            req.registry,
            reloaded,
            "serve_websocket_message kept the registry it called "
            "check_signaling() ON instead of the one it returned",
        )

    def test_registry_failure_maps_to_invalid_database_error(self):
        req = WebsocketRequest.__new__(WebsocketRequest)
        req.db = self.env.registry.db_name
        req.ws = MagicMock()
        req.ws._session = MagicMock()
        registry = self.env.registry
        with (
            patch.object(WebsocketRequest, "_get_session", return_value=MagicMock()),
            patch.object(
                registry, "check_signaling", side_effect=psycopg.ProgrammingError
            ),
            self.assertRaises(InvalidDatabaseError),
        ):
            req.serve_websocket_message(json.dumps({"event_name": "noop"}))

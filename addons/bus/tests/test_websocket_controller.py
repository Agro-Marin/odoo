from odoo.http import SESSION_ROTATION_INTERVAL, root
from odoo.tests import JsonRpcException
from odoo.tools import mute_logger

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

        # Response containing channels/notifications is retrieved and is
        # conform to excpectations.
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

        # Reponse is received as long as the session is valid.
        self.assertIsNotNone(result)

    def test_websocket_peek_session_expired_login(self):
        # first rpc should be fine
        self.make_jsonrpc_request(
            "/websocket/peek_notifications",
            {
                "channels": [],
                "last": 0,
                "is_first_poll": True,
            },
        )

        self.authenticate("admin", "admin")
        # rpc with outdated session should lead to error.
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
        # first rpc should be fine
        self.make_jsonrpc_request(
            "/websocket/peek_notifications",
            {
                "channels": [],
                "last": 0,
                "is_first_poll": True,
            },
        )
        self.url_open("/web/session/logout")
        # rpc with outdated session should lead to error.
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
        """`last_notification_id` is client-controlled JSON: anything but an
        integer must be rejected instead of crashing the SQL query."""
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
        # id 0 can never exist (serial starts at 1): reported as missed.
        result = self.make_jsonrpc_request(
            "/bus/has_missed_notifications", {"last_notification_id": 0}
        )
        self.assertTrue(result)

    def test_has_missed_notifications_semantics(self):
        """An existing watermark id means nothing was missed; once the
        notification is gone (garbage-collected), the client must be told it
        missed notifications so it performs a full resync."""
        self.env["bus.bus"]._sendone("some_channel", "notif_type", "message")
        self.env.cr.precommit.run()  # trigger the creation of bus.bus records
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
        notification.unlink()  # simulate the GC having dropped the watermark
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
        """The bundle is served with an ETag and no max-age: a conditional
        request with a matching If-None-Match must be answered 304."""
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

    def test_cors_headers_echoed_only_with_origin(self):
        """The credentialed-CORS headers are added when (and only when) the
        request carries an Origin header; the origin is echoed back since
        `Access-Control-Allow-Origin: *` is forbidden with credentials."""
        origin = "http://other-origin.example.com:8072"
        response = self._get_bundle(headers={"Origin": origin})
        self.assertEqual(response.headers.get("Access-Control-Allow-Origin"), origin)
        self.assertEqual(
            response.headers.get("Access-Control-Allow-Credentials"), "true"
        )
        self.assertIn("Origin", response.headers.get("Vary", ""))
        response = self._get_bundle()
        self.assertNotIn("Access-Control-Allow-Origin", response.headers)
        self.assertNotIn("Access-Control-Allow-Credentials", response.headers)

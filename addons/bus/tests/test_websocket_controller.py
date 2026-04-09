from odoo.http import Request
from odoo.tests import HttpCase, JsonRpcException, tagged

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
        with self.assertRaises(
            JsonRpcException, msg="odoo.http.SessionExpiredException"
        ):
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
        with self.assertRaises(
            JsonRpcException, msg="odoo.http.SessionExpiredException"
        ):
            self.make_jsonrpc_request(
                "/websocket/peek_notifications",
                {
                    "channels": [],
                    "last": 0,
                    "is_first_poll": False,
                },
            )


@tagged("-at_install", "post_install")
class TestHasMissedNotifications(HttpCaseWithUserDemo):
    """Tests for the /bus/has_missed_notifications endpoint."""

    def test_notification_exists_returns_false(self):
        """When the notification still exists, the client has not missed it."""
        bus = self.env["bus.bus"]
        bus.search([]).unlink()
        bus._sendone("test_channel", "test_type", {"data": 1})
        self.env.cr.precommit.run()
        last_id = bus._bus_last_id()
        result = self.make_jsonrpc_request(
            "/bus/has_missed_notifications",
            {"last_notification_id": last_id},
        )
        self.assertFalse(result)

    def test_notification_missing_returns_true(self):
        """When the notification no longer exists, the client missed it."""
        bus = self.env["bus.bus"]
        bus.search([]).unlink()
        bus._sendone("test_channel", "test_type", {"data": 1})
        self.env.cr.precommit.run()
        last_id = bus._bus_last_id()
        # Delete the notification (simulate GC)
        self.env.cr.execute("DELETE FROM bus_bus WHERE id = %s", [last_id])
        result = self.make_jsonrpc_request(
            "/bus/has_missed_notifications",
            {"last_notification_id": last_id},
        )
        self.assertTrue(result)

    def test_nonexistent_id_returns_true(self):
        """An ID that never existed returns True (same as GC'd)."""
        result = self.make_jsonrpc_request(
            "/bus/has_missed_notifications",
            {"last_notification_id": 999_999_999},
        )
        self.assertTrue(result)

    def test_zero_id_returns_true(self):
        """Edge case: ID 0 never exists in the sequence."""
        result = self.make_jsonrpc_request(
            "/bus/has_missed_notifications",
            {"last_notification_id": 0},
        )
        self.assertTrue(result)


@tagged("-at_install", "post_install")
class TestGetModelDefinitionsValidation(HttpCase):
    """Tests for input validation on /bus/get_model_definitions.

    This is a ``type='http'`` POST route with CSRF protection, so we must
    include the ``csrf_token`` in the form data.
    """

    def setUp(self):
        super().setUp()
        self.authenticate("admin", "admin")

    def _post_model_definitions(self, model_names_to_fetch_json):
        """POST to the endpoint with form-encoded data + CSRF token."""
        return self.url_open(
            "/bus/get_model_definitions",
            data={
                "model_names_to_fetch": model_names_to_fetch_json,
                "csrf_token": Request.csrf_token(self),
            },
        )

    def test_valid_input(self):
        """A valid JSON array of model name strings succeeds."""
        response = self._post_model_definitions('["res.partner"]')
        self.assertEqual(response.status_code, 200)

    def test_non_list_input(self):
        """A JSON string (not array) is rejected with 400."""
        response = self._post_model_definitions('"res.partner"')
        self.assertEqual(response.status_code, 400)

    def test_non_string_elements(self):
        """An array with non-string elements is rejected with 400."""
        response = self._post_model_definitions("[1, 2, 3]")
        self.assertEqual(response.status_code, 400)

    def test_mixed_types(self):
        """An array mixing strings and non-strings is rejected."""
        response = self._post_model_definitions('["res.partner", 42]')
        self.assertEqual(response.status_code, 400)

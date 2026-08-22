from unittest.mock import patch

from odoo.tests import HttpCase, tagged

from ..models.bus import ImDispatch


class TestBusController(HttpCase):
    def test_health(self):
        response = self.url_open("/websocket/health")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "pass")
        self.assertFalse(response.cookies.get("session_id"))


@tagged("-at_install", "post_install")
class TestDispatcherHealth(HttpCase):
    def test_never_started_dispatcher_is_healthy(self):
        dispatch = ImDispatch()
        self.assertFalse(dispatch.is_alive())
        self.assertFalse(dispatch._ever_started)
        self.assertTrue(dispatch.is_healthy)

    def test_started_then_dead_dispatcher_is_unhealthy(self):
        dispatch = ImDispatch()
        dispatch._ever_started = True
        self.assertFalse(dispatch.is_alive())
        self.assertFalse(dispatch.is_healthy)

    def test_health_endpoint_reports_a_dead_dispatcher(self):
        with patch("odoo.addons.bus.controllers.websocket.dispatch") as mock_dispatch:
            mock_dispatch.is_healthy = False
            response = self.url_open("/websocket/health")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["status"], "fail")

    def test_shutting_down_server_reports_unhealthy(self):
        dispatch = ImDispatch()
        dispatch._ever_started = True
        with patch("odoo.addons.bus.models.bus.stop_event") as stop_event:
            stop_event.is_set.return_value = True
            self.assertFalse(dispatch.is_healthy)

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
    """``/websocket/health`` must report the dispatcher, not just the WSGI stack.

    It used to answer ``pass`` unconditionally, so a node whose ``ImDispatch``
    thread had died kept advertising itself as healthy and kept being handed
    websocket traffic it could never dispatch.
    """

    def test_never_started_dispatcher_is_healthy(self):
        """The thread starts lazily on the first subscriber.

        Probing ``is_alive()`` directly would fail every freshly booted server
        until someone connected -- evicting a perfectly good node from the
        load-balancer pool.
        """
        dispatch = ImDispatch()
        self.assertFalse(dispatch.is_alive())
        self.assertFalse(dispatch._ever_started)
        self.assertTrue(dispatch.is_healthy)

    def test_started_then_dead_dispatcher_is_unhealthy(self):
        dispatch = ImDispatch()
        dispatch._ever_started = True  # started, and since terminated
        self.assertFalse(dispatch.is_alive())
        self.assertFalse(dispatch.is_healthy)

    def test_health_endpoint_reports_a_dead_dispatcher(self):
        with patch("odoo.addons.bus.controllers.websocket.dispatch") as mock_dispatch:
            mock_dispatch.is_healthy = False
            response = self.url_open("/websocket/health")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["status"], "fail")

    def test_shutting_down_server_reports_unhealthy(self):
        """So the node drains out of the pool before it stops answering."""
        dispatch = ImDispatch()
        dispatch._ever_started = True
        with patch("odoo.addons.bus.models.bus.stop_event") as stop_event:
            stop_event.is_set.return_value = True
            self.assertFalse(dispatch.is_healthy)

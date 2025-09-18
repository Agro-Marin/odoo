# Part of Odoo. See LICENSE file for full copyright and licensing details.

from unittest.mock import MagicMock, patch

from odoo.addons.bus.models.ir_http import _websocket_session_info
from odoo.addons.bus.websocket import WebsocketConnectionHandler
from odoo.tests.common import BaseCase


def _mock_config(workers, proxy_mode, gevent_port=8072):
    """Return a config-like mock for the three keys read by _websocket_session_info."""
    values = {"workers": workers, "proxy_mode": proxy_mode, "gevent_port": gevent_port}
    m = MagicMock()
    m.__getitem__ = MagicMock(side_effect=values.__getitem__)
    return m


class TestWebsocketSessionInfo(BaseCase):
    """Unit tests for _websocket_session_info().

    The function has no ORM dependency so we test it without a database,
    patching only the config values it reads.
    """

    def _patch(self, **kw):
        return patch("odoo.addons.bus.models.ir_http.config", _mock_config(**kw))

    def test_always_includes_worker_version(self):
        """websocket_worker_version is present in every mode."""
        for workers, proxy_mode in [(0, False), (4, False), (4, True)]:
            with self._patch(workers=workers, proxy_mode=proxy_mode):
                result = _websocket_session_info()
            self.assertIn("websocket_worker_version", result)
            self.assertEqual(
                result["websocket_worker_version"],
                WebsocketConnectionHandler._VERSION,
            )

    def test_prefork_without_proxy_exposes_gevent_port(self):
        """workers>0 + proxy_mode=False → client gets websocket_gevent_port.

        This is the root cause of 503 WebSocket errors when running in prefork
        mode without a reverse proxy: WorkerHTTP uses CommonRequestHandler which
        never adds environ["socket"], so WebsocketConnectionHandler.open_connection()
        raises ServiceUnavailable. The client must connect to the EventServer port
        (gevent_port, default 8072) instead.
        """
        with self._patch(workers=4, proxy_mode=False, gevent_port=8072):
            result = _websocket_session_info()
        self.assertEqual(result["websocket_gevent_port"], 8072)

    def test_threaded_mode_no_port_exposed(self):
        """workers=0 (threaded mode) → no websocket_gevent_port in session.

        In threaded mode ThreadedWSGIServerReloadable uses RequestHandler which
        does add environ["socket"], so WebSocket works on the main port directly.
        """
        with self._patch(workers=0, proxy_mode=False):
            result = _websocket_session_info()
        self.assertNotIn("websocket_gevent_port", result)

    def test_prefork_with_proxy_no_port_exposed(self):
        """workers>0 + proxy_mode=True → no websocket_gevent_port in session.

        When a reverse proxy is in use it routes WebSocket upgrade requests to
        the EventServer transparently, so the client sees a single origin and
        needs no port override.
        """
        with self._patch(workers=4, proxy_mode=True):
            result = _websocket_session_info()
        self.assertNotIn("websocket_gevent_port", result)

    def test_gevent_port_value_is_forwarded(self):
        """The actual gevent_port value from config is forwarded unchanged."""
        with self._patch(workers=2, proxy_mode=False, gevent_port=9999):
            result = _websocket_session_info()
        self.assertEqual(result["websocket_gevent_port"], 9999)

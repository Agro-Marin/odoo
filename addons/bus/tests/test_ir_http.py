from unittest.mock import MagicMock, patch

from odoo.tests.common import BaseCase

from odoo.addons.bus.models.ir_http import _websocket_session_info
from odoo.addons.bus.websocket import WebsocketConnectionHandler


def _mock_config(workers, proxy_mode, gevent_port=8072):
    values = {"workers": workers, "proxy_mode": proxy_mode, "gevent_port": gevent_port}
    m = MagicMock()
    m.__getitem__ = MagicMock(side_effect=values.__getitem__)
    return m


class TestWebsocketSessionInfo(BaseCase):
    def _patch(self, **kw):
        return patch("odoo.addons.bus.models.ir_http.config", _mock_config(**kw))

    def test_always_includes_worker_version(self):
        for workers, proxy_mode in [(0, False), (4, False), (4, True)]:
            with self._patch(workers=workers, proxy_mode=proxy_mode):
                result = _websocket_session_info()
            self.assertIn("websocket_worker_version", result)
            self.assertEqual(
                result["websocket_worker_version"],
                WebsocketConnectionHandler._VERSION,
            )

    def test_prefork_without_proxy_exposes_gevent_port(self):
        with self._patch(workers=4, proxy_mode=False, gevent_port=8072):
            result = _websocket_session_info()
        self.assertEqual(result["websocket_gevent_port"], 8072)

    def test_threaded_mode_no_port_exposed(self):
        with self._patch(workers=0, proxy_mode=False):
            result = _websocket_session_info()
        self.assertNotIn("websocket_gevent_port", result)

    def test_prefork_with_proxy_no_port_exposed(self):
        with self._patch(workers=4, proxy_mode=True):
            result = _websocket_session_info()
        self.assertNotIn("websocket_gevent_port", result)

    def test_gevent_port_value_is_forwarded(self):
        with self._patch(workers=2, proxy_mode=False, gevent_port=9999):
            result = _websocket_session_info()
        self.assertEqual(result["websocket_gevent_port"], 9999)

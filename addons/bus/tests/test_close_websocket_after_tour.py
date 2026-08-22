import gc
from unittest.mock import patch
from weakref import WeakSet

from odoo.tests import tagged

from .. import websocket as websocket_module
from .common import WebsocketCase


@tagged("-at_install", "post_install")
class TestCloseWebsocketAfterTour(WebsocketCase):
    @patch("odoo.tests.common.ChromeBrowser")
    def test_ensure_websocket_closed_after_tour(self, mocked_brower_class):
        websocket_created = False

        def navigate_to_side_effect(*args, **kwargs):
            self.websocket_connect()
            self.assertEqual(len(websocket_module._websocket_instances), 1)
            nonlocal websocket_created
            websocket_created = True

        mocked_brower_class.return_value.navigate_to.side_effect = (
            navigate_to_side_effect
        )

        with patch.object(websocket_module, "_websocket_instances", WeakSet()):
            self.browser_js("/odoo", "")
            self.assertTrue(websocket_created)
            self._serve_forever_patch.stop()
            gc.collect()
            self.assertEqual(len(websocket_module._websocket_instances), 0)

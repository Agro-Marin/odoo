import contextlib
import inspect
import json
import struct
import unittest
from queue import Empty, SimpleQueue
from threading import Event
from unittest.mock import patch

from werkzeug.exceptions import BadRequest

try:
    import websocket
except ImportError:
    websocket = None

from odoo.http import request
from odoo.tests import HttpCase
from odoo.tests.common import (
    HOST,
    TEST_CURSOR_COOKIE_NAME,
    Like,
    _registry_test_lock,
    release_test_lock,
)

from ..models.bus import channel_with_db, dispatch, hashable
from ..websocket import CloseCode, Websocket, WebsocketConnectionHandler


def channel_key(env, channel):
    return hashable(channel_with_db(env.cr.dbname, channel))


def channel_keys(env, channels):
    return [channel_key(env, channel) for channel in channels]


class WebsocketCase(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if websocket is None:
            cls._logger.warning("websocket-client module is not installed")
            raise unittest.SkipTest("websocket-client module is not installed")
        cls._BASE_WEBSOCKET_URL = f"ws://{HOST}:{cls.http_port()}/websocket"
        cls._WEBSOCKET_URL = (
            f"{cls._BASE_WEBSOCKET_URL}?version={WebsocketConnectionHandler._VERSION}"
        )
        websocket_allowed_patch = patch.object(
            WebsocketConnectionHandler, "websocket_allowed", return_value=True
        )
        cls.startClassPatcher(websocket_allowed_patch)

    def setUp(self):
        super().setUp()
        self._websockets = set()
        self._websocket_close_events = []
        self._pending_websocket_close_events = SimpleQueue()
        original_open_connection = WebsocketConnectionHandler.open_connection

        def _mocked_open_connection(*args, **kwargs):
            response = original_open_connection(*args, **kwargs)
            websocket_closed_event = Event()
            self._websocket_close_events.append(websocket_closed_event)
            self._pending_websocket_close_events.put(websocket_closed_event)
            return response

        self.startPatcher(
            patch.object(
                WebsocketConnectionHandler, "open_connection", _mocked_open_connection
            )
        )
        original_serve_forever = WebsocketConnectionHandler._serve_forever

        def _mocked_serve_forever(*args):
            try:
                websocket_closed_event = (
                    self._pending_websocket_close_events.get_nowait()
                )
            except Empty:
                websocket_closed_event = None
            try:
                original_serve_forever(*args)
            finally:
                if websocket_closed_event is not None:
                    websocket_closed_event.set()

        self._serve_forever_patch = patch.object(
            WebsocketConnectionHandler, "_serve_forever", wraps=_mocked_serve_forever
        )
        self.startPatcher(self._serve_forever_patch)
        self.enterContext(
            release_test_lock()
        )
        self.http_request_key = "websocket"

    def tearDown(self):
        self._close_websockets()
        super().tearDown()

    def _close_websockets(self):
        for ws in self._websockets:
            if ws.connected:
                ws.close(CloseCode.CLEAN)
        self.wait_remaining_websocket_connections()

    @contextlib.contextmanager
    def allow_requests(self, *args, **kwargs):
        with _registry_test_lock, super().allow_requests(*args, **kwargs):
            yield

    def assertCanOpenTestCursor(self):
        allowed_methods = [
            ("acquire_cursor", Like(".../bus/websocket.py")),
        ]
        if (
            any(
                frame.function == function and frame.filename == filename
                for frame in inspect.stack()
                for function, filename in allowed_methods
            )
            or request
        ):
            return super().assertCanOpenTestCursor()
        raise BadRequest("Opening a cursor from an unknown method in websocket test.")

    def websocket_connect(self, *args, ping_after_connect=True, **kwargs):
        if "cookie" not in kwargs:
            self.session = self.authenticate(None, None)
            kwargs["cookie"] = f"session_id={self.session.sid}"
        kwargs.setdefault("timeout", 10)
        kwargs["cookie"] += f";{TEST_CURSOR_COOKIE_NAME}={self.http_request_key}"
        ws = websocket.create_connection(self._WEBSOCKET_URL, *args, **kwargs)
        if ping_after_connect:
            ws.ping()
            ws.recv_data_frame(control_frame=True)
        self._websockets.add(ws)
        return ws

    def subscribe(self, websocket, channels=None, last=None, wait_for_dispatch=True):
        dispatch_bus_notification_done = Event()
        original_dispatch_bus_notifications = Websocket._dispatch_bus_notifications

        def _mocked_dispatch_bus_notifications(self, *args):
            original_dispatch_bus_notifications(self, *args)
            dispatch_bus_notification_done.set()

        with patch.object(
            Websocket, "_dispatch_bus_notifications", _mocked_dispatch_bus_notifications
        ):
            sub = {
                "event_name": "subscribe",
                "data": {
                    "channels": channels or [],
                },
            }
            if last is not None:
                sub["data"]["last"] = last
            websocket.send(json.dumps(sub))
            if wait_for_dispatch:
                self.assertTrue(
                    dispatch_bus_notification_done.wait(timeout=5),
                    "Subscription should have triggered a notification dispatch "
                    "(use wait_for_dispatch=False for subscriptions expected to "
                    "be rejected)",
                )

    def trigger_notification_dispatching(self, channels):
        self.env.cr.precommit.run()
        channels = [
            hashable(channel_with_db(self.registry.db_name, c)) for c in channels
        ]
        websockets = set()
        for channel in channels:
            websockets.update(dispatch._channels_to_ws.get(hashable(channel), []))
        for websocket in websockets:
            websocket.trigger_notification_dispatching()

    def wait_remaining_websocket_connections(self):
        for event in self._websocket_close_events:
            self.assertTrue(
                event.wait(5),
                "A websocket connection did not terminate within 5 seconds",
            )

    def assert_close_with_code(self, websocket, expected_code, expected_reason=None):
        opcode, payload = websocket.recv_data()
        self.assertEqual(opcode, 8)
        code = struct.unpack("!H", payload[:2])[0]
        self.assertEqual(code, expected_code)
        if expected_reason:
            self.assertEqual(payload[2:].decode(), expected_reason)


class BusCase:
    def _reset_bus(self):
        self.env.cr.precommit.run()
        self.env["bus.bus"].sudo().search([]).unlink()

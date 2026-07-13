"""WebSocket serving layer of the ``bus`` module.

Cross-site WebSocket hijacking (CSWSH) protection
-------------------------------------------------
Browsers do not apply the same-origin policy to WebSocket handshakes: any
web page can open a connection to ``/websocket`` and the browser attaches
the victim's session cookie (subject only to its SameSite policy). To
prevent a cross-site page from acting with an authenticated session, a
handshake whose ``Origin`` header does not match the request host — as seen
by ``odoo.http``, i.e. after ``proxy_mode`` folded the ``X-Forwarded-*``
headers into the WSGI environ — is downgraded to a brand new public
(unauthenticated) session.

Environment variables:

- ``ODOO_BUS_TRUSTED_ORIGINS``: comma-separated allowlist of origins
  (``scheme://host[:port]``) additionally permitted to open websocket
  connections with the request's authenticated session, for deployments
  that legitimately serve websockets cross-origin.
- ``ODOO_BUS_PUBLIC_SAMESITE_WS``: legacy opt-in flag for the downgrade
  behaviour described above. The downgrade is now the default; the
  variable is still accepted but has no effect.
"""

import base64
import bisect
import functools
import hashlib
import logging
import os
import random
import selectors
import socket
import struct
import sys
import threading
import time
from collections import defaultdict, deque
from contextlib import contextmanager, suppress
from enum import IntEnum
from itertools import count
from queue import PriorityQueue
from urllib.parse import urlparse
from weakref import WeakSet

import psycopg
from werkzeug.datastructures import ImmutableMultiDict, MultiDict
from werkzeug.exceptions import BadRequest, HTTPException, ServiceUnavailable
from werkzeug.local import LocalStack

from odoo import api, modules
from odoo.db import PoolError
from odoo.http import (
    Request,
    Response,
    SessionExpiredException,
    get_default_session,
    root,
)
from odoo.modules.registry import Registry
from odoo.service.security import check_session
from odoo.service.server import CommonServer
from odoo.service.transaction import retrying
from odoo.tools import config

from .models.bus import dispatch
from .tools import orjson

_logger = logging.getLogger(__name__)


MAX_TRY_ON_POOL_ERROR = 10
DELAY_ON_POOL_ERROR = 0.15
JITTER_ON_POOL_ERROR = 0.3


@contextmanager
def acquire_cursor(db):
    """Try to acquire a cursor up to `MAX_TRY_ON_POOL_ERROR`.

    Uses explicit context manager protocol to avoid ``suppress(PoolError)``
    accidentally swallowing PoolErrors raised by the caller's code after
    ``yield``.
    """
    delay = DELAY_ON_POOL_ERROR
    try:
        for attempt in range(1, MAX_TRY_ON_POOL_ERROR + 1):
            # Yield before trying to acquire the cursor to let other
            # threads release their cursor.
            time.sleep(0)
            try:
                cm = Registry(db).cursor()
                cr = cm.__enter__()
            except PoolError:
                if attempt == MAX_TRY_ON_POOL_ERROR:
                    raise PoolError(
                        f"Failed to acquire cursor after {MAX_TRY_ON_POOL_ERROR} retries"
                    ) from None
            else:
                try:
                    yield cr
                    return
                finally:
                    cm.__exit__(*sys.exc_info())
            time.sleep(delay + random.uniform(0, JITTER_ON_POOL_ERROR))
            delay *= 1.5
    finally:
        # Yield after releasing the cursor to let waiting threads
        # immediately pick up the freed connection.
        time.sleep(0)


# ------------------------------------------------------
# EXCEPTIONS
# ------------------------------------------------------


class UpgradeRequired(HTTPException):
    code = 426
    description = "Wrong websocket version was given during the handshake"

    def get_headers(self, environ=None):
        headers = super().get_headers(environ)
        headers.append(
            (
                "Sec-WebSocket-Version",
                "; ".join(WebsocketConnectionHandler.SUPPORTED_VERSIONS),
            )
        )
        return headers


class WebsocketError(Exception):
    """Base class for all websockets exceptions"""


class ConnectionClosedError(WebsocketError):
    """
    Raised when the other end closes the socket without performing
    the closing handshake.
    """


class InvalidCloseCodeError(WebsocketError):
    def __init__(self, code):
        super().__init__(f"Invalid close code: {code}")


class InvalidDatabaseError(WebsocketError):
    """
    When raised: the database probably does not exists anymore, the
    database is corrupted or the database version doesn't match the
    server version.
    """


class InvalidStateError(WebsocketError):
    """
    Raised when an operation is forbidden in the current state.
    """


class InvalidWebsocketRequestError(WebsocketError):
    """
    Raised when a websocket request is invalid (format, wrong args).
    """


class PayloadTooLargeError(WebsocketError):
    """
    Raised when a websocket message is too large.
    """


class ProtocolError(WebsocketError):
    """
    Raised when a frame format doesn't match expectations.
    """


class RateLimitExceededError(Exception):
    """
    Raised when a client exceeds the number of request in a given
    time.
    """


# Idea taken from the python cookbook:
# https://github.com/dabeaz/python-cookbook/blob/6e46b7/src/12/polling_multiple_thread_queues/pqueue.py
class PollablePriorityQueue(PriorityQueue):
    """A custom PriorityQueue than can be polled"""

    def __init__(self, maxsize=0):
        super().__init__(maxsize)
        self._putsocket, self._getsocket = socket.socketpair()

    def fileno(self):
        return self._getsocket.fileno()

    def put(self, item, *args, **kwargs):
        super().put(item, *args, **kwargs)
        self._putsocket.send(b".")

    def get(self, *args, **kwargs):
        self._getsocket.recv(1)
        return super().get(*args, **kwargs)

    def close(self):
        self._putsocket.close()
        self._getsocket.close()


# ------------------------------------------------------
# WEBSOCKET LIFECYCLE
# ------------------------------------------------------


class LifecycleEvent(IntEnum):
    OPEN = 0
    CLOSE = 1


# ------------------------------------------------------
# WEBSOCKET
# ------------------------------------------------------


class Opcode(IntEnum):
    CONTINUE = 0x00
    TEXT = 0x01
    BINARY = 0x02
    CLOSE = 0x08
    PING = 0x09
    PONG = 0x0A


class CloseCode(IntEnum):
    CLEAN = 1000
    GOING_AWAY = 1001
    PROTOCOL_ERROR = 1002
    INCORRECT_DATA = 1003
    ABNORMAL_CLOSURE = 1006
    INCONSISTENT_DATA = 1007
    MESSAGE_VIOLATING_POLICY = 1008
    MESSAGE_TOO_BIG = 1009
    EXTENSION_NEGOTIATION_FAILED = 1010
    SERVER_ERROR = 1011
    RESTART = 1012
    TRY_LATER = 1013
    BAD_GATEWAY = 1014
    SESSION_EXPIRED = 4001
    KEEP_ALIVE_TIMEOUT = 4002
    KILL_NOW = 4003


class ConnectionState(IntEnum):
    OPEN = 0
    CLOSING = 1
    CLOSED = 2


# Used to maintain order of commands in the queue according to their priority
# (IntEnum) and then the order of reception.
_command_uid = count(0)


class ControlCommand(IntEnum):
    CLOSE = 0
    DISPATCH = 1


DATA_OP = {Opcode.TEXT, Opcode.BINARY}
CTRL_OP = {Opcode.CLOSE, Opcode.PING, Opcode.PONG}
HEARTBEAT_OP = {Opcode.PING, Opcode.PONG}

VALID_CLOSE_CODES = {
    code for code in CloseCode if code is not CloseCode.ABNORMAL_CLOSURE
}
RESERVED_CLOSE_CODES = range(3000, 5000)

_XOR_TABLE = [bytes(a ^ b for a in range(256)) for b in range(256)]


class Frame:
    __slots__ = ("fin", "opcode", "payload", "rsv1", "rsv2", "rsv3")

    def __init__(
        self, opcode, payload=b"", fin=True, rsv1=False, rsv2=False, rsv3=False
    ):
        self.opcode = opcode
        self.payload = payload
        self.fin = fin
        self.rsv1 = rsv1
        self.rsv2 = rsv2
        self.rsv3 = rsv3


class CloseFrame(Frame):
    __slots__ = ("code", "reason")

    # Control frames are limited to a 125 byte payload (RFC 6455 §5.5); the
    # close code takes 2 bytes, leaving 123 bytes for the reason.
    MAX_REASON_LENGTH = 123

    def __init__(self, code, reason):
        if code not in VALID_CLOSE_CODES and code not in RESERVED_CLOSE_CODES:
            raise InvalidCloseCodeError(code)
        payload = struct.pack("!H", code)
        if reason:
            encoded_reason = reason.encode("utf-8")
            if len(encoded_reason) > self.MAX_REASON_LENGTH:
                # Truncate on a codepoint boundary: a hard byte cut could
                # split a multi-byte sequence and produce invalid UTF-8,
                # which peers reject with INCONSISTENT_DATA. Reasons are
                # free-form diagnostics (often ``str(exc)``), truncation is
                # preferable to failing to close cleanly.
                reason = encoded_reason[: self.MAX_REASON_LENGTH].decode(
                    "utf-8", errors="ignore"
                )
                encoded_reason = reason.encode("utf-8")
            payload += encoded_reason
        self.code = code
        self.reason = reason
        super().__init__(Opcode.CLOSE, payload)


_websocket_instances = WeakSet()
# ``WeakSet`` iteration is guarded against GC removals, but a concurrent
# ``add`` from a serving thread while another thread snapshots the set
# (``list(...)`` in ``_kick_all``) still raises ``RuntimeError: set changed
# size during iteration``. Serialize additions and snapshots.
_websocket_instances_lock = threading.Lock()


class NotificationDispatchState:
    """Per-websocket bookkeeping for bus notification dispatching.

    Deduplicates notifications by id while holding the low-water-mark id
    (``last_id``) back for a few seconds, so that notifications committed out of
    id order by concurrent transactions are not skipped. See
    ``Websocket.MAX_NOTIFICATION_HISTORY_SEC`` for the full rationale.

    Kept free of any socket/ORM coupling so the tricky ordering logic can be
    unit-tested in isolation.
    """

    __slots__ = ("_clock", "_history", "_retention_sec", "last_id")

    # Hard bound on the history length: ``record_dispatched`` runs an O(n)
    # insort and ``ignore_ids`` copies the whole list on every poll, so a
    # pathological notification burst must not let the history grow without
    # limit. Expired ids are trimmed on every call; the cap only bites when
    # more than this many ids are dispatched *within* ``_retention_sec``.
    MAX_HISTORY_LENGTH = 5000

    def __init__(self, retention_sec, clock=None):
        # Injectable clock (unit tests). Monotonic by default: a backward
        # NTP step must not pin the history retention logic.
        self._clock = clock if clock is not None else time.monotonic
        # Seconds a dispatched id is kept in history before it may raise last_id.
        self._retention_sec = retention_sec
        # Id of the last dispatched notification no longer held in _history.
        self.last_id = 0
        # Dispatched notifications as (id, dispatch_time), always sorted by id ASC.
        self._history = []

    @property
    def ignore_ids(self):
        """Ids already dispatched but still held back, to exclude from polling."""
        return [nid for nid, _sent_at in self._history]

    def initialize_last_id(self, last):
        """Adopt the client's ``last`` id, but only while still at the initial 0.

        After the first assignment the server's own tracking is authoritative
        (the client may reconnect with a stale value).
        """
        if self.last_id == 0:
            self.last_id = last

    def record_dispatched(self, notif_ids):
        """Record that ``notif_ids`` were dispatched now and advance
        ``last_id`` past the contiguous prefix of expired ids.

        Only the contiguous run of the lowest expired ids may be dropped: an id
        cannot be forgotten while any smaller id is still held back, otherwise
        the next ``id > last_id`` poll would fetch it again.

        For example, if the threshold is 10s and the state is
        ``last_id 2, history [(3, 8s), (6, 10s), (7, 7s)]``: if 6 were removed
        because it is above the threshold, the next query would be
        ``id > 2 AND id NOT IN (3, 7)`` which would fetch 6 again. 6 can only be
        removed after 3 reaches the threshold and is removed as well; and if 4
        appears in the meantime, 3 can be removed but 6 must wait for 4 to reach
        the threshold too.
        """
        now = self._clock()
        for nid in notif_ids:
            bisect.insort(self._history, (nid, now), key=lambda entry: entry[0])
        last_index = -1
        for i, (_nid, sent_at) in enumerate(self._history):
            if now - sent_at > self._retention_sec:
                last_index = i
            else:
                break
        if last_index != -1:
            self.last_id = self._history[last_index][0]
            self._history = self._history[last_index + 1 :]
        overflow = len(self._history) - self.MAX_HISTORY_LENGTH
        if overflow > 0:
            # Cap hit: drop the oldest (lowest) ids even though they are
            # still within the retention window, advancing ``last_id`` past
            # them so they cannot be re-fetched. Notifications with a lower
            # id committed late may then be skipped -- an accepted trade-off
            # against unbounded memory/CPU growth.
            self.last_id = self._history[overflow - 1][0]
            del self._history[:overflow]
            _logger.debug(
                "Notification dispatch history capped: dropped %s ids still "
                "within the retention window",
                overflow,
            )


class Websocket:
    __event_callbacks = defaultdict(set)
    # Maximum size for a message in bytes, whether it is sent as one
    # frame or many fragmented ones.
    MESSAGE_MAX_SIZE = 2**20
    # How much time (in second) the history of last dispatched notifications is
    # kept in memory for each websocket.
    # To avoid duplicate notifications, we fetch them based on their ids.
    # However during parallel transactions, ids are assigned immediately (when
    # they are requested), but the notifications are dispatched at the time of
    # the commit. This means lower id notifications might be dispatched after
    # higher id notifications.
    # Simply incrementing the last id is sufficient to guarantee no duplicates,
    # but it is not sufficient to guarantee all notifications are dispatched,
    # and in particular not sufficient for those with a lower id coming after a
    # higher id was dispatched.
    # To solve the issue of missed notifications, the lowest id, stored in
    # ``NotificationDispatchState.last_id``, is held back by a few seconds to
    # give time for concurrent transactions to finish. To avoid dispatching
    # duplicate notifications, the history of already dispatched notifications
    # during this period is kept in memory and the corresponding notifications
    # are discarded from subsequent dispatching even if their id is higher than
    # ``last_id``.
    # In practice, what is important functionally is the time between the create
    # of the notification and the commit of the transaction in business code.
    # If this time exceeds this threshold, the notification will never be
    # dispatched if the target user receive any other notification in the
    # meantime.
    # Transactions known to be long should therefore create their notifications
    # at the end, as close as possible to their commit.
    MAX_NOTIFICATION_HISTORY_SEC = 10
    # How many requests can be made in excess of the given rate.
    # Clamped to >= 1: `_limit_rate` indexes the timestamp deque, and a
    # zero-length deque (burst 0) would raise IndexError on every frame
    # instead of the intended RateLimitExceededError.
    RL_BURST = max(1, int(config["websocket_rate_limit_burst"]))
    # How many seconds between each request.
    RL_DELAY = float(config["websocket_rate_limit_delay"])
    # Control frames (PING/PONG/CLOSE) and continuation frames of a
    # fragmented message do not count against the data-message budget above
    # (a PONG burst answering server PINGs, or a well-behaved client
    # fragmenting a large message, must not trip the limit). They still get
    # their own limiter, this many times more generous, so a PING or
    # empty-continuation flood cannot bypass rate limiting entirely.
    RL_CONTROL_FACTOR = 10
    # How long (seconds, monotonic) a successful session validation
    # (session-store read + ``check_session``) is trusted before
    # ``_dispatch_bus_notifications`` re-validates. Trade-off: a session that
    # is logged out / expired keeps receiving notifications for at most this
    # long before the socket is closed with SESSION_EXPIRED; in exchange,
    # each DISPATCH is spared a session-store read and an HMAC check. Set to
    # 0 to re-validate on every dispatch (used by tests that need exact
    # session-expiry semantics).
    SESSION_VALIDITY_TTL = 60

    def __init__(self, sock, session, cookies):
        # Session linked to the current websocket connection.
        self._session = session
        # Cookies linked to the current websocket connection.
        self._cookies = cookies
        self._db = session.db
        self.__socket = sock
        self._close_sent = False
        self._close_received = False
        self._timeout_manager = TimeoutManager()
        # Used for rate limiting: message-starting data frames on one side,
        # control/continuation frames on the other (see RL_CONTROL_FACTOR).
        self._incoming_frame_timestamps = deque(maxlen=self.RL_BURST)
        self._incoming_control_frame_timestamps = deque(
            maxlen=self.RL_BURST * self.RL_CONTROL_FACTOR
        )
        # Command queue used to manage the websocket instance externally, such
        # as triggering notification dispatching or terminating the connection.
        self.__cmd_queue = PollablePriorityQueue()
        self._waiting_for_dispatch = False
        self._channels = set()
        # Session validity cache, see ``SESSION_VALIDITY_TTL``.
        self._session_validated_until = 0.0
        self._validated_session_sid = None
        # Notification dedup / hold-back bookkeeping, see
        # ``MAX_NOTIFICATION_HISTORY_SEC`` and ``NotificationDispatchState``.
        self._dispatch_state = NotificationDispatchState(
            self.MAX_NOTIFICATION_HISTORY_SEC
        )
        # Websocket start up
        self.__selector = selectors.DefaultSelector()
        self.__selector.register(self.__socket, selectors.EVENT_READ)
        self.__selector.register(self.__cmd_queue, selectors.EVENT_READ)
        self.state = ConnectionState.OPEN
        with _websocket_instances_lock:
            _websocket_instances.add(self)
        self._trigger_lifecycle_event(LifecycleEvent.OPEN)

    # ------------------------------------------------------
    # PUBLIC METHODS
    # ------------------------------------------------------

    def get_messages(self):
        while self.state is not ConnectionState.CLOSED:
            try:
                readables = {
                    selector_key[0].fileobj
                    for selector_key in self.__selector.select(TimeoutManager.TIMEOUT)
                }
                if (
                    self._timeout_manager.has_keep_alive_timed_out()
                    and self.state is ConnectionState.OPEN
                ):
                    self._disconnect(CloseCode.KEEP_ALIVE_TIMEOUT)
                    continue
                if self._timeout_manager.has_frame_response_timed_out():
                    self._terminate()
                    continue
                if not readables and self._timeout_manager.should_send_ping_frame():
                    self._send_ping_frame()
                    continue
                if self.__cmd_queue in readables:
                    cmd, _, data = self.__cmd_queue.get_nowait()
                    self._process_control_command(cmd, data)
                    if self.state is ConnectionState.CLOSED:
                        continue
                if self.__socket in readables:
                    message = self._process_next_message()
                    if message is not None:
                        yield message
            except Exception as exc:
                self._handle_transport_error(exc)

    def close(self, code, reason=None):
        """Notify the socket to initiate closure. The closing handshake
        will start in the subsequent iteration of the event loop.

        Callers may race with the serving thread terminating the
        connection (which closes the command queue): a close request for
        an already-terminated socket is a no-op, not an error.
        """
        with suppress(OSError):
            self._send_control_command(
                ControlCommand.CLOSE, {"code": code, "reason": reason}
            )

    @classmethod
    def onopen(cls, func):
        cls.__event_callbacks[LifecycleEvent.OPEN].add(func)
        return func

    @classmethod
    def onclose(cls, func):
        cls.__event_callbacks[LifecycleEvent.CLOSE].add(func)
        return func

    def subscribe(self, channels, last):
        """Subscribe to bus channels."""
        self._channels = channels
        # Force a session re-validation on the next dispatch: a (re)subscribe
        # is the natural point where the session may just have changed.
        self._session_validated_until = 0.0
        # Only assign the last id according to the client once: the server is
        # more reliable later on, see ``MAX_NOTIFICATION_HISTORY_SEC``.
        self._dispatch_state.initialize_last_id(last)
        # Dispatch past notifications if there are any.
        self.trigger_notification_dispatching()

    def trigger_notification_dispatching(self):
        """
        Warn the socket that notifications are available. Ignore if a
        dispatch is already planned or if the socket is already in the
        closing state.
        """
        if self.state is not ConnectionState.OPEN or self._waiting_for_dispatch:
            return
        self._waiting_for_dispatch = True
        # Ignore if the socket was closed in the meantime.
        with suppress(OSError):
            self._send_control_command(ControlCommand.DISPATCH)

    # ------------------------------------------------------
    # PRIVATE METHODS
    # ------------------------------------------------------

    def _get_next_frame(self):
        #     0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
        #    +-+-+-+-+-------+-+-------------+-------------------------------+
        #    |F|R|R|R| opcode|M| Payload len |    Extended payload length    |
        #    |I|S|S|S|  (4)  |A|     (7)     |             (16/64)           |
        #    |N|V|V|V|       |S|             |   (if payload len==126/127)   |
        #    | |1|2|3|       |K|             |                               |
        #    +-+-+-+-+-------+-+-------------+ - - - - - - - - - - - - - - - +
        #    |     Extended payload length continued, if payload len == 127  |
        #    + - - - - - - - - - - - - - - - +-------------------------------+
        #    |                               |Masking-key, if MASK set to 1  |
        #    +-------------------------------+-------------------------------+
        #    | Masking-key (continued)       |          Payload Data         |
        #    +-------------------------------- - - - - - - - - - - - - - - - +
        #    :                     Payload Data continued ...                :
        #    + - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - +
        #    |                     Payload Data continued ...                |
        #    +---------------------------------------------------------------+
        def recv_bytes(n):
            """Pull n bytes from the socket"""
            data = bytearray()
            while len(data) < n:
                received_data = self.__socket.recv(n - len(data))
                if not received_data:
                    raise ConnectionClosedError
                data.extend(received_data)
            return data

        def is_bit_set(byte, n):
            """
            Check whether nth bit of byte is set or not (from left
            to right).
            """
            return byte & (1 << (7 - n))

        def apply_mask(payload, mask):
            # see: https://www.willmcgugan.com/blog/tech/post/speeding-up-websockets-60x/
            a, b, c, d = (_XOR_TABLE[n] for n in mask)
            payload[::4] = payload[::4].translate(a)
            payload[1::4] = payload[1::4].translate(b)
            payload[2::4] = payload[2::4].translate(c)
            payload[3::4] = payload[3::4].translate(d)
            return payload

        first_byte, second_byte = recv_bytes(2)
        fin, rsv1, rsv2, rsv3 = (is_bit_set(first_byte, n) for n in range(4))
        try:
            opcode = Opcode(first_byte & 0b00001111)
        except ValueError as exc:
            raise ProtocolError(exc) from exc
        self._limit_rate(opcode)
        payload_length = second_byte & 0b01111111

        if rsv1 or rsv2 or rsv3:
            raise ProtocolError("Reserved bits must be unset")
        if not is_bit_set(second_byte, 0):
            raise ProtocolError("Frame must be masked")
        if opcode in CTRL_OP:
            if not fin:
                raise ProtocolError("Control frames cannot be fragmented")
            if payload_length > 125:
                raise ProtocolError("Control frames payload must be smaller than 126")
        if payload_length == 126:
            payload_length = struct.unpack("!H", recv_bytes(2))[0]
        elif payload_length == 127:
            payload_length = struct.unpack("!Q", recv_bytes(8))[0]
        if payload_length > self.MESSAGE_MAX_SIZE:
            raise PayloadTooLargeError

        mask = recv_bytes(4)
        payload = apply_mask(recv_bytes(payload_length), mask)
        frame = Frame(opcode, bytes(payload), fin, rsv1, rsv2, rsv3)
        self._timeout_manager.acknowledge_frame_receipt(frame)
        return frame

    def _process_next_message(self):
        """
        Process the next message coming through the socket. If a
        data message can be extracted, return its decoded payload.
        As per the RFC, only control frames will be processed once
        the connection reaches the closing state.
        """
        frame = self._get_next_frame()
        if frame.opcode in CTRL_OP:
            self._handle_control_frame(frame)
            return None
        if self.state is not ConnectionState.OPEN:
            # After receiving a control frame indicating the connection
            # should be closed, a peer discards any further data
            # received.
            return None
        if frame.opcode is Opcode.CONTINUE:
            raise ProtocolError("Unexpected continuation frame")
        message = frame.payload
        if not frame.fin:
            message = self._recover_fragmented_message(frame)
        return (
            message.decode("utf-8")
            if message is not None and frame.opcode is Opcode.TEXT
            else message
        )

    def _recover_fragmented_message(self, initial_frame):
        message_fragments = bytearray(initial_frame.payload)
        while True:
            frame = self._get_next_frame()
            if frame.opcode in CTRL_OP:
                # Control frames can be received in the middle of a
                # fragmented message, process them as soon as possible.
                self._handle_control_frame(frame)
                if self.state is not ConnectionState.OPEN:
                    return None
                continue
            if frame.opcode is not Opcode.CONTINUE:
                raise ProtocolError("A continuation frame was expected")
            message_fragments.extend(frame.payload)
            if len(message_fragments) > self.MESSAGE_MAX_SIZE:
                raise PayloadTooLargeError
            if frame.fin:
                return bytes(message_fragments)

    def _send(self, message):
        if self.state is not ConnectionState.OPEN:
            raise InvalidStateError("Trying to send a frame on a closed socket")
        opcode = Opcode.BINARY
        if not isinstance(message, (bytes, bytearray)):
            opcode = Opcode.TEXT
        self._send_frame(Frame(opcode, message))

    def _send_frame(self, frame):
        if frame.opcode in CTRL_OP and len(frame.payload) > 125:
            raise ProtocolError(
                "Control frames should have a payload length smaller than 126"
            )
        if isinstance(frame.payload, str):
            frame.payload = frame.payload.encode("utf-8")
        elif not isinstance(frame.payload, (bytes, bytearray)):
            frame.payload = orjson.dumps(frame.payload)

        output = bytearray()
        first_byte = (
            (0b10000000 if frame.fin else 0)
            | (0b01000000 if frame.rsv1 else 0)
            | (0b00100000 if frame.rsv2 else 0)
            | (0b00010000 if frame.rsv3 else 0)
            | frame.opcode
        )
        payload_length = len(frame.payload)
        if payload_length < 126:
            output.extend(struct.pack("!BB", first_byte, payload_length))
        elif payload_length < 65536:
            output.extend(struct.pack("!BBH", first_byte, 126, payload_length))
        else:
            output.extend(struct.pack("!BBQ", first_byte, 127, payload_length))
        output.extend(frame.payload)
        self.__socket.sendall(output)
        self._timeout_manager.acknowledge_frame_sent(frame)
        if not isinstance(frame, CloseFrame):
            return
        self.state = ConnectionState.CLOSING
        self._close_sent = True
        if (
            frame.code in (CloseCode.ABNORMAL_CLOSURE, CloseCode.KILL_NOW)
            or self._close_received
        ):
            self._terminate()
            return
        # After sending a control frame indicating the connection
        # should be closed, a peer does not send any further data.
        self.__selector.unregister(self.__cmd_queue)

    def _send_close_frame(self, code, reason=None):
        """Send a close frame."""
        self._send_frame(CloseFrame(code, reason))

    def _send_ping_frame(self):
        """Send a ping frame"""
        self._send_frame(Frame(Opcode.PING))

    def _send_pong_frame(self, payload):
        """Send a pong frame"""
        self._send_frame(Frame(Opcode.PONG, payload))

    def _disconnect(self, code, reason=None):
        """Initiate the closing handshake. Once the acknowledgment is received,
        `self._terminate` will be invoked to execute a graceful shutdown of the
        TCP connection. If the connection is already dead, skip the handshake
        and terminate immediately. This is a low level method, meant to be
        called from the WebSocket event loop. To close the connection, use
        `self.close`.
        """
        if code in (CloseCode.ABNORMAL_CLOSURE, CloseCode.KILL_NOW):
            self._terminate()
        else:
            self._send_close_frame(code, reason)

    def _terminate(self):
        """Close the underlying TCP socket."""
        if self.state == ConnectionState.CLOSED:
            return
        self.state = ConnectionState.CLOSED
        # Unsubscribe before the socket/selector teardown: an unexpected
        # exception below must not leave this websocket registered in
        # ``ImDispatch._channels_to_ws`` (dispatch-to-dead-socket leak).
        dispatch.unsubscribe(self)
        with suppress(OSError, TimeoutError):
            self.__socket.shutdown(socket.SHUT_WR)
            # Call recv until obtaining a return value of 0 indicating
            # the other end has performed an orderly shutdown. A timeout
            # is set to ensure the connection will be closed even if
            # the other end does not close the socket properly.
            self.__socket.settimeout(1)
            # The per-recv timeout does not bound the drain as a whole: a
            # peer that keeps streaming after our shutdown would keep this
            # loop (and the serving thread) alive indefinitely. Give the
            # orderly-shutdown wait a hard deadline and cut the connection
            # loose past it.
            drain_deadline = time.monotonic() + 5
            while self.__socket.recv(4096):
                if time.monotonic() > drain_deadline:
                    break
        with suppress(KeyError):
            self.__selector.unregister(self.__socket)
        with suppress(OSError):
            self.__selector.close()
        with suppress(OSError):
            self.__socket.close()
        with suppress(OSError):
            self.__cmd_queue.close()
        # Application-level teardown (CLOSE callbacks and the ir.websocket
        # `_on_websocket_closed` hook) is best-effort: it acquires a cursor and
        # may raise — most notably ``PoolError`` under connection-pool
        # exhaustion, exactly when many sockets terminate at once. Such a
        # failure must not escape ``_terminate``: doing so would propagate out
        # of the event loop (killing the serving thread) and, more importantly,
        # skip ``_on_websocket_closed`` inconsistently (leaving e.g. presence
        # state stale). The socket/selector are already closed above, so it is
        # safe to swallow and log here.
        try:
            self._trigger_lifecycle_event(LifecycleEvent.CLOSE)
            with acquire_cursor(self._db) as cr:
                env = self.new_env(cr, self._session)
                env["ir.websocket"]._on_websocket_closed(self._cookies)
        except Exception:
            _logger.warning("Error during websocket teardown cleanup", exc_info=True)

    def _handle_control_frame(self, frame):
        if frame.opcode is Opcode.PING:
            self._send_pong_frame(frame.payload)
        elif frame.opcode is Opcode.CLOSE:
            self.state = ConnectionState.CLOSING
            self._close_received = True
            code, reason = CloseCode.CLEAN, None
            if len(frame.payload) >= 2:
                code = struct.unpack("!H", frame.payload[:2])[0]
                if code not in VALID_CLOSE_CODES and code not in RESERVED_CLOSE_CODES:
                    # RFC 6455 §7.4: 1005/1006/1015, codes below 1000 and
                    # unassigned codes must not appear on the wire. Echoing
                    # them back would itself be a protocol violation (and
                    # raise InvalidCloseCodeError); answer PROTOCOL_ERROR.
                    code, reason = CloseCode.PROTOCOL_ERROR, "Invalid close code"
                else:
                    try:
                        reason = frame.payload[2:].decode("utf-8")
                    except UnicodeDecodeError:
                        # RFC 6455 §5.5.1: the close reason must be UTF-8.
                        code = CloseCode.INCONSISTENT_DATA
                        reason = "Malformed close reason"
            elif frame.payload:
                # RFC 6455 §5.5.1: a 1-byte close payload is malformed (the
                # close code alone takes two bytes).
                code, reason = CloseCode.PROTOCOL_ERROR, "Malformed closing frame"
            if not self._close_sent:
                self._send_close_frame(code, reason)
            else:
                self._terminate()

    def _handle_transport_error(self, exc):
        """
        Find out which close code should be sent according to given
        exception and call `self._disconnect` in order to close the
        connection cleanly.
        """
        code, reason = CloseCode.SERVER_ERROR, str(exc)
        if isinstance(exc, (ConnectionClosedError, OSError)):
            code = CloseCode.ABNORMAL_CLOSURE
        elif isinstance(exc, (ProtocolError, InvalidCloseCodeError)):
            code = CloseCode.PROTOCOL_ERROR
        elif isinstance(exc, UnicodeDecodeError):
            code = CloseCode.INCONSISTENT_DATA
        elif isinstance(exc, PayloadTooLargeError):
            code = CloseCode.MESSAGE_TOO_BIG
        elif isinstance(exc, (PoolError, RateLimitExceededError)):
            code = CloseCode.TRY_LATER
        elif isinstance(exc, SessionExpiredException):
            code = CloseCode.SESSION_EXPIRED
        if code is CloseCode.SERVER_ERROR:
            reason = None
            try:
                registry = Registry(self._session.db)
                sequence = registry.registry_sequence
                registry = registry.check_signaling()
                registry_reloaded = sequence != registry.registry_sequence
            except Exception:
                # Loading the registry itself can fail (database dropped,
                # connection refused, ...). This method runs inside the event
                # loop's exception handler: letting a second exception escape
                # would kill the serving thread without `_terminate`, leaking
                # the channel registrations in `ImDispatch`.
                registry_reloaded = False
            if registry_reloaded:
                _logger.warning("Bus operation aborted; registry has been reloaded")
            else:
                _logger.exception("Unhandled exception in websocket handler")
        if self.state is ConnectionState.OPEN:
            try:
                self._disconnect(code, reason)
            except Exception:
                # Emitting the close frame writes to the socket and can fail
                # (e.g. BrokenPipeError) precisely when the peer misbehaved and
                # then vanished -- the common trigger for a non-abnormal
                # transport error. This handler runs *outside* the ``get_messages``
                # try/except, so an escape here would propagate out of the event
                # loop, kill the serving thread and skip ``_terminate`` -- leaving
                # the websocket registered in ``ImDispatch._channels_to_ws`` (a
                # dispatch-to-dead-socket leak) and ``_on_websocket_closed``
                # uncalled. Fall back to a hard close, which is idempotent.
                _logger.debug("Failed to emit close frame, terminating", exc_info=True)
                self._terminate()
        else:
            self._terminate()

    def _limit_rate(self, opcode):
        """
        This method is a simple rate limiter designed not to allow
        more than one message by `RL_DELAY` seconds. `RL_BURST` specify
        how many messages can be made in excess of the given rate at the
        beginning. When messages are received too fast, raises the
        `RateLimitExceededError`.

        Only data frames that *begin* a message (TEXT/BINARY) count against
        that budget: continuation frames of a fragmented message and control
        frames (PING/PONG/CLOSE) are accounted separately against a
        ``RL_CONTROL_FACTOR`` times larger budget, so well-behaved clients
        are not disconnected for fragmenting or answering PINGs while a
        control-frame flood still cannot bypass rate limiting.
        """
        if opcode in DATA_OP:
            timestamps = self._incoming_frame_timestamps
            delay = self.RL_DELAY
        else:
            timestamps = self._incoming_control_frame_timestamps
            delay = self.RL_DELAY / self.RL_CONTROL_FACTOR
        now = time.monotonic()
        if (
            len(timestamps) == timestamps.maxlen
            and now - timestamps[0] < delay * timestamps.maxlen
        ):
            raise RateLimitExceededError
        timestamps.append(now)

    def _trigger_lifecycle_event(self, event_type):
        """
        Trigger a lifecycle event that is, call every function
        registered for this event type. Every callback is given both the
        environment and the related websocket.
        """
        if not self.__event_callbacks[event_type]:
            return
        with acquire_cursor(self._db) as cr:
            env = self.new_env(cr, self._session, set_lang=True)
            for callback in self.__event_callbacks[event_type]:
                try:
                    retrying(functools.partial(callback, env, self), env)
                except Exception:
                    _logger.warning(
                        "Error during Websocket %s callback",
                        LifecycleEvent(event_type).name,
                        exc_info=True,
                    )

    def _send_control_command(self, command, data=None):
        """Send a command to the websocket event loop.

        :param ControlCommand command: The command to be executed.
        :param dict | None data: An optional dictionary of parameters.
        """
        self.__cmd_queue.put((command, next(_command_uid), data))

    def _process_control_command(self, command, data):
        """Process a command received in `self.__cmd_queue`.

        :param ControlCommand command: The command to be executed. This key is required.
        :param dict | None data: An optional dictionary of parameters.
        """
        match command:
            case ControlCommand.DISPATCH:
                self._dispatch_bus_notifications()
            case ControlCommand.CLOSE:
                self._disconnect(data["code"], data.get("reason"))

    def _dispatch_bus_notifications(self):
        """
        Dispatch notifications related to the registered channels. If
        the session is expired, close the connection with the
        `SESSION_EXPIRED` close code. If no cursor can be acquired,
        close the connection with the `TRY_LATER` close code.

        The session-store read and the ``check_session`` HMAC check are
        cached for ``SESSION_VALIDITY_TTL`` seconds: an expired/logged-out
        session is still disconnected, at worst one TTL after invalidation
        (see ``SESSION_VALIDITY_TTL`` for the trade-off).
        """
        now = time.monotonic()
        must_validate = (
            now >= self._session_validated_until
            or self._session.sid != self._validated_session_sid
        )
        if must_validate:
            self._session = _follow_session_chain(self._session)
        session = self._session
        # Mark the notification request as processed.
        self._waiting_for_dispatch = False
        with acquire_cursor(session.db) as cr:
            env = self.new_env(cr, session)
            if must_validate:
                if session.uid is not None and not check_session(session, env):
                    raise SessionExpiredException
                self._session_validated_until = now + self.SESSION_VALIDITY_TTL
                self._validated_session_sid = session.sid
            notifications = env["bus.bus"]._poll(
                self._channels,
                self._dispatch_state.last_id,
                self._dispatch_state.ignore_ids,
            )
        if not notifications:
            return
        self._dispatch_state.record_dispatched([notif["id"] for notif in notifications])
        self._send(notifications)

    def new_env(self, cr, session, *, set_lang=False):
        """
        Create a new environment.
        Make sure the transaction has a `default_env` and if requested, set the
        language of the user in the context.
        """
        uid = session.uid
        # lang is not guaranteed to be correct, set None
        ctx = dict(session.context, lang=None)
        env = api.Environment(cr, uid, ctx)
        if set_lang:
            lang = env["res.lang"]._get_code(ctx["lang"])
            env = env(context=dict(ctx, lang=lang))
        if not env.transaction.default_env:
            env.transaction.default_env = env
        return env


class TimeoutManager:
    """
    Track WebSocket activity to determine when a response has timed out,
    when a ping should be sent, and when the connection has exceeded its
    keep-alive duration.
    """

    TIMEOUT = 15
    # Timeout specifying how many seconds the connection should be kept
    # alive.
    KEEP_ALIVE_TIMEOUT = int(config["websocket_keep_alive_timeout"])
    # Proxies and NATs usually close a connection after 1 minute of inactivity.
    # Therefore, a PING frame should be sent if the connection has been idle for
    # a while. Since the selector can block for up to `TIMEOUT` seconds, the
    # worst case delay is 55 seconds (`INACTIVITY_TIMEOUT` + `TIMEOUT`), which
    # is enough to keep the connection alive.
    CONNECTION_TIMEOUT = 60
    INACTIVITY_TIMEOUT = CONNECTION_TIMEOUT - 20

    def __init__(self, clock=None):
        super().__init__()
        # Injectable clock (unit tests). Monotonic by default: a backward
        # NTP step must not stall keep-alive/ping bookkeeping.
        self._clock = clock if clock is not None else time.monotonic
        # Maps an awaited response opcode (i.e. PONG, CLOSE) to the
        # time by which the response must be received.
        self._expiration_time_by_opcode = {}
        # Custom keep alive timeout for each TimeoutManager to avoid multiple
        # connections timing out at the same time.
        self._keep_alive_timeout = self.KEEP_ALIVE_TIMEOUT + random.uniform(
            0, self.KEEP_ALIVE_TIMEOUT / 2
        )
        now = self._clock()
        self._keep_alive_expiration_time = now + self._keep_alive_timeout
        self._next_ping_time = now + self.INACTIVITY_TIMEOUT

    def acknowledge_frame_receipt(self, frame):
        self._next_ping_time = self._clock() + self.INACTIVITY_TIMEOUT
        self._expiration_time_by_opcode.pop(frame.opcode, None)

    def acknowledge_frame_sent(self, frame):
        """
        Acknowledge a frame was sent. If this frame is a PING/CLOSE
        frame, start waiting for an answer.
        """
        now = self._clock()
        self._next_ping_time = now + self.INACTIVITY_TIMEOUT
        if frame.opcode in (Opcode.PING, Opcode.CLOSE):
            self._expiration_time_by_opcode[
                Opcode.PONG if frame.opcode is Opcode.PING else Opcode.CLOSE
            ] = now + self.TIMEOUT

    def has_keep_alive_timed_out(self):
        return self._clock() >= self._keep_alive_expiration_time

    def has_frame_response_timed_out(self):
        """
        Check if any pending PING or CLOSE frame has been waiting for an answer
        for at least `TIMEOUT` seconds.
        """
        now = self._clock()
        return any(
            now >= expiration for expiration in self._expiration_time_by_opcode.values()
        )

    def should_send_ping_frame(self):
        return (
            not self.has_frame_response_timed_out()
            and not self.has_keep_alive_timed_out()
            and self._clock() >= self._next_ping_time
        )


# ------------------------------------------------------
# WEBSOCKET SERVING
# ------------------------------------------------------


def _follow_session_chain(initial_session):
    """Resolve a session, following ``next_sid`` rotation chains.

    Returns the final (non-rotated) session.  Raises
    :class:`~odoo.http.SessionExpiredException` if any session in the
    chain is missing or if the chain exceeds 10 hops (which indicates a
    bug or circular rotation).
    """
    session = root.session_store.get(initial_session.sid)
    for _ in range(10):
        if not session:
            raise SessionExpiredException
        if "next_sid" not in session:
            return session
        session = root.session_store.get(session["next_sid"])
    raise SessionExpiredException


_wsrequest_stack = LocalStack()
wsrequest = _wsrequest_stack()


class WebsocketRequest:
    def __init__(self, db, httprequest, websocket):
        self.db = db
        self.httprequest = httprequest
        self.session = None
        self.ws = websocket
        # Assigned by ``serve_websocket_message``; initialized here so that
        # accessors used before a message is served (e.g. the ``cookies``
        # cached_property via ``wsrequest``) don't hit an AttributeError.
        self.registry = None

    def __enter__(self):
        _wsrequest_stack.push(self)
        return self

    def __exit__(self, *args):
        _wsrequest_stack.pop()

    def serve_websocket_message(self, message):
        try:
            jsonrequest = orjson.loads(message)
            if not isinstance(jsonrequest, dict):
                # A top-level scalar/list would raise TypeError below and land
                # in the generic exception-with-traceback handler; reject it on
                # the same quiet path as any other client-controlled garbage.
                raise InvalidWebsocketRequestError(
                    "Websocket request must be a JSON object"
                )
            event_name = jsonrequest["event_name"]  # mandatory
        except KeyError as exc:
            raise InvalidWebsocketRequestError(
                f"Key {exc.args[0]!r} is missing from request"
            ) from exc
        except ValueError as exc:
            raise InvalidWebsocketRequestError(
                f"Invalid JSON data, {exc.args[0]}"
            ) from exc
        data = jsonrequest.get("data")
        self.session = self._get_session()

        try:
            self.registry = Registry(self.db)
            threading.current_thread().dbname = self.registry.db_name
            self.registry.check_signaling()
        except (
            AttributeError,
            psycopg.OperationalError,
            psycopg.ProgrammingError,
        ) as exc:
            raise InvalidDatabaseError from exc

        with acquire_cursor(self.db) as cr:
            self.env = self.ws.new_env(cr, self.session, set_lang=True)
            retrying(
                functools.partial(self._serve_ir_websocket, event_name, data),
                self.env,
            )

    def _serve_ir_websocket(self, event_name, data):
        """Process websocket events, in particular authenticate and subscribe, and delegate extra
        processing to the ir.websocket model which is extensible by applications."""
        self.env["ir.websocket"]._authenticate()
        if event_name == "subscribe":
            self.env["ir.websocket"]._subscribe(data)
        self.env["ir.websocket"]._serve_ir_websocket(event_name, data)

    def _get_session(self):
        """Return the current session, following at most 10 next_sid hops."""
        session = _follow_session_chain(self.ws._session)
        self.ws._session = session
        return session

    def update_env(self, user=None, context=None, su=None):
        """
        Update the environment of the current websocket request.
        """
        Request.update_env(self, user, context, su)

    def update_context(self, **overrides):
        """
        Override the environment context of the current request with the
        values of ``overrides``. To replace the entire context, please
        use :meth:`~update_env` instead.
        """
        self.update_env(context=dict(self.env.context, **overrides))

    @functools.cached_property
    def cookies(self):
        cookies = MultiDict(self.httprequest.cookies)
        if self.registry:
            self.registry["ir.http"]._sanitize_cookies(cookies)
        return ImmutableMultiDict(cookies)


class WebsocketConnectionHandler:
    SUPPORTED_VERSIONS = {"13"}
    # Given by the RFC in order to generate Sec-WebSocket-Accept from
    # Sec-WebSocket-Key value.
    _HANDSHAKE_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
    _REQUIRED_HANDSHAKE_HEADERS = {
        "connection",
        "host",
        "sec-websocket-key",
        "sec-websocket-version",
        "upgrade",
        "origin",
    }
    # Latest version of the websocket worker. This version should be incremented
    # every time `websocket_worker.js` is modified to force the browser to fetch
    # the new worker bundle.
    _VERSION = "19.0-5"

    @classmethod
    def websocket_allowed(cls, request):
        # WebSockets are disabled during tests because the test environment and
        # the WebSocket thread use the same cursor, leading to race conditions.
        # However, they are enabled during tours as RPC requests and WebSocket
        # instances both use the `TestCursor` class wich is locked.
        # See `HttpCase@browser_js`.
        return not modules.module.current_test

    @classmethod
    def open_connection(cls, request, version):
        """
        Open a websocket connection if the handshake is successful.
        :return: Response indicating the server performed a connection
        upgrade.
        :raise: UpgradeRequired if there is no intersection between the
        versions the client supports and those we support.
        :raise: BadRequest if the handshake data is incorrect.
        """
        if not cls.websocket_allowed(request):
            raise ServiceUnavailable("Websocket is disabled in test mode")
        try:
            response = cls._get_handshake_response(request.httprequest.headers)
            socket = request.httprequest.raw_environ["socket"]
            # Only create (and persist) a downgraded public session once the
            # handshake was validated and the socket is available: doing it
            # earlier left orphaned session records behind every malformed
            # handshake.
            public_session = cls._handle_public_configuration(request)
            session, db, httprequest = (
                (public_session or request.session),
                request.db,
                request.httprequest,
            )
            response.call_on_close(
                lambda: cls._serve_forever(
                    Websocket(socket, session, httprequest.cookies),
                    db,
                    httprequest,
                    version,
                )
            )
            # Force save the session. Session must be persisted to handle
            # WebSocket authentication.
            request.session.is_dirty = True
            return response
        except KeyError as err:
            raise ServiceUnavailable(
                "Websocket unavailable on this port. Use the evented service port."
            ) from err
        except HTTPException as exc:
            # The HTTP stack does not log exceptions derivated from the
            # HTTPException class since they are valid responses.
            _logger.error(exc)
            raise

    @classmethod
    def _get_handshake_response(cls, headers):
        """
        :return: Response indicating the server performed a connection
        upgrade.
        :raise: BadRequest
        :raise: UpgradeRequired
        """
        cls._assert_handshake_validity(headers)
        # sha-1 is used as it is required by
        # https://datatracker.ietf.org/doc/html/rfc6455#page-7
        accept_header = hashlib.sha1(
            (headers["sec-websocket-key"] + cls._HANDSHAKE_GUID).encode()
        ).digest()
        accept_header = base64.b64encode(accept_header)
        return Response(
            status=101,
            headers={
                "Upgrade": "websocket",
                "Connection": "Upgrade",
                "Sec-WebSocket-Accept": accept_header.decode(),
            },
        )

    @classmethod
    def _handle_public_configuration(cls, request):
        """Guard against cross-site WebSocket hijacking (CSWSH).

        Browsers do not apply the same-origin policy to WebSocket
        handshakes: any web page may open a websocket to this server and
        the browser attaches the session cookie (subject only to its
        SameSite policy). When the ``Origin`` header does not match the
        request host, downgrade the connection to a brand new public
        (unauthenticated) session so a cross-site page cannot act with the
        victim's session. Deployments that legitimately serve websockets
        cross-origin can allow specific origins through the
        ``ODOO_BUS_TRUSTED_ORIGINS`` environment variable (see the module
        docstring).

        :return: the public session to use instead of the request's one,
            or ``None`` when the origin is trusted.
        """
        origin = request.httprequest.headers.get("origin", "")
        if cls._is_trusted_origin(origin, request):
            return None
        _logger.warning(
            "Downgrading websocket session. Host=%(host)s, Origin=%(origin)s, "
            "Scheme=%(scheme)s.",
            {
                "host": request.httprequest.host,
                "origin": origin,
                "scheme": request.httprequest.scheme,
            },
        )
        session = root.session_store.new()
        session.update(get_default_session(), db=request.session.db)
        root.session_store.save(session)
        return session

    @staticmethod
    def _normalize_origin(origin):
        """Normalize an origin string to ``scheme://netloc`` (lowercase,
        default ports stripped) for comparison purposes."""
        url = urlparse(origin.strip())
        scheme = url.scheme.lower()
        netloc = url.netloc.lower()
        default_port = {"http": ":80", "https": ":443", "ws": ":80", "wss": ":443"}
        suffix = default_port.get(scheme)
        if suffix and netloc.endswith(suffix):
            netloc = netloc.removesuffix(suffix)
        return f"{scheme}://{netloc}"

    @classmethod
    def _is_trusted_origin(cls, origin, request):
        """Whether the handshake ``Origin`` is the request host itself or an
        explicitly allowlisted origin (``ODOO_BUS_TRUSTED_ORIGINS``).

        The expected origin is computed from the request the way
        ``odoo.http`` sees it: under ``proxy_mode`` the ``X-Forwarded-*``
        headers were already folded into the WSGI environ (werkzeug
        ``ProxyFix``, see ``Application._apply_proxy_fix``), so
        ``httprequest.scheme``/``host`` reflect the client-facing origin.
        """
        origin = cls._normalize_origin(origin)
        expected = cls._normalize_origin(
            f"{request.httprequest.scheme}://{request.httprequest.host}"
        )
        if origin == expected:
            return True
        trusted_origins = os.getenv("ODOO_BUS_TRUSTED_ORIGINS", "")
        return origin in {
            cls._normalize_origin(trusted)
            for trusted in trusted_origins.split(",")
            if trusted.strip()
        }

    @classmethod
    def _assert_handshake_validity(cls, headers):
        """
        :raise: UpgradeRequired if there is no intersection between
        the version the client supports and those we support.
        :raise: BadRequest in case of invalid handshake.
        """
        missing_or_empty_headers = {
            header
            for header in cls._REQUIRED_HANDSHAKE_HEADERS
            if header not in headers
        }
        if missing_or_empty_headers:
            raise BadRequest(
                f"""Empty or missing header(s): {", ".join(missing_or_empty_headers)}"""
            )

        if headers["upgrade"].lower() != "websocket":
            raise BadRequest("Invalid upgrade header")
        if "upgrade" not in headers["connection"].lower():
            raise BadRequest("Invalid connection header")
        if headers["sec-websocket-version"] not in cls.SUPPORTED_VERSIONS:
            raise UpgradeRequired

        key = headers["sec-websocket-key"]
        try:
            decoded_key = base64.b64decode(key, validate=True)
        except ValueError as err:
            raise BadRequest("Sec-WebSocket-Key should be b64 encoded") from err
        if len(decoded_key) != 16:
            raise BadRequest("Sec-WebSocket-Key should be of length 16 once decoded")

    @classmethod
    def _serve_forever(cls, websocket, db, httprequest, version):
        """
        Process incoming messages and dispatch them to the application.
        """
        current_thread = threading.current_thread()
        current_thread.type = "websocket"
        if httprequest.user_agent and version != cls._VERSION:
            # Close the connection from an outdated worker. We can't use a
            # custom close code because the connection is considered successful,
            # preventing exponential reconnect backoff. This would cause old
            # workers to reconnect frequently, putting pressure on the server.
            # Clean closes don't trigger reconnections, assuming they are
            # intentional. The reason indicates to the origin worker not to
            # reconnect, preventing old workers from lingering after updates.
            # Non browsers are ignored since IOT devices do not provide the
            # worker version.
            websocket.close(CloseCode.CLEAN, "OUTDATED_VERSION")
        for message in websocket.get_messages():
            if message == b"\x00":
                # Ignore internal sentinel message used to detect dead/idle connections.
                continue
            with WebsocketRequest(db, httprequest, websocket) as req:
                try:
                    req.serve_websocket_message(message)
                except SessionExpiredException:
                    websocket.close(CloseCode.SESSION_EXPIRED)
                except PoolError:
                    websocket.close(CloseCode.TRY_LATER)
                except (InvalidWebsocketRequestError, ValueError) as exc:
                    # Client-controlled input (malformed JSON, bad subscribe
                    # payload shape, non-string channels, ...): reject the
                    # message without the log noise of a full traceback --
                    # any anonymous peer can send garbage at will.
                    _logger.warning("Invalid websocket request: %s", exc)
                except Exception:
                    _logger.exception(
                        "Exception occurred during websocket request handling"
                    )


def _kick_all(code=CloseCode.GOING_AWAY):
    """Disconnect all the websocket instances."""
    # Snapshot the WeakSet under the lock shared with ``Websocket.__init__``:
    # serving threads keep opening websockets concurrently and a concurrent
    # ``add`` during the snapshot raises RuntimeError, which would abort the
    # kick for the remaining sockets (GC removals are internally deferred by
    # WeakSet during iteration and are not a hazard).
    with _websocket_instances_lock:
        websockets = list(_websocket_instances)
    for websocket in websockets:
        if websocket.state is ConnectionState.OPEN:
            websocket.close(code)


CommonServer.on_stop(_kick_all)

from __future__ import annotations

import contextlib
import errno
import logging
import os
import selectors
import socket
import sys
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import Enum
from http import HTTPStatus
from typing import Any

from werkzeug.urls import uri_to_iri

from odoo.libs.debug_log import DebugLog
from odoo.libs.http1 import (
    LAST_CHUNK,
    BodyLimits,
    BodyReader,
    BufferedSource,
    ChunkedReader,
    Framing,
    HeadLimits,
    LengthReader,
    ProtocolError,
    RequestHead,
    ResponseHead,
    encode_chunk,
    find_head,
    parse_request_head,
    prepare_response_head,
)
from odoo.libs.worker_thread import as_worker_thread, current_worker_thread

from ._env import get_env_float, get_env_int
from .settings import current

_logger = logging.getLogger("odoo.service.server")
_access_logger = logging.getLogger("odoo.service.http.access")
_debug = DebugLog(__name__)

WSGIApp = Callable[[dict[str, Any], Callable[..., Any]], Iterable[bytes]]

REQUEST_THREAD_PREFIX = "odoo.service.http.request."
IDLE_THREAD_PREFIX = "odoo.service.http.idle."
_SEND_SLICE = 65536
_MAX_PIPELINED = 16
_ACCEPT_BACKOFF = 0.1
_RESOURCE_WARNING_INTERVAL = 60.0
_RESOURCE_ERRNOS = frozenset({errno.EMFILE, errno.ENFILE, errno.ENOBUFS, errno.ENOMEM})
_PEER_GONE = (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)
_CONTROL_CHARS = str.maketrans(
    {c: rf"\x{c:02x}" for c in [*range(0x20), *range(0x7F, 0xA0)]} | {ord("\\"): r"\\"}
)
_MONTHS = (
    "",
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)
_ANSI = {
    "bold": "1",
    "red": "31",
    "green": "32",
    "yellow": "33",
    "magenta": "35",
    "cyan": "36",
}


def get_http_socket_timeout() -> float:
    return get_env_float("ODOO_HTTP_SOCKET_TIMEOUT", 2.0, minimum=0.1, logger=_logger)


@dataclass(frozen=True, slots=True)
class TransportLimits:
    socket_timeout: float
    keepalive_timeout: float
    head_timeout: float
    drain_bytes: int
    drain_seconds: float
    linger_seconds: float
    max_idle_connections: int
    head: HeadLimits = field(default_factory=HeadLimits)
    body: BodyLimits = field(default_factory=BodyLimits)

    @classmethod
    def from_environment(cls) -> TransportLimits:
        timeout = get_http_socket_timeout()
        if current().test_enable:
            timeout = max(timeout, 5.0)
        return cls(
            socket_timeout=timeout,
            keepalive_timeout=get_env_float(
                "ODOO_HTTP_KEEPALIVE_TIMEOUT", 75.0, minimum=0.0, logger=_logger
            ),
            head_timeout=get_env_float(
                "ODOO_HTTP_HEAD_TIMEOUT", 10.0, minimum=0.1, logger=_logger
            ),
            drain_bytes=get_env_int(
                "ODOO_HTTP_DRAIN_BYTES", 1 << 20, minimum=0, logger=_logger
            ),
            drain_seconds=1.0,
            linger_seconds=2.0,
            max_idle_connections=get_env_int(
                "ODOO_HTTP_MAX_IDLE_CONNECTIONS", 4096, minimum=0, logger=_logger
            ),
        )


class Outcome(Enum):
    PERSIST = "persist"
    CLOSE = "close"
    UPGRADED = "upgraded"


class Connection:
    __slots__ = (
        "addr",
        "deadline",
        "head_started",
        "idle_since",
        "ready_at",
        "requests",
        "sock",
        "source",
    )

    def __init__(self, sock: socket.socket, addr: Any) -> None:
        self.sock = sock
        self.addr = addr if isinstance(addr, tuple) else ("<local>", 0)
        self.source = BufferedSource(sock.recv)
        self.deadline = 0.0
        self.head_started = False
        self.idle_since = time.monotonic()
        self.ready_at = self.idle_since
        self.requests = 0

    def send(self, data: bytes) -> None:
        if len(data) <= _SEND_SLICE:
            self.sock.sendall(data)
            return
        view = memoryview(data)
        for offset in range(0, len(view), _SEND_SLICE):
            self.sock.sendall(view[offset : offset + _SEND_SLICE])

    def close(self, *, linger: float = 0.0) -> None:
        with contextlib.suppress(OSError):
            self.sock.shutdown(socket.SHUT_WR)
        if linger > 0:
            deadline = time.monotonic() + linger
            with contextlib.suppress(OSError):
                self.sock.settimeout(linger)
                while time.monotonic() < deadline and self.sock.recv(65536):
                    pass
        with contextlib.suppress(OSError):
            self.sock.close()


def _style(message: str, *styles: str) -> str:
    if not sys.stderr.isatty():
        return message
    codes = ";".join(_ANSI[s] for s in styles)
    return f"\x1b[{codes}m{message}\x1b[0m"


def log_access(
    conn: Connection, request_line: str, raw_path: str, status: int, size: int | str
) -> None:
    message = request_line
    if fragment := getattr(current_worker_thread(), "rpc_model_method", ""):
        target, _, protocol = request_line.rpartition(" ")
        if target and protocol.startswith("HTTP/"):
            message = f"{target}#{fragment} {protocol}"
        else:
            message = f"{request_line}#{fragment}"
    message = message.translate(_CONTROL_CHARS)
    if "/static/" in raw_path and not current().dev_mode:
        level = logging.DEBUG
    else:
        level = logging.INFO
        if status < 200:
            message = _style(message, "bold")
        elif status == 304:
            message = _style(message, "cyan")
        elif 300 <= status < 400:
            message = _style(message, "green")
        elif status == 404:
            message = _style(message, "yellow")
        elif 400 <= status < 500:
            message = _style(message, "bold", "red")
        elif status >= 500:
            message = _style(message, "bold", "magenta")
    if _access_logger.isEnabledFor(level):
        now = time.localtime()
        stamp = (
            f"{now.tm_mday:02d}/{_MONTHS[now.tm_mon]}/{now.tm_year:04d} "
            f"{now.tm_hour:02d}:{now.tm_min:02d}:{now.tm_sec:02d}"
        )
        # Record args are werkzeug's (request line, status, size): access-log filters
        # match on args[0], and an IPv6 zone id carries a literal %.
        address = str(conn.addr[0]).replace("%", "%%")
        template = address + " - - [" + stamp + '] "%s" %s %s'
        _access_logger.log(level, template, message, status, size)


def _reset_request_attributes() -> None:
    worker = current_worker_thread()
    worker.rpc_model_method = ""
    if hasattr(worker, "query_count"):
        del worker.query_count


@dataclass(frozen=True, slots=True)
class ServerIdentity:
    name: str
    port: int
    multithread: bool
    multiprocess: bool
    exposes_socket: bool


def build_environ(
    head: RequestHead,
    conn: Connection,
    reader: BodyReader,
    identity: ServerIdentity,
) -> dict[str, Any]:
    environ: dict[str, Any] = {
        "wsgi.version": (1, 0),
        "wsgi.url_scheme": "http",
        "wsgi.input": reader,
        "wsgi.errors": sys.stderr,
        "wsgi.multithread": identity.multithread,
        "wsgi.multiprocess": identity.multiprocess,
        "wsgi.run_once": False,
        "SERVER_SOFTWARE": "Odoo",
        "REQUEST_METHOD": head.method,
        "SCRIPT_NAME": "",
        "PATH_INFO": head.path,
        "QUERY_STRING": head.query,
        "REQUEST_URI": head.target,
        "RAW_URI": head.target,
        "REMOTE_ADDR": conn.addr[0],
        "REMOTE_PORT": conn.addr[1],
        "SERVER_NAME": identity.name,
        "SERVER_PORT": str(identity.port),
        "SERVER_PROTOCOL": head.protocol,
    }
    for name, value in head.headers:
        if "_" in name:
            continue
        key = name.upper().replace("-", "_")
        if key == "CONTENT_LENGTH":
            if head.chunked:
                continue
        elif key != "CONTENT_TYPE":
            key = f"HTTP_{key}"
            if key in environ:
                value = f"{environ[key]},{value}"
        environ[key] = value
    if identity.exposes_socket:
        environ["socket"] = conn.sock
    if head.host is not None:
        environ["HTTP_HOST"] = head.host
    if head.chunked:
        environ["wsgi.input_terminated"] = True
    return environ


class Exchange:
    __slots__ = (
        "bytes_sent",
        "conn",
        "head",
        "keep_alive",
        "reader",
        "response",
        "response_headers",
        "status",
        "upgraded",
    )

    def __init__(
        self, conn: Connection, head: RequestHead, *, keep_alive: bool
    ) -> None:
        self.conn = conn
        self.head = head
        self.keep_alive = keep_alive
        self.reader: BodyReader = LengthReader(conn.source, 0)
        self.status: str | None = None
        self.response_headers: list[tuple[str, str]] = []
        self.response: ResponseHead | None = None
        self.bytes_sent = 0
        self.upgraded = False

    def start_response(
        self,
        status: str,
        headers: list[tuple[str, str]],
        exc_info: Any = None,
    ) -> Callable[[bytes], None]:
        if exc_info is not None:
            try:
                if self.response is not None:
                    raise exc_info[1].with_traceback(exc_info[2])
            finally:
                exc_info = None
        elif self.status is not None:
            raise AssertionError("start_response called twice without exc_info")
        self.status = status
        self.response_headers = list(headers)
        return self.write

    def continue_upload(self) -> None:
        if self.response is None:
            self.conn.send(b"HTTP/1.1 100 Continue\r\n\r\n")

    def _send_head(self, first: bytes) -> None:
        if self.status is None:
            raise AssertionError("write() before start_response")
        self.response = prepare_response_head(
            self.status,
            self.response_headers,
            method=self.head.method,
            version=self.head.version,
            keep_alive=self.keep_alive,
        )
        if self.response.code == 101:
            self.upgraded = True
            self.conn.sock.settimeout(None)
        _log_exchange(self)
        self.conn.send(self.response.data + self._frame(first))

    def _frame(self, data: bytes) -> bytes:
        response = self.response
        assert response is not None
        if not data or response.framing is Framing.NONE:
            return b""
        if response.framing is Framing.CHUNKED:
            self.bytes_sent += len(data)
            return encode_chunk(data)
        if response.framing is Framing.LENGTH:
            assert response.content_length is not None
            room = response.content_length - self.bytes_sent
            if len(data) > room:
                _logger.warning(
                    "%s %s wrote more than its Content-Length (%s); truncating",
                    self.head.method,
                    self.head.path,
                    response.content_length,
                )
                data = data[: max(room, 0)]
        self.bytes_sent += len(data)
        return data

    def write(self, data: bytes) -> None:
        if self.response is None:
            self._send_head(data)
        elif data := self._frame(data):
            self.conn.send(data)

    def finish(self) -> None:
        if self.response is None:
            self._send_head(b"")
        response = self.response
        assert response is not None
        if response.framing is Framing.CHUNKED:
            self.conn.send(LAST_CHUNK)

    @property
    def complete(self) -> bool:
        response = self.response
        if response is None:
            return False
        if response.framing is Framing.LENGTH:
            return self.bytes_sent == response.content_length
        return response.framing is not Framing.CLOSE


def _error_response(conn: Connection, status: HTTPStatus, detail: str) -> int:
    body = f"{status.value} {status.phrase}: {detail}\n".encode()
    head = prepare_response_head(
        f"{status.value} {status.phrase}",
        [
            ("Content-Type", "text/plain; charset=utf-8"),
            ("Content-Length", str(len(body))),
        ],
        method="GET",
        version=(1, 1),
        keep_alive=False,
    )
    with contextlib.suppress(OSError):
        conn.send(head.data + body)
    return len(body)


def _read_head(conn: Connection, limits: TransportLimits) -> tuple[int, int] | None:
    deadline = time.monotonic() + limits.head_timeout
    scanned = 0
    while (span := find_head(conn.source.buffer, limits.head, scanned)) is None:
        scanned = len(conn.source.buffer)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ProtocolError(
                HTTPStatus.REQUEST_TIMEOUT, "request head not received in time"
            )
        conn.sock.settimeout(min(limits.socket_timeout, remaining))
        if not conn.source.fill():
            return None
    conn.sock.settimeout(limits.socket_timeout)
    return span


def _first_line(buffer: bytearray) -> str:
    line = bytes(buffer[: buffer.find(b"\n")] if b"\n" in buffer else buffer[:200])
    return line.rstrip(b"\r").decode("latin-1")


def serve_one(
    conn: Connection,
    app: WSGIApp,
    identity: ServerIdentity,
    limits: TransportLimits,
    *,
    allow_keep_alive: bool,
) -> Outcome:
    try:
        span = _read_head(conn, limits)
        if span is None:
            return Outcome.CLOSE
        head = parse_request_head(
            bytes(conn.source.buffer[span[0] : span[1]]), limits.head
        )
    except ProtocolError as exc:
        _reset_request_attributes()
        line = _first_line(conn.source.buffer)
        size = _error_response(conn, exc.status, exc.detail)
        log_access(conn, line or "-", "", exc.status.value, size)
        _debug.logic("httpd.protocol_error", status=exc.status.value, detail=exc.detail)
        return Outcome.CLOSE
    except OSError:
        return Outcome.CLOSE
    del conn.source.buffer[: span[1]]
    conn.requests += 1
    return _run_exchange(
        conn, head, app, identity, limits, allow_keep_alive=allow_keep_alive
    )


def _open_reader(
    conn: Connection,
    head: RequestHead,
    limits: TransportLimits,
    exchange: Exchange,
) -> BodyReader:
    on_first_read = exchange.continue_upload if head.expect_continue else None
    if head.chunked:
        return ChunkedReader(conn.source, limits.body, on_first_read)
    return LengthReader(conn.source, head.content_length or 0, on_first_read)


def _run_exchange(
    conn: Connection,
    head: RequestHead,
    app: WSGIApp,
    identity: ServerIdentity,
    limits: TransportLimits,
    *,
    allow_keep_alive: bool,
) -> Outcome:
    exchange = Exchange(
        conn,
        head,
        keep_alive=head.keep_alive and allow_keep_alive and not head.must_close,
    )
    exchange.reader = _open_reader(conn, head, limits, exchange)
    environ = build_environ(head, conn, exchange.reader, identity)
    iterable: Iterable[bytes] | None = None
    try:
        iterable = app(environ, exchange.start_response)
        for data in iterable:
            if data:
                exchange.write(data)
        exchange.finish()
    except (TimeoutError, *_PEER_GONE) as exc:
        _debug.logic("httpd.peer_gone", error=type(exc).__name__, path=head.path)
        _close_iterable(iterable)
        return Outcome.CLOSE
    except Exception:
        _logger.exception(
            "Exception happened during processing of request from %s", conn.addr
        )
        if exchange.response is None:
            exchange.status = None
            size = _error_response(
                conn, HTTPStatus.INTERNAL_SERVER_ERROR, "internal error"
            )
            log_access(
                conn,
                f"{head.method} {head.target} {head.protocol}",
                head.path,
                500,
                size,
            )
        _close_iterable(iterable)
        return Outcome.CLOSE
    if _debug.perf.enabled:
        response = exchange.response
        _debug.perf.count(
            "httpd.exchange",
            ms=(time.monotonic() - conn.ready_at) * 1000.0,
            status=response.code if response else 0,
            request_on_connection=conn.requests,
            path=head.path,
        )
    if exchange.upgraded:
        if conn.source.buffer:
            _debug.logic(
                "httpd.upgrade_with_buffered_bytes",
                bytes=len(conn.source.buffer),
                path=head.path,
            )
        _hand_off_upgrade(conn, iterable)
        return Outcome.UPGRADED
    _close_iterable(iterable)
    return _settle(exchange, limits, allow_keep_alive=allow_keep_alive)


def _log_exchange(exchange: Exchange) -> None:
    head = exchange.head
    try:
        iri = uri_to_iri(head.target)
    except ValueError:
        iri = head.target
    response = exchange.response
    assert response is not None
    size: int | str = "-"
    if response.content_length is not None and response.framing is Framing.LENGTH:
        size = response.content_length
    log_access(
        exchange.conn,
        f"{head.method} {iri} {head.protocol}",
        head.target,
        response.code,
        size,
    )


def _close_iterable(iterable: Iterable[bytes] | None) -> None:
    close = getattr(iterable, "close", None)
    if close is not None:
        try:
            close()
        except Exception:
            _logger.exception("error while closing the response iterable")


def _hand_off_upgrade(conn: Connection, iterable: Iterable[bytes] | None) -> None:
    def run() -> None:
        me = threading.current_thread()
        me.name = f"{REQUEST_THREAD_PREFIX}{me.ident}"
        try:
            _close_iterable(iterable)
        finally:
            conn.close()

    threading.Thread(target=run, daemon=True).start()


def _settle(
    exchange: Exchange, limits: TransportLimits, *, allow_keep_alive: bool
) -> Outcome:
    response = exchange.response
    assert response is not None
    head = exchange.head
    persist = (
        allow_keep_alive
        and response.keep_alive
        and exchange.complete
        and not head.must_close
    )
    reader = exchange.reader
    if reader.exhausted:
        return Outcome.PERSIST if persist else Outcome.CLOSE
    drained = False
    if persist:
        try:
            drained = reader.drain(
                limits.drain_bytes, time.monotonic() + limits.drain_seconds
            )
        except OSError:
            drained = False
    _debug.logic("httpd.body_unread", drained=drained, persist=persist, path=head.path)
    if drained:
        return Outcome.PERSIST
    exchange.conn.close(linger=limits.linger_seconds)
    return Outcome.CLOSE


def serve_prefork_connection(
    sock: socket.socket,
    addr: Any,
    app: WSGIApp,
    identity: ServerIdentity,
    limits: TransportLimits,
) -> None:
    conn = Connection(sock, addr)
    try:
        serve_one(conn, app, identity, limits, allow_keep_alive=False)
    finally:
        conn.close()


def compute_http_thread_limit(settings: Any) -> tuple[int, int]:
    auto_limit = max(
        (settings.db_maxconn - settings.max_cron_threads - settings.job_workers) // 2, 1
    )
    limit = get_env_int("ODOO_MAX_HTTP_THREADS", auto_limit, minimum=0, logger=_logger)
    return limit, auto_limit


def announce_thread_budget(settings: Any, limit: int, auto_limit: int) -> None:
    if not limit:
        _logger.info(
            "HTTP concurrency is unbounded (ODOO_MAX_HTTP_THREADS=0); "
            "in-flight requests are limited only by db_maxconn=%s",
            settings.db_maxconn,
        )
        return
    source = (
        "ODOO_MAX_HTTP_THREADS"
        if limit != auto_limit
        else "(db_maxconn %s - max_cron_threads %s - job_workers %s) // 2"
        % (settings.db_maxconn, settings.max_cron_threads, settings.job_workers)
    )
    log = _logger.warning if limit < 4 else _logger.info
    log(
        "At most %d HTTP request(s) will be served concurrently, from %s. "
        "Further requests wait in the connection queue; set "
        "ODOO_MAX_HTTP_THREADS to decouple this from the pool size.",
        limit,
        source,
    )


class WorkerPool:
    def __init__(
        self,
        limit: int | None,
        target: Callable[[Connection], None],
        on_unsaturated: Callable[[], None] | None = None,
    ) -> None:
        self.limit = limit
        self._target = target
        self._on_unsaturated = on_unsaturated
        self._jobs: deque[Connection] = deque()
        self._cond = threading.Condition()
        self._threads = 0
        self._idle = 0
        self._busy = 0
        self._closed = False
        self.idle_timeout = 60.0

    @property
    def busy(self) -> int:
        return self._busy

    @property
    def saturated(self) -> bool:
        return self.limit is not None and len(self._jobs) >= self.limit

    def submit(self, conn: Connection) -> bool:
        with self._cond:
            if self._closed:
                return False
            self._jobs.append(conn)
            if self._idle > len(self._jobs) - 1:
                self._cond.notify()
                return True
            if self.limit is not None and self._threads >= self.limit:
                return True
            thread = threading.Thread(target=self._run, daemon=True)
            try:
                thread.start()
            except RuntimeError:
                self._jobs.pop()
                return False
            self._threads += 1
            return True

    def _next(self) -> Connection | None:
        with self._cond:
            while not self._jobs:
                if self._closed:
                    self._threads -= 1
                    return None
                self._idle += 1
                woke = self._cond.wait(self.idle_timeout)
                self._idle -= 1
                if not woke and not self._jobs:
                    self._threads -= 1
                    return None
            self._busy += 1
            conn = self._jobs.popleft()
            crossed = self.limit is not None and len(self._jobs) == self.limit - 1
        if crossed and self._on_unsaturated is not None:
            self._on_unsaturated()
        return conn

    def _run(self) -> None:
        me = threading.current_thread()
        idle_name = f"{IDLE_THREAD_PREFIX}{me.ident}"
        busy_name = f"{REQUEST_THREAD_PREFIX}{me.ident}"
        me.name = idle_name
        worker = as_worker_thread(me)
        while (conn := self._next()) is not None:
            me.name = busy_name
            worker.type = "http"
            worker.start_time = time.monotonic()
            if _debug.perf.enabled:
                _debug.perf.count(
                    "httpd.dispatch",
                    queue_ms=(worker.start_time - conn.ready_at) * 1000.0,
                    request_on_connection=conn.requests + 1,
                    busy=self._busy,
                )
            try:
                self._target(conn)
            except Exception:
                _logger.exception("unhandled error in HTTP worker")
                conn.close()
            finally:
                worker.type = "http_idle"
                worker.start_time = None
                me.name = idle_name
                with self._cond:
                    self._busy -= 1

    def close(self) -> list[Connection]:
        with self._cond:
            self._closed = True
            pending = list(self._jobs)
            self._jobs.clear()
            self._cond.notify_all()
        return pending


_THREAD_EXHAUSTION_RESPONSE = b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"


class ThreadedHTTPServer:
    def __init__(
        self, host: str, port: int, app: WSGIApp, *, announce: bool = True
    ) -> None:
        self.settings = current()
        self.app = app
        self.limits = TransportLimits.from_environment()
        self.max_http_threads, auto_limit = compute_http_thread_limit(self.settings)
        announce_thread_budget(self.settings, self.max_http_threads, auto_limit)
        self.socket, self.reload_socket = self._bind(host, port, announce=announce)
        self.server_address = self.socket.getsockname()[:2]
        self.server_name, self.server_port = (
            self.server_address[0],
            self.server_address[1],
        )
        self.identity = ServerIdentity(
            self.server_name, self.server_port, True, False, True
        )
        self._pool = WorkerPool(
            self.max_http_threads or None, self._serve_connection, self._wake
        )
        self._selector = selectors.DefaultSelector()
        self._wake_r, self._wake_w = socket.socketpair()
        self._wake_r.setblocking(False)
        self._wake_w.setblocking(False)
        self._returned: deque[Connection] = deque()
        self._returned_lock = threading.Lock()
        self._idle: dict[int, Connection] = {}
        self._shutdown = threading.Event()
        self._stopped = threading.Event()
        self._stopped.set()
        self._listening = False
        self._accept_paused_until = 0.0
        self._resource_warned_at = -_RESOURCE_WARNING_INTERVAL
        _debug.lifecycle(
            "httpd.server_created",
            host=host,
            port=self.server_port,
            max_http_threads=self.max_http_threads,
            activation=self.reload_socket,
        )

    @staticmethod
    def _bind(
        host: str, port: int, *, announce: bool = True
    ) -> tuple[socket.socket, bool]:
        if os.environ.get("LISTEN_FDS") == "1" and os.environ.get("LISTEN_PID") == str(
            os.getpid()
        ):
            sock = socket.socket(fileno=3)
            if announce:
                _logger.info("HTTP service running through socket activation")
            sock.setblocking(False)
            return sock, True
        family = socket.AF_INET6 if ":" in host else socket.AF_INET
        sock = socket.socket(family, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError as exc:
            sock.close()
            sys.stderr.write(
                f"{exc.strerror or exc}\nPort {port} is in use by another program. "
                "Either identify and stop that program, or start the server with a "
                "different port.\n"
            )
            raise SystemExit(1) from exc
        sock.listen(socket.SOMAXCONN)
        sock.setblocking(False)
        if announce:
            _logger.info("HTTP service running on %s:%s", *sock.getsockname()[:2])
        return sock, False

    def _serve_connection(self, conn: Connection) -> None:
        for _ in range(_MAX_PIPELINED):
            outcome = serve_one(
                conn,
                self.app,
                self.identity,
                self.limits,
                allow_keep_alive=not self._shutdown.is_set(),
            )
            if outcome is Outcome.UPGRADED:
                return
            if outcome is Outcome.CLOSE:
                conn.close()
                return
            if find_head(conn.source.buffer, self.limits.head) is None:
                break
            conn.ready_at = time.monotonic()
        with self._returned_lock:
            if self._stopped.is_set():
                conn.close()
                return
            self._returned.append(conn)
        with contextlib.suppress(OSError):
            self._wake_w.send(b"\0")

    def _wake(self) -> None:
        with contextlib.suppress(OSError):
            self._wake_w.send(b"\0")

    def _dispatch(self, conn: Connection) -> None:
        conn.ready_at = time.monotonic()
        self._selector.unregister(conn.sock)
        self._idle.pop(conn.sock.fileno(), None)
        conn.sock.setblocking(True)
        conn.sock.settimeout(self.limits.socket_timeout)
        if not self._pool.submit(conn):
            _logger.warning(
                "could not start an HTTP worker thread; answering %s with 503",
                conn.addr,
            )
            with contextlib.suppress(OSError):
                conn.sock.sendall(_THREAD_EXHAUSTION_RESPONSE)
            conn.close()

    def _park(self, conn: Connection, now: float) -> None:
        conn.sock.setblocking(False)
        conn.head_started = bool(conn.source.buffer.strip(b"\r\n"))
        conn.idle_since = now
        conn.deadline = now + (
            self.limits.head_timeout
            if conn.head_started
            else self.limits.keepalive_timeout
        )
        self._idle[conn.sock.fileno()] = conn
        self._selector.register(conn.sock, selectors.EVENT_READ, conn)
        if len(self._idle) > self.limits.max_idle_connections:
            self._evict_oldest_idle()

    def _evict_oldest_idle(self) -> bool:
        # _idle is keyed in parking order, so the first entries are the oldest. A
        # connection idle between requests goes first because its client reconnects
        # without losing anything; after that the oldest goes, whether it never sent
        # a byte or is part way through a head, or a slowloris client could hold
        # every slot while each newcomer is closed before it can speak.
        victim = next(
            (c for c in self._idle.values() if c.requests and not c.head_started),
            None,
        )
        if victim is None:
            victim = next(iter(self._idle.values()), None)
        if victim is None:
            return False
        self._drop(victim)
        return True

    def _drop(self, conn: Connection) -> None:
        with contextlib.suppress(KeyError, ValueError):
            self._selector.unregister(conn.sock)
        self._idle.pop(conn.sock.fileno(), None)
        conn.close()

    def _accept(self, now: float) -> None:
        for _ in range(256):
            try:
                sock, addr = self.socket.accept()
            except BlockingIOError, InterruptedError:
                return
            except OSError as exc:
                _debug.logic("httpd.accept_failed", error=type(exc).__name__)
                if exc.errno in _RESOURCE_ERRNOS:
                    self._accept_starved(exc, now)
                return
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self._park(Connection(sock, addr), now)

    def _accept_starved(self, exc: OSError, now: float) -> None:
        if now - self._resource_warned_at >= _RESOURCE_WARNING_INTERVAL:
            self._resource_warned_at = now
            _logger.warning(
                "cannot accept HTTP connections (%s) with %d idle and %d busy;"
                " closing idle connections to make room",
                exc.strerror or exc,
                len(self._idle),
                self._pool.busy,
            )
        # The listener stays readable while accept fails, so without freeing a
        # descriptor or leaving the selector the loop would spin on it.
        if not self._evict_oldest_idle():
            self._accept_paused_until = now + _ACCEPT_BACKOFF

    def _readable(self, conn: Connection, now: float) -> None:
        try:
            data = conn.sock.recv(65536)
        except BlockingIOError, InterruptedError:
            return
        except OSError:
            self._drop(conn)
            return
        if not data:
            self._drop(conn)
            return
        scanned = len(conn.source.buffer)
        conn.source.buffer += data
        if not conn.head_started and conn.source.buffer.strip(b"\r\n"):
            conn.head_started = True
            conn.deadline = now + self.limits.head_timeout
        try:
            complete = (
                find_head(conn.source.buffer, self.limits.head, scanned) is not None
            )
        except ProtocolError:
            complete = True
        if complete:
            self._dispatch(conn)

    def _expire(self, now: float) -> None:
        for conn in [c for c in self._idle.values() if c.deadline <= now]:
            if conn.head_started:
                with contextlib.suppress(OSError):
                    conn.sock.send(
                        b"HTTP/1.1 408 Request Timeout\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                    )
            self._drop(conn)

    def _take_returned(self, now: float) -> None:
        with contextlib.suppress(OSError):
            while self._wake_r.recv(4096):
                pass
        with self._returned_lock:
            returned = list(self._returned)
            self._returned.clear()
        for conn in returned:
            if self._shutdown.is_set():
                conn.close()
            else:
                self._park(conn, now)

    def _update_listening(self) -> None:
        want = (
            not self._pool.saturated
            and not self._shutdown.is_set()
            and time.monotonic() >= self._accept_paused_until
        )
        if want and not self._listening:
            self._selector.register(self.socket, selectors.EVENT_READ, None)
            self._listening = True
        elif not want and self._listening:
            self._selector.unregister(self.socket)
            self._listening = False

    def serve_forever(self) -> None:
        self._stopped.clear()
        self._selector.register(self._wake_r, selectors.EVENT_READ, self._wake_r)
        next_expiry = 0.0
        try:
            while not self._shutdown.is_set():
                self._update_listening()
                timeout = 0.5
                if not self._listening and self._accept_paused_until:
                    timeout = max(
                        0.0, min(timeout, self._accept_paused_until - time.monotonic())
                    )
                for key, _ in self._selector.select(timeout=timeout):
                    now = time.monotonic()
                    if key.data is None:
                        self._accept(now)
                    elif key.data is self._wake_r:
                        self._take_returned(now)
                    else:
                        self._readable(key.data, now)
                now = time.monotonic()
                if now >= next_expiry:
                    self._expire(now)
                    next_expiry = now + 0.5
        finally:
            for conn in list(self._idle.values()):
                self._drop(conn)
            for conn in self._pool.close():
                conn.close()
            with self._returned_lock:
                returned = list(self._returned)
                self._returned.clear()
                self._stopped.set()
            for conn in returned:
                conn.close()

    def shutdown(self) -> None:
        self._shutdown.set()
        with contextlib.suppress(OSError):
            self._wake_w.send(b"\0")
        self._stopped.wait()

    def server_close(self) -> None:
        with contextlib.suppress(OSError):
            self.socket.close()
        for sock in (self._wake_r, self._wake_w):
            with contextlib.suppress(OSError):
                sock.close()

    @property
    def busy_workers(self) -> int:
        return self._pool.busy

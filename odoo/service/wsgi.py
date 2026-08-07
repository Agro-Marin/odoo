"""WSGI request handlers and the threaded WSGI server.

Extracted from ``server.py`` (which re-exports every public name here) so
``server.py`` stays focused on processes/threads and this module on the request
side of the wire.

* ``LoggingBaseWSGIServerMixIn`` — turns request-handling exceptions into log
  records (skipping benign client-disconnects).
* ``BaseWSGIServerNoBind`` — werkzeug ``BaseWSGIServer`` that skips its bind;
  ``WorkerHTTP`` replaces ``self.socket`` before each request.
* ``CommonRequestHandler`` / ``RequestHandler`` — prefork and threaded request
  handlers, with ANSI styling, websocket-upgrade tweaks, and a timeout-vs-error
  log distinction.
* ``ThreadedWSGIServerReloadable`` — ``ThreadedServer``'s WSGI server: bounded
  handler thread pool, semaphore-balanced accept loop, daemon-thread fallback
  when ``pthread_create`` returns EAGAIN.
"""

from __future__ import annotations

import logging
import os
import socket
import sys
import threading
import time
import weakref
from contextlib import suppress
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from io import BytesIO
from typing import Any

import werkzeug.serving
from werkzeug.urls import uri_to_iri

from odoo.libs.worker_thread import current_worker_thread
from odoo.tools import config

from ._env import env_float, env_int

_logger = logging.getLogger("odoo.service.server")


def http_socket_timeout() -> float:
    """Per-operation socket timeout for one served HTTP connection.

    Single source of truth for every server flavor, so deployments cannot drift
    into different DoS postures: without it a handler thread blocks forever in
    ``rfile.readline()`` while holding one of the bounded ``max_http_threads``
    slots, which a handful of slowloris connections turns into an
    unauthenticated denial of service.

    Per-operation, not per-request: a slow upload keeps resetting it as long as
    bytes keep arriving.  Floor 0.1s — ``0`` would put the socket in
    non-blocking mode and break every request.
    """
    return env_float("ODOO_HTTP_SOCKET_TIMEOUT", 2.0, minimum=0.1, logger=_logger)


_ANSI_ENABLED = sys.stderr.isatty()


def _maybe_style(msg: str, *styles: str) -> str:
    """Apply werkzeug ANSI styles when stderr is a TTY, otherwise return as-is."""
    if not _ANSI_ENABLED:
        return msg
    return werkzeug.serving._ansi_style(msg, *styles)


def _parse_http_date(value: str) -> datetime | None:
    """Parse an HTTP-date header value to an aware ``datetime``, or ``None``.

    ``None`` on any malformed value: ``parsedate_to_datetime`` raises
    ``ValueError`` on garbage.  The result is always tz-AWARE — an RFC-legal
    ``-0000`` ("unknown local offset") parses NAIVE, and subtracting a naive
    from an aware datetime raises ``TypeError``; both operands are pinned to UTC
    here so the caller can always compare them.  Comparing two Date headers is a
    cosmetic dedup, so a value we cannot parse must never turn into a 500.
    """
    try:
        dt = parsedate_to_datetime(value)
    except TypeError, ValueError:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt


class LoggingBaseWSGIServerMixIn:
    def handle_error(self, request: Any, client_address: tuple[str, int]) -> None:
        if isinstance(sys.exception(), BrokenPipeError):
            return
        _logger.exception(
            "Exception happened during processing of request from %s",
            client_address,
        )


class BaseWSGIServerNoBind(LoggingBaseWSGIServerMixIn, werkzeug.serving.BaseWSGIServer):
    """werkzeug Base WSGI Server patched to skip socket binding. WorkerHTTP
    uses this class, sets the socket and calls process_request() manually.
    """

    def __init__(self, app: Any) -> None:
        werkzeug.serving.BaseWSGIServer.__init__(
            self, "127.0.0.1", 0, app, handler=CommonRequestHandler
        )
        if self.socket:
            self.socket.close()

    def server_bind(self) -> None:
        self.server_name = "127.0.0.1"
        self.server_port = 0

    def server_activate(self) -> None:
        pass


class CommonRequestHandler(werkzeug.serving.WSGIRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._sent_date_header: str | None = None
        self._sent_server_header: str | None = None
        super().__init__(*args, **kwargs)

    def send_header(self, keyword: str, value: str) -> None:
        if keyword.casefold() == "date":
            if self._sent_date_header is None:
                self._sent_date_header = value
            elif self._sent_date_header == value:
                return
            else:
                sent_datetime = _parse_http_date(self._sent_date_header)
                new_datetime = _parse_http_date(value)
                if sent_datetime is not None and new_datetime is not None:
                    if abs((sent_datetime - new_datetime).total_seconds()) <= 1:
                        return
                    _logger.warning(
                        "sending two different Date response headers: %r vs %r",
                        self._sent_date_header,
                        value,
                    )
                else:
                    _logger.warning(
                        "un-parseable Date response header(s); sending both: "
                        "%r then %r",
                        self._sent_date_header,
                        value,
                    )

        if keyword.casefold() == "server":
            if self._sent_server_header is None:
                self._sent_server_header = value
            elif self._sent_server_header == value:
                return
            else:
                _logger.warning(
                    "sending two different Server response headers: %r vs %r",
                    self._sent_server_header,
                    value,
                )

        super().send_header(keyword, value)

    def log_error(self, format: str, *args: Any) -> None:
        if format == "Request timed out: %r":
            _logger.debug(format, *args)
            return
        super().log_error(format, *args)

    def log_request(self, code: str | int = "-", size: str | int = "-") -> None:
        raw_path = getattr(self, "path", "")
        try:
            path = uri_to_iri(raw_path) if raw_path else self.requestline
            fragment = getattr(current_worker_thread(), "rpc_model_method", "")
            if fragment:
                path += "#" + fragment
            msg = f"{self.command} {path} {self.request_version}"
        except AttributeError:
            msg = self.requestline

        msg = msg.translate(self._control_char_table)

        code = str(code)

        if "/static/" in raw_path and not config["dev_mode"]:
            self.log("debug", '"%s" %s %s', msg, code, size)
            return

        if code[0] == "1":
            msg = _maybe_style(msg, "bold")
        elif code == "200":
            pass
        elif code == "304":
            msg = _maybe_style(msg, "cyan")
        elif code[0] == "3":
            msg = _maybe_style(msg, "green")
        elif code == "404":
            msg = _maybe_style(msg, "yellow")
        elif code[0] == "4":
            msg = _maybe_style(msg, "bold", "red")
        else:
            msg = _maybe_style(msg, "bold", "magenta")

        self.log("info", '"%s" %s %s', msg, code, size)


class RequestHandler(CommonRequestHandler):
    def setup(self) -> None:
        self.timeout = http_socket_timeout()
        if config["test_enable"]:
            self.timeout = max(self.timeout, 5)
        super().setup()
        me = threading.current_thread()
        me.name = f"odoo.service.http.request.{me.ident}"

    def make_environ(self) -> dict[str, Any]:
        environ = super().make_environ()
        environ["socket"] = self.connection
        if self.headers.get("Upgrade") == "websocket":
            self.protocol_version = "HTTP/1.1"
        return environ

    def _is_websocket_upgrade(self) -> bool:
        """Whether the in-flight request asked for a websocket upgrade.

        Reads ``self.headers`` defensively: a malformed request line makes
        ``BaseHTTPRequestHandler`` call ``send_error(400)`` — and so
        ``send_header``/``end_headers`` — before ``self.headers`` is assigned,
        and werkzeug's ``__getattr__`` forwards the lookup to a ``super()`` that
        has none either.  The resulting ``AttributeError`` killed the 400
        half-written, reachable by anyone who can open a socket.
        ``log_request`` guards ``self.path`` the same way.
        """
        headers = getattr(self, "headers", None)
        return headers is not None and headers.get("Upgrade") == "websocket"

    def send_header(self, keyword: str, value: str) -> None:
        if (
            keyword == "Connection"
            and value == "close"
            and self._is_websocket_upgrade()
        ):
            self.close_connection = True
            return
        super().send_header(keyword, value)

    def end_headers(self, *a: Any, **kw: Any) -> None:
        super().end_headers(*a, **kw)
        if self._is_websocket_upgrade():
            self.rfile = BytesIO()
            self.wfile = BytesIO()

    def send_response(self, code: int, message: str | None = None) -> None:
        super().send_response(code, message)
        if code == 101:
            conn = getattr(self, "connection", None)
            if conn is not None:
                with suppress(OSError):
                    conn.settimeout(None)
            release = getattr(self.server, "release_upgraded_request_slot", None)
            if release is not None:
                release(self.request)


class ThreadedWSGIServerReloadable(
    LoggingBaseWSGIServerMixIn, werkzeug.serving.ThreadedWSGIServer
):
    """werkzeug ThreadedWSGIServer patched to adopt a listen socket handed in via
    systemd socket activation (``LISTEN_FDS`` — see ``server_bind``).

    Not the autoreload path: threaded ``--dev=reload`` re-execs and rebinds a
    fresh socket.  Only ``PreforkServer`` carries its socket across a reload
    (via ``ODOO_HTTP_SOCKET_FD``, which this class never reads).
    """

    def __init__(self, host: str, port: int, app: Any) -> None:
        auto_limit = max(
            (config["db_maxconn"] - config["max_cron_threads"] - config["job_workers"])
            // 2,
            1,
        )
        self.max_http_threads = env_int(
            "ODOO_MAX_HTTP_THREADS", auto_limit, minimum=0, logger=_logger
        )
        if self.max_http_threads:
            self.http_threads_sem = threading.Semaphore(self.max_http_threads)
            self._sem_released_requests: weakref.WeakSet = weakref.WeakSet()
        super().__init__(host, port, app, handler=RequestHandler)

        self.daemon_threads = True

    def server_bind(self) -> None:
        SD_LISTEN_FDS_START = 3
        if os.environ.get("LISTEN_FDS") == "1" and os.environ.get("LISTEN_PID") == str(
            os.getpid()
        ):
            self.reload_socket = True
            self.socket = socket.socket(fileno=SD_LISTEN_FDS_START)
            _logger.info("HTTP service (werkzeug) running through socket activation")
        else:
            self.reload_socket = False
            super().server_bind()
            _logger.info(
                "HTTP service (werkzeug) running on %s:%s",
                self.server_name,
                self.server_port,
            )

    def server_activate(self) -> None:
        if not self.reload_socket:
            super().server_activate()

    def process_request(self, request: Any, client_address: tuple[str, int]) -> None:
        """Start a request-handling thread.

        Overrides ``socketserver.ThreadingMixIn`` to capture the thread object
        and stamp its start time as an attribute.
        """
        t = threading.Thread(
            target=self.process_request_thread, args=(request, client_address)
        )
        t.daemon = self.daemon_threads
        t.type = "http"
        t.start_time = time.monotonic()
        try:
            t.start()
        except RuntimeError as exc:
            _logger.warning(
                "thread spawn failed (%s, active=%d); serving request synchronously",
                exc,
                threading.active_count(),
            )
            self.process_request_thread(request, client_address)

    def _handle_request_noblock(self) -> None:
        if self.max_http_threads and not self.http_threads_sem.acquire(timeout=0.1):
            return
        super()._handle_request_noblock()

    def get_request(self) -> Any:
        """Forward to upstream, releasing the HTTP-threads semaphore on failure.

        CPython's ``_handle_request_noblock`` catches ``OSError`` from this call
        and returns without ``shutdown_request`` (the only release point), so
        under fd exhaustion or connection-reset storms the semaphore would drain
        and never recover.  Releasing here on ``OSError`` keeps it balanced.
        """
        try:
            return super().get_request()
        except OSError:
            if self.max_http_threads:
                self.http_threads_sem.release()
            raise

    def _release_http_slot(self, request: Any) -> None:
        """Idempotently return ``request``'s bounded-thread slot.

        A request can legitimately reach a release point twice: a duplicate
        ``shutdown_request`` on the inline-fail + SystemExit path (see
        ``__init__`` next to ``_sem_released_requests``), or an early
        websocket-upgrade release followed by the connection's eventual
        ``shutdown_request``.  WeakSet membership is GIL-atomic and a request
        is handled by one thread at a time, so no lock is needed.
        """
        if request not in self._sem_released_requests:
            self.http_threads_sem.release()
            self._sem_released_requests.add(request)

    def release_upgraded_request_slot(self, request: Any) -> None:
        """Free ``request``'s bounded-thread slot after a protocol upgrade.

        Called by ``RequestHandler.send_response`` when it commits a 101
        response: the handler thread then parks on the long-lived websocket
        serve loop for the connection's lifetime, and keeping its slot would
        let a handful of idle websocket tabs starve the accept loop (see
        ``_handle_request_noblock``).  The later ``shutdown_request`` for the
        same connection is a no-op thanks to ``_release_http_slot``'s
        idempotence.
        """
        if self.max_http_threads:
            self._release_http_slot(request)

    def shutdown_request(self, request: Any) -> None:
        if self.max_http_threads:
            self._release_http_slot(request)
        super().shutdown_request(request)

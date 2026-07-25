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
from email.utils import parsedate_to_datetime
from io import BytesIO
from typing import Any

import werkzeug.serving
from werkzeug.urls import uri_to_iri

from odoo.tools import config

from ._env import env_float, env_int

_logger = logging.getLogger("odoo.service.server")  # preserve operator log filters


def http_socket_timeout() -> float:
    """Per-operation socket timeout for one served HTTP connection.

    Single source of truth for every server flavor: ``WorkerHTTP`` applies it to
    each accepted socket in prefork, and ``RequestHandler.setup`` applies it on
    the threaded and evented servers.  Sharing one knob (and one default) keeps
    the deployments from drifting into different DoS postures.

    Without it, a handler thread blocks forever in ``rfile.readline()`` waiting
    for a request line that never arrives, while still holding one of the
    bounded ``max_http_threads`` slots.  Measured on the threaded server: six
    connections sending nine bytes each (``GET /slow``, no CRLF) drained the pool
    to 0/4 and every subsequent request timed out — an unauthenticated denial of
    service costing the attacker almost nothing.  Prefork was never exposed
    because it has always set this; the threaded path used to set a timeout only
    under ``--test-enable``.

    This is a per-operation deadline, not a request deadline: a slow upload keeps
    resetting it as long as bytes keep arriving.  Floor 0.1s — ``0`` would put the
    socket in non-blocking mode and break every request.
    """
    return env_float("ODOO_HTTP_SOCKET_TIMEOUT", 2.0, minimum=0.1, logger=_logger)


# ANSI status colors help on a TTY but pollute a log file (raw ESC sequences)
# under systemd or a log shipper.  Detected once — stderr's tty-ness is fixed.
_ANSI_ENABLED = sys.stderr.isatty()


def _maybe_style(msg: str, *styles: str) -> str:
    """Apply werkzeug ANSI styles when stderr is a TTY, otherwise return as-is."""
    if not _ANSI_ENABLED:
        return msg
    return werkzeug.serving._ansi_style(msg, *styles)


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
        # ``TCPServer.__init__`` always creates ``self.socket``, but our
        # ``server_bind`` skipped the bind, so close this unused fd: every
        # request gets its socket patched in by ``WorkerHTTP.process_request``.
        if self.socket:
            self.socket.close()

    def server_bind(self) -> None:
        # Skip ``socket.bind`` — every request's socket is patched in by
        # ``WorkerHTTP.process_request``, so binding would waste an ephemeral
        # port.  Set placeholders so werkzeug logging doesn't AttributeError.
        self.server_name = "127.0.0.1"
        self.server_port = 0

    def server_activate(self) -> None:
        # dont listen as we use PreforkServer#socket
        pass


class CommonRequestHandler(werkzeug.serving.WSGIRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # werkzeug and the stdlib base handler can each emit a Date/Server
        # header; track what we sent so a request never carries two.
        self._sent_date_header: str | None = None
        self._sent_server_header: str | None = None
        super().__init__(*args, **kwargs)

    def send_header(self, keyword: str, value: str) -> None:
        if keyword.casefold() == "date":
            if self._sent_date_header is None:
                self._sent_date_header = value
            elif self._sent_date_header == value:
                return  # don't send the same header twice
            else:
                sent_datetime = parsedate_to_datetime(self._sent_date_header)
                new_datetime = parsedate_to_datetime(value)
                if sent_datetime == new_datetime:
                    return  # don't send the same date twice (differ in format)
                if abs((sent_datetime - new_datetime).total_seconds()) <= 1:
                    return  # don't send the same date twice (jitter of 1 second)
                _logger.warning(
                    "sending two different Date response headers: %r vs %r",
                    self._sent_date_header,
                    value,
                )

        if keyword.casefold() == "server":
            if self._sent_server_header is None:
                self._sent_server_header = value
            elif self._sent_server_header == value:
                return  # don't send the same header twice
            else:
                _logger.warning(
                    "sending two different Server response headers: %r vs %r",
                    self._sent_server_header,
                    value,
                )

        super().send_header(keyword, value)

    def log_error(self, format: str, *args: Any) -> None:
        # Idle-connection timeouts aren't errors (browser pre-connects,
        # keep-alive probes, connection pools).  Downgrade to DEBUG.
        if format == "Request timed out: %r":
            _logger.debug(format, *args)
            return
        super().log_error(format, *args)

    def log_request(self, code: str | int = "-", size: str | int = "-") -> None:
        # Resolve the request path once (``self.path`` is unset on a malformed
        # requestline; the static-asset filter below reads it too).
        raw_path = getattr(self, "path", "")
        try:
            path = uri_to_iri(raw_path) if raw_path else self.requestline
            fragment = getattr(threading.current_thread(), "rpc_model_method", "")
            if fragment:
                path += "#" + fragment
            msg = f"{self.command} {path} {self.request_version}"
        except AttributeError:
            # command or request_version also missing on a malformed request
            msg = self.requestline

        # Neutralize control characters before the line reaches a log sink.
        # Both the decoded request-target (``http.server`` keeps raw C0/C1 bytes
        # from the request line; ``uri_to_iri`` does not strip them) and the
        # ``rpc_model_method`` fragment (set from the raw RPC ``method`` param
        # BEFORE validation, see ``model.execute_cr``) are attacker-controlled,
        # so an unescaped ESC/CSI byte would render as a live terminal sequence
        # in an operator's log (spoofed entries, screen-clear).  werkzeug's own
        # ``log_request`` applies this same table; the fork's override must not
        # drop it.
        msg = msg.translate(self._control_char_table)

        code = str(code)

        # In ESM mode the browser fetches each JS/CSS file individually,
        # flooding the log; downgrade static-asset lines to DEBUG.
        if "/static/" in raw_path and not config["dev_mode"]:
            self.log("debug", '"%s" %s %s', msg, code, size)
            return

        if code[0] == "1":  # 1xx - Informational
            msg = _maybe_style(msg, "bold")
        elif code == "200":  # 2xx - Success
            pass
        elif code == "304":  # 304 - Resource Not Modified
            msg = _maybe_style(msg, "cyan")
        elif code[0] == "3":  # 3xx - Redirection
            msg = _maybe_style(msg, "green")
        elif code == "404":  # 404 - Resource Not Found
            msg = _maybe_style(msg, "yellow")
        elif code[0] == "4":  # 4xx - Client Error
            msg = _maybe_style(msg, "bold", "red")
        else:  # 5xx, or any other response
            msg = _maybe_style(msg, "bold", "magenta")

        self.log("info", '"%s" %s %s', msg, code, size)


class RequestHandler(CommonRequestHandler):
    def setup(self) -> None:
        # Bound the request-read phase on every connection, not just under
        # ``--test-enable`` as this used to: an idle half-open connection
        # otherwise parks a handler thread — and one of the bounded
        # ``max_http_threads`` slots — forever.  See ``http_socket_timeout``.
        # ``StreamRequestHandler.setup`` pushes ``self.timeout`` onto the socket,
        # so it must be assigned BEFORE the ``super().setup()`` below.
        self.timeout = http_socket_timeout()
        if config["test_enable"]:
            # Chrome-headless preconnects during tests open sockets they never
            # write to; keep the historical 5s grace, but never shorten the
            # shared default.
            self.timeout = max(self.timeout, 5)
        # flag the current thread as handling a http request
        super().setup()
        me = threading.current_thread()
        me.name = f"odoo.service.http.request.{me.ident}"

    def make_environ(self) -> dict[str, Any]:
        environ = super().make_environ()
        # Add the TCP socket to environ in order for the websocket
        # connections to use it.
        environ["socket"] = self.connection
        if self.headers.get("Upgrade") == "websocket":
            # Since the upgrade header is introduced in version 1.1, Firefox
            # won't accept a websocket connection if the version is set to
            # 1.0.
            self.protocol_version = "HTTP/1.1"
        return environ

    def _is_websocket_upgrade(self) -> bool:
        """Whether the in-flight request asked for a websocket upgrade.

        Reads ``self.headers`` DEFENSIVELY.  ``BaseHTTPRequestHandler`` assigns
        that attribute only after it has parsed the request line, but a MALFORMED
        request line makes it call ``send_error(400)`` — and therefore
        ``send_header`` / ``end_headers`` — while ``self.headers`` is still
        unset.  werkzeug's ``WSGIRequestHandler.__getattr__`` then forwards the
        lookup to ``super()``, which has no ``headers`` either, so the override
        raised ``AttributeError: 'super' object has no attribute 'headers'`` from
        inside the error path: the 400 response died half-written and the client
        got NOTHING back, while the server logged a traceback at ERROR.

        That is reachable unauthenticated by anyone who can open a socket — a
        browser sent to ``https://host:8069``, a TLS probe, a port scanner, a
        misconfigured health check — on both servers that use this handler (the
        threaded dev/test server and the evented long-polling subprocess).
        ``log_request`` already guards ``self.path`` the same way.
        """
        headers = getattr(self, "headers", None)
        return headers is not None and headers.get("Upgrade") == "websocket"

    def send_header(self, keyword: str, value: str) -> None:
        # Prevent WSGIRequestHandler from sending the "Connection: close" header
        # which is incompatible with WebSocket connections.
        if (
            keyword == "Connection"
            and value == "close"
            and self._is_websocket_upgrade()
        ):
            # Do not keep processing requests.
            self.close_connection = True
            return
        super().send_header(keyword, value)

    def end_headers(self, *a: Any, **kw: Any) -> None:
        super().end_headers(*a, **kw)
        # After end_headers, werkzeug assumes the connection is closed and discards
        # incoming data. For WebSocket upgrades, replace rfile/wfile to prevent that.
        if self._is_websocket_upgrade():
            self.rfile = BytesIO()
            self.wfile = BytesIO()

    def send_response(self, code: int, message: str | None = None) -> None:
        super().send_response(code, message)
        if code == 101:
            # Hand the socket to the websocket loop with no inherited deadline.
            # ``setup`` armed a short per-operation timeout to bound the
            # REQUEST-READ phase (see ``http_socket_timeout``); a websocket is
            # legitimately idle for minutes at a time, and ``bus/websocket.py``
            # drives this socket through its own ``selectors`` loop, so it needs
            # no timeout of ours.
            #
            # Both guards are best-effort on purpose, and for the same reason as
            # ``_is_websocket_upgrade``: an attribute that is merely *usually*
            # present must never be dereferenced bare here, because werkzeug's
            # ``__getattr__`` turns a miss into ``AttributeError`` from inside a
            # response path.  A client that vanished between the handshake and
            # here likewise must not turn a completed upgrade into a 500.
            conn = getattr(self, "connection", None)
            if conn is not None:
                with suppress(OSError):
                    conn.settimeout(None)
            # Successful upgrade handshake: this handler thread is about to
            # park on a long-lived websocket serve loop (bus/websocket.py
            # ``_serve_forever`` runs in the response's close callback), so it
            # is no longer part of a short-lived request burst.  Return its
            # bounded-thread slot now, or each open websocket permanently
            # consumes one ``max_http_threads`` slot and the accept loop
            # starves once every slot is parked (a single browser tab is
            # enough to wedge the server when the bound computes to 1, e.g.
            # ``--db_maxconn 5`` in tests).  Guarded getattr: this handler is
            # only wired to ``ThreadedWSGIServerReloadable``, but don't crash
            # if it is ever reused on a server without the semaphore.
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
        # Bound concurrent HTTP-handling threads so a request burst (e.g. a page
        # fetching hundreds of asset shims in parallel) can't exhaust the OS
        # thread limit.  Default: half the cursor budget — db_maxconn minus the
        # in-process cron AND job threads (both borrow cursors while processing)
        # — since most requests borrow one cursor but a few borrow two.
        auto_limit = max(
            (config["db_maxconn"] - config["max_cron_threads"] - config["job_workers"])
            // 2,
            1,
        )
        # ``minimum=0``: "0" opts out of the bound (the guard below skips the
        # semaphore), and a NEGATIVE value clamps to that same opt-out rather
        # than reaching ``Semaphore(-N)``, which would abort startup.  A
        # MALFORMED value is different — ``env_float``/``env_int`` fall back to
        # the ``default``, so it keeps ``auto_limit`` (the bound stays on) rather
        # than silently disabling it.  That is the safer of the two, but it is
        # not the same behaviour, so don't conflate them.
        self.max_http_threads = env_int(
            "ODOO_MAX_HTTP_THREADS", auto_limit, minimum=0, logger=_logger
        )
        if self.max_http_threads:
            self.http_threads_sem = threading.Semaphore(self.max_http_threads)
            # Track per-request release so a duplicate ``shutdown_request`` for
            # the same socket can't double-release (and slowly inflate the cap).
            # The duplicate fires when ``process_request`` runs the handler
            # inline (pthread_create EAGAIN) and the inline handler propagates a
            # ``BaseException`` past ``process_request_thread``'s ``except
            # Exception``, so both its ``finally`` and ``_handle_request_noblock``'s
            # bare ``except:`` call ``shutdown_request``.  WeakSet because sockets
            # support weakref but not a per-request attribute.
            self._sem_released_requests: weakref.WeakSet = weakref.WeakSet()
        super().__init__(host, port, app, handler=RequestHandler)

        # Daemon threads for HTTP handlers: non-daemon threads go on the
        # interpreter's joinable-thread registry, which on Python 3.14 appears to
        # refuse new thread creation after a burst of short-lived request threads
        # (seen under the web JS test suite).  Daemon threads skip that registry.
        # Tradeoff: in-flight requests are dropped at exit — acceptable since
        # production uses PreforkServer and dev/test shutdowns are SIGINT anyway.
        self.daemon_threads = True

    def server_bind(self) -> None:
        SD_LISTEN_FDS_START = 3
        if os.environ.get("LISTEN_FDS") == "1" and os.environ.get("LISTEN_PID") == str(
            os.getpid()
        ):
            self.reload_socket = True
            # ``socket.socket(fileno=)`` detects the family via SO_DOMAIN, so an
            # IPv6 systemd socket is wrapped as AF_INET6, not garbage AF_INET.
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
            # Python can refuse a new OS thread under transient resource pressure
            # (pthread_create EAGAIN); serve the request inline on the accept
            # thread rather than dropping it.
            _logger.warning(
                "thread spawn failed (%s, active=%d); serving request synchronously",
                exc,
                threading.active_count(),
            )
            self.process_request_thread(request, client_address)

    def _handle_request_noblock(self) -> None:
        if self.max_http_threads and not self.http_threads_sem.acquire(timeout=0.1):
            # If the semaphore is full we will return immediately to the upstream (most probably
            # socketserver.BaseServer's serve_forever loop  which will retry immediately as the
            # selector will find a pending connection to accept on the socket. There is a 100 ms
            # penalty in such case in order to avoid cpu bound loop while waiting for the semaphore.
            return
        # Released by ``shutdown_request`` (every path where get_request()
        # succeeded) or by the ``get_request`` override (the OSError-from-accept
        # path).  The 1:1 acquire/release pairing keeps the semaphore from leaking.
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

"""WSGI request handlers and the threaded WSGI server.

Extracted from ``server.py`` (which still re-exports every public name here
for backwards compatibility).  Splitting these out keeps ``server.py`` focused
on the lifecycle of *processes* and *threads* — this module is concerned
purely with the request side of the wire.

What lives here:

* ``LoggingBaseWSGIServerMixIn`` — converts request-handling exceptions to log
  records (skipping benign client-disconnects).
* ``BaseWSGIServerNoBind`` — werkzeug ``BaseWSGIServer`` patched to skip its
  own bind step; ``WorkerHTTP`` (in ``server.py``) replaces ``self.socket``
  before each request.
* ``CommonRequestHandler`` / ``RequestHandler`` — request handlers for the
  prefork and threaded paths respectively, with ANSI styling, websocket
  upgrade tweaks, and a custom timeout-vs-error log distinction.
* ``ThreadedWSGIServerReloadable`` — the threaded WSGI server used by
  ``ThreadedServer``: bounded HTTP-handler thread pool, semaphore-balanced
  accept loop, daemon-thread fallback when ``pthread_create`` returns EAGAIN.
"""

from __future__ import annotations

import logging
import os
import socket
import sys
import threading
import time
import weakref
from email.utils import parsedate_to_datetime
from io import BytesIO
from typing import Any

import werkzeug.serving
from werkzeug.urls import uri_to_iri

from odoo.tools import config

from ._env import env_int

_logger = logging.getLogger("odoo.service.server")  # preserve operator log filters

# ANSI status colors are useful when developing locally with a TTY-attached
# stderr, but pollute the log file (raw ESC sequences) when the operator
# runs Odoo under systemd or pipes stderr to a log shipper.  Detect once at
# import time — stderr's tty-ness doesn't change at runtime, and a per-request
# ``isatty()`` syscall would cost ~1us over thousands of requests for no benefit.
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
        # ``socketserver.TCPServer.__init__`` always creates ``self.socket``;
        # our ``server_bind`` override skipped the bind so this socket is
        # unbound, but the fd is still allocated.  Close it: every request
        # gets its socket monkey-patched in by
        # ``WorkerHTTP.process_request``, so the placeholder is never used.
        if self.socket:
            self.socket.close()

    def server_bind(self) -> None:
        # Skip the actual ``socket.bind`` — every request gets its socket
        # monkey-patched in by ``WorkerHTTP.process_request``, so binding here
        # would only allocate (and waste) an ephemeral kernel port.
        # ``server_name`` / ``server_port`` are set to placeholders so any
        # werkzeug logging code that reads them doesn't AttributeError.
        self.server_name = "127.0.0.1"
        self.server_port = 0

    def server_activate(self) -> None:
        # dont listen as we use PreforkServer#socket
        pass


class CommonRequestHandler(werkzeug.serving.WSGIRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # werkzeug and the stdlib base handler can each emit a Date/Server
        # header; track what we already sent so a request never carries two.
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
        # Socket timeouts on idle connections are not errors — they are
        # expected from browser pre-connects, keep-alive probes, and
        # connection pools.  Downgrade to DEBUG to avoid log noise.
        if format == "Request timed out: %r":
            _logger.debug(format, *args)
            return
        super().log_error(format, *args)

    def log_request(self, code: str | int = "-", size: str | int = "-") -> None:
        # Resolve the request path once. ``self.path`` is unset when the
        # requestline was malformed — callers later in this method (the
        # static-asset filter) would re-raise ``AttributeError`` if each
        # access were guarded independently.
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

        code = str(code)

        # In ESM mode the browser fetches each JS/CSS file individually,
        # flooding the log with hundreds of static-asset lines.  Downgrade
        # those to DEBUG so they only appear with --log-level=debug.
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
        # timeout to avoid chrome headless preconnect during tests
        if config["test_enable"]:
            self.timeout = 5
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

    def send_header(self, keyword: str, value: str) -> None:
        # Prevent WSGIRequestHandler from sending the "Connection: close" header
        # which is incompatible with WebSocket connections.
        if (
            self.headers.get("Upgrade") == "websocket"
            and keyword == "Connection"
            and value == "close"
        ):
            # Do not keep processing requests.
            self.close_connection = True
            return
        super().send_header(keyword, value)

    def end_headers(self, *a: Any, **kw: Any) -> None:
        super().end_headers(*a, **kw)
        # After end_headers, werkzeug assumes the connection is closed and discards
        # incoming data. For WebSocket upgrades, replace rfile/wfile to prevent that.
        if self.headers.get("Upgrade") == "websocket":
            self.rfile = BytesIO()
            self.wfile = BytesIO()


class ThreadedWSGIServerReloadable(
    LoggingBaseWSGIServerMixIn, werkzeug.serving.ThreadedWSGIServer
):
    """werkzeug Threaded WSGI Server patched to adopt a listen socket handed in
    by the environment via systemd socket activation (``LISTEN_FDS`` — see
    ``server_bind``).

    This is NOT the autoreload path: threaded ``--dev=reload`` re-execs and
    rebinds a fresh socket.  Only ``PreforkServer`` carries its listen socket
    across a reload, via ``ODOO_HTTP_SOCKET_FD`` — a separate mechanism this
    class never reads.
    """

    def __init__(self, host: str, port: int, app: Any) -> None:
        # Bound the number of concurrent HTTP-handling threads so a burst of
        # requests (e.g. a browser opening a test page that fetches hundreds
        # of asset shims in parallel) cannot exhaust the OS thread limit.
        # Default: half of the available cursor budget (db_maxconn minus cron
        # threads), because most requests borrow at most one cursor but a few
        # controllers borrow two. ODOO_MAX_HTTP_THREADS overrides this default;
        # set it to "0" to opt out of the bound.
        auto_limit = max((config["db_maxconn"] - config["max_cron_threads"]) // 2, 1)
        # ``minimum=0``: a malformed value drops to the computed default; "0" is
        # a meaningful opt-out of the bound (the ``if self.max_http_threads:``
        # guard below skips the semaphore), and a negative value clamps to that
        # same opt-out rather than reaching ``threading.Semaphore(-N)``, which
        # raises ``ValueError`` and aborts server startup with an opaque error.
        self.max_http_threads = env_int(
            "ODOO_MAX_HTTP_THREADS", auto_limit, minimum=0, logger=_logger
        )
        if self.max_http_threads:
            self.http_threads_sem = threading.Semaphore(self.max_http_threads)
            # Per-request release tracking so a duplicate ``shutdown_request``
            # call for the same socket does not double-release the semaphore.
            # The duplicate path fires when ``process_request`` runs the
            # handler INLINE (after ``t.start()`` raised RuntimeError on
            # pthread_create EAGAIN) AND the inline handler propagates a
            # ``BaseException`` (e.g. SystemExit) past
            # ``process_request_thread``'s ``except Exception``: the
            # ``finally`` clause inside ``process_request_thread`` calls
            # ``shutdown_request`` once, then ``socketserver.BaseServer.
            # _handle_request_noblock``'s outer bare ``except:`` calls it
            # again before re-raising.  Each call would otherwise increment
            # the (unbounded) semaphore, slowly inflating the cap above
            # ``max_http_threads`` over the process's lifetime.  WeakSet
            # because socket objects support weakref but not __dict__ for
            # a per-request flag.
            self._sem_released_requests: weakref.WeakSet = weakref.WeakSet()
        super().__init__(host, port, app, handler=RequestHandler)

        # Use daemon threads for HTTP request handlers. Non-daemon threads
        # are tracked by the interpreter's joinable-thread registry, and on
        # Python 3.14 that tracking appears to throttle/refuse new thread
        # creation after a burst of short-lived request threads (observed
        # under the web JS test suite: 13 active threads, low sem slot
        # usage, pthread_create still fails with "can't start new thread").
        # Daemon threads skip the joinable registry.
        # Graceful-shutdown tradeoff: in-flight requests are dropped when
        # the process exits. That's acceptable because (a) production uses
        # PreforkServer, not this class, and (b) dev/test shutdowns are
        # almost always via SIGINT where forced termination is expected.
        self.daemon_threads = True

    def server_bind(self) -> None:
        SD_LISTEN_FDS_START = 3
        if os.environ.get("LISTEN_FDS") == "1" and os.environ.get("LISTEN_PID") == str(
            os.getpid()
        ):
            self.reload_socket = True
            # `socket.socket(fileno=)` auto-detects the family via SO_DOMAIN,
            # so an IPv6 systemd socket is wrapped as AF_INET6, not reinterpreted
            # as a sockaddr_in with garbage address fields.
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
        """
        Start a new thread to process the request.
        Override the default method of class socketserver.ThreadingMixIn
        to be able to get the thread object which is instantiated
        and set its start time as an attribute
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
            # Python can refuse to spawn a new OS thread under transient
            # resource pressure (pthread_create EAGAIN). Rather than drop
            # the request, serve it inline on the accept thread so the
            # client still gets a response.
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
        # Released either by ``shutdown_request`` (every path where
        # get_request() succeeded) or by the ``get_request`` override below (the
        # OSError-from-accept path upstream silently swallows).  The 1:1
        # acquire/release pairing is what keeps the semaphore from leaking.
        super()._handle_request_noblock()

    def get_request(self) -> Any:
        """Forward to upstream, releasing the HTTP-threads semaphore on failure.

        CPython's ``socketserver.BaseServer._handle_request_noblock`` catches
        ``OSError`` from this call and returns without invoking
        ``shutdown_request`` (the only place the semaphore is released).
        Under fd exhaustion (EMFILE), connection-reset storms, or a
        misconfigured listener (EBADF), the semaphore would slowly drain
        and never recover until process restart.  Releasing here on
        ``OSError`` keeps acquire/release balanced.
        """
        try:
            return super().get_request()
        except OSError:
            if self.max_http_threads:
                self.http_threads_sem.release()
            raise

    def shutdown_request(self, request: Any) -> None:
        if self.max_http_threads:
            # Idempotent release: a request can legitimately reach
            # ``shutdown_request`` twice on the inline-fail + SystemExit
            # path (see the comment in ``__init__`` next to
            # ``_sem_released_requests``).  Track which requests have been
            # released and skip the second decrement.  WeakSet membership
            # is GIL-atomic, and a single request is only handled by one
            # thread at a time, so no extra lock is needed.
            if request not in self._sem_released_requests:
                self.http_threads_sem.release()
                self._sem_released_requests.add(request)
        super().shutdown_request(request)

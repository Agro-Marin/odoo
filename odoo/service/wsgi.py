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

from odoo.libs.worker_thread import as_worker_thread, current_worker_thread
from odoo.tools import config

from ._env import env_float, env_int

_logger = logging.getLogger("odoo.service.server")


def http_socket_timeout() -> float:
    return env_float("ODOO_HTTP_SOCKET_TIMEOUT", 2.0, minimum=0.1, logger=_logger)


_ANSI_ENABLED = sys.stderr.isatty()


def _plain_style(msg: str, *styles: str) -> str:
    return msg


#: ``werkzeug.serving._ansi_style`` is private API.  Resolved once here, with an
#: identity fallback, rather than reached for on every call: colouring a request
#: log line is not worth an ``AttributeError`` raised inside the request
#: handler on every non-200 response, which is what a werkzeug release that
#: renames it would otherwise cause.
_ansi_style = getattr(werkzeug.serving, "_ansi_style", _plain_style)


def _maybe_style(msg: str, *styles: str) -> str:
    if not _ANSI_ENABLED:
        return msg
    return _ansi_style(msg, *styles)


def _parse_http_date(value: str) -> datetime | None:
    try:
        dt = parsedate_to_datetime(value)
    except TypeError, ValueError:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt


class LoggingBaseWSGIServerMixIn:
    def handle_error(self, request: Any, client_address: tuple[str, int]) -> None:
        exc = sys.exception()
        if isinstance(exc, BrokenPipeError):
            return
        _logger.error(
            "Exception happened during processing of request from %s",
            client_address,
            exc_info=exc,
        )


class BaseWSGIServerNoBind(LoggingBaseWSGIServerMixIn, werkzeug.serving.BaseWSGIServer):
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
        t = threading.Thread(
            target=self.process_request_thread, args=(request, client_address)
        )
        t.daemon = self.daemon_threads
        worker = as_worker_thread(t)
        worker.type = "http"
        worker.start_time = time.monotonic()
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
        try:
            return super().get_request()
        except OSError:
            if self.max_http_threads:
                self.http_threads_sem.release()
            raise

    def _release_http_slot(self, request: Any) -> None:
        if request not in self._sem_released_requests:
            self.http_threads_sem.release()
            self._sem_released_requests.add(request)

    def release_upgraded_request_slot(self, request: Any) -> None:
        if self.max_http_threads:
            self._release_http_slot(request)

    def shutdown_request(self, request: Any) -> None:
        if self.max_http_threads:
            self._release_http_slot(request)
        super().shutdown_request(request)

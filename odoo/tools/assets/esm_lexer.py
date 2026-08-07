import atexit
import contextlib
import json
import logging
import os
import select
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import odoo
from odoo.libs.asset_log import get_asset_logger, log_event

_lexer_log = get_asset_logger("lexer")

_WORKER_SCRIPT = Path(__file__).parent / "js" / "esm_lexer_worker.mjs"

_REQUEST_TIMEOUT_S = 10.0

_MAX_CONSECUTIVE_FAILURES = 2


class _LexerWorker:
    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._counter = 0
        self._disabled = False
        self._consec_failures = 0
        self._inbuf = b""
        self._lock = threading.Lock()

    def _spawn(self) -> subprocess.Popen | None:
        node = shutil.which("node")
        if not node:
            return None
        odoo_root = Path(odoo.__path__[0]).parent
        try:
            proc = subprocess.Popen(
                [node, str(_WORKER_SCRIPT)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,
                cwd=odoo_root,
            )
        except OSError:
            return None
        os.set_blocking(proc.stdin.fileno(), False)
        os.set_blocking(proc.stdout.fileno(), False)
        self._inbuf = b""
        _register_worker_cleanup()
        return proc

    def close(self) -> None:
        with self._lock:
            self._kill()

    def _kill(self) -> None:
        proc, self._proc = self._proc, None
        self._inbuf = b""
        if proc is not None:
            with contextlib.suppress(OSError):
                proc.kill()
            with contextlib.suppress(subprocess.TimeoutExpired, OSError):
                proc.wait(timeout=5)

    def _write_all(self, proc: subprocess.Popen, data: bytes, deadline: float) -> None:
        fd = proc.stdin.fileno()
        view = memoryview(data)
        while view:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("lexer worker stdin write timed out")
            _, writable, _ = select.select([], [fd], [], remaining)
            if not writable:
                raise TimeoutError("lexer worker stdin write timed out")
            try:
                written = os.write(fd, view)
            except BlockingIOError:
                continue
            except OSError as exc:
                raise EOFError("lexer worker closed stdin") from exc
            view = view[written:]

    def _read_line(self, proc: subprocess.Popen, deadline: float) -> str:
        fd = proc.stdout.fileno()
        while True:
            newline = self._inbuf.find(b"\n")
            if newline >= 0:
                line, self._inbuf = self._inbuf[:newline], self._inbuf[newline + 1 :]
                return line.decode("utf-8")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("lexer worker stdout read timed out")
            readable, _, _ = select.select([fd], [], [], remaining)
            if not readable:
                raise TimeoutError("lexer worker stdout read timed out")
            try:
                chunk = os.read(fd, 65536)
            except BlockingIOError:
                continue
            if not chunk:
                raise EOFError("lexer worker closed stdout")
            self._inbuf += chunk

    def request(self, src: str) -> dict[str, Any] | None:
        if self._disabled or os.name != "posix":
            return None
        with self._lock:
            for _attempt in range(2):
                proc = self._proc
                if proc is None or proc.poll() is not None:
                    proc = self._proc = self._spawn()
                    if proc is None:
                        self._disabled = True
                        log_event(
                            _lexer_log,
                            logging.INFO,
                            "worker_unavailable",
                            hint="node + `npm install` provide es-module-lexer;"
                            " using the regex extractor",
                        )
                        return None
                self._counter += 1
                request_id = self._counter
                deadline = time.monotonic() + _REQUEST_TIMEOUT_S
                try:
                    payload = json.dumps({"id": request_id, "src": src}) + "\n"
                    self._write_all(proc, payload.encode("utf-8"), deadline)
                    line = self._read_line(proc, deadline)
                    response = json.loads(line)
                    if response.get("id") != request_id:
                        raise ValueError("lexer worker desynchronized")
                except Exception as exc:
                    self._kill()
                    self._consec_failures += 1
                    disabled = self._consec_failures >= _MAX_CONSECUTIVE_FAILURES
                    if disabled:
                        self._disabled = True
                    log_event(
                        _lexer_log,
                        logging.WARNING if disabled else logging.DEBUG,
                        "worker_request_failed",
                        err=type(exc).__name__,
                        attempt=_attempt + 1,
                        consecutive=self._consec_failures,
                        disabled=disabled,
                    )
                    if disabled:
                        return None
                    continue
                self._consec_failures = 0
                if not response.get("ok"):
                    log_event(
                        _lexer_log,
                        logging.DEBUG,
                        "source_unlexable",
                        err=str(response.get("error", ""))[:200],
                    )
                    return None
                return response
            return None


_worker = _LexerWorker()
_cleanup_registered = False


def _register_worker_cleanup() -> None:
    global _cleanup_registered  # noqa: PLW0603  atexit hook must be registered exactly once
    if _cleanup_registered:
        return
    _cleanup_registered = True
    atexit.register(close_lexer_worker)
    try:
        from odoo.service.server import CommonServer

        CommonServer.on_stop(close_lexer_worker)
    except Exception:
        log_event(
            _lexer_log,
            logging.DEBUG,
            "on_stop_registration_failed",
        )


def close_lexer_worker() -> None:
    _worker.close()


def lex_module(src: str) -> dict[str, Any] | None:
    return _worker.request(src)

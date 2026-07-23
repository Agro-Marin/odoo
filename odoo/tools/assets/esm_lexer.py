"""Persistent es-module-lexer worker client for the assets pipeline.

The regex export-extractor in ``esm_graph`` is corpus-validated but
inherently approximate (it scans text, not syntax).  This module offers a
spec-compliant alternative: a long-lived node subprocess running
``es-module-lexer`` (``js/esm_lexer_worker.mjs``), spoken to over
line-delimited JSON in strict request/response ping-pong.

Callers treat it as best-effort: :func:`lex_module` returns ``None``
whenever node is missing, the package isn't installed, the worker dies,
times out, or the source doesn't lex — and the caller falls back to the
regex path.  A worker that fails to *spawn* twice is disabled for the
process lifetime (one log line, not one per module).

One worker per server process (spawned lazily, guarded by a lock — the
protocol is stateful ping-pong so requests must serialize).  POSIX-only:
the read timeout uses ``select`` on the pipe, which Windows does not
support for pipes; non-POSIX platforms simply use the regex path.
"""

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

# Per-request budget.  Lexing is sub-millisecond; the timeout only exists
# so a wedged worker degrades to the regex path instead of pinning a
# server worker.  Generous because the FIRST request also pays node
# startup + WASM init.  This is a HARD wall-clock bound on the whole
# request/response (see ``_write_all`` / ``_read_line``): neither the
# stdin write nor the stdout read can exceed it, even against a worker
# that stopped reading (full pipe) or emitted a partial line then wedged.
_REQUEST_TIMEOUT_S = 10.0

# After this many CONSECUTIVE failed requests the worker is disabled for
# the process (regex fallback everywhere).  Without this a worker that is
# present but broken (e.g. an incompatible node build that never answers)
# would cost up to ``_REQUEST_TIMEOUT_S`` PER MODULE — minutes across a
# large bundle.  A single wedged module now costs at most this many
# timeouts once, then the whole process degrades to the fast regex path.
_MAX_CONSECUTIVE_FAILURES = 2


class _LexerWorker:
    """One persistent worker subprocess.

    Respawn-once per request: a worker that dies mid-request (OOM,
    operator) is respawned and the request retried once.  A *spawn*
    failure (no ``node`` on PATH, or ``OSError`` launching it) disables
    the worker for the process immediately — the environment cannot run
    it.  ``_MAX_CONSECUTIVE_FAILURES`` consecutive request failures
    (timeout / EOF / desync) also disable it, so a present-but-broken
    worker degrades the whole process to the regex path fast instead of
    paying the per-request budget on every module.

    I/O is deadline-bounded (``_write_all`` / ``_read_line``): the pipes
    are non-blocking and every read/write is gated by ``select`` against
    the request's wall-clock deadline, so a wedged worker can never block
    a caller past ``_REQUEST_TIMEOUT_S``.
    """

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._counter = 0
        self._disabled = False
        self._consec_failures = 0
        self._inbuf = b""  # bytes read past the last response newline
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
                # Binary + unbuffered: we frame line-delimited JSON
                # ourselves over the raw fds so the I/O can be made
                # non-blocking and deadline-bounded (a text-mode
                # ``readline`` on a partial line blocks unbounded).
                bufsize=0,
                # node resolves ``es-module-lexer`` against the Odoo
                # root's node_modules (same install that provides esbuild).
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
        """Shut down the worker from outside a request.

        Takes ``_lock`` so ``_proc``/``_inbuf`` are never mutated under a
        concurrent :meth:`request` (which holds the lock for its whole
        lifecycle and uses the unlocked :meth:`_kill` on its own failure
        path — calling ``close`` there would self-deadlock).
        """
        with self._lock:
            self._kill()

    def _kill(self) -> None:
        proc, self._proc = self._proc, None
        self._inbuf = b""
        if proc is not None:
            with contextlib.suppress(OSError):
                proc.kill()
            # Reap it: an unwaited-for killed child lingers as a zombie, which
            # still shows up in `psutil.Process().children()` — so the test
            # suite's leftover-child audit kept reporting it as a leak even
            # once it was dead. SIGKILL is not catchable, so this cannot block
            # for long; the timeout only guards a pathological uninterruptible
            # state.
            with contextlib.suppress(subprocess.TimeoutExpired, OSError):
                proc.wait(timeout=5)

    def _write_all(self, proc: subprocess.Popen, data: bytes, deadline: float) -> None:
        """Write all of ``data`` to the worker's stdin before ``deadline``.

        Non-blocking fd + ``select``: a worker that stopped reading (its
        own stdout pipe full, or wedged) cannot block us past the budget,
        unlike a plain ``stdin.write`` on a full pipe (~64 KB) which
        blocks unbounded before ``select`` is ever reached.
        """
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
            except OSError as exc:  # BrokenPipeError et al. — worker gone
                raise EOFError("lexer worker closed stdin") from exc
            view = view[written:]

    def _read_line(self, proc: subprocess.Popen, deadline: float) -> str:
        """Read one newline-terminated response before ``deadline``.

        ``select`` only signals that SOME bytes are ready, not a whole
        line, so a worker that emits a partial line then wedges would
        block a plain ``readline`` forever.  Accumulate bytes until the
        first ``\\n`` under the same wall-clock budget; bytes past it
        (there should be none under strict ping-pong) are kept in
        ``_inbuf`` for the next response.
        """
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
        """Lex one module source; ``None`` means "use the regex fallback"."""
        if self._disabled or os.name != "posix":
            return None
        with self._lock:
            # One respawn per request: a worker killed mid-request (OOM,
            # operator) recovers transparently.  A spawn failure (no node /
            # OSError) disables immediately — the environment cannot run it.
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
                # Success resets the consecutive-failure streak.
                self._consec_failures = 0
                if not response.get("ok"):
                    # The SOURCE doesn't lex (syntax error) — a per-module
                    # condition, not a worker failure.  Fall back for this
                    # module only; the worker stays up.
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
    """Register :func:`close_lexer_worker` for interpreter exit and server stop.

    Mirrors ``sass_embedded.get_sass_compiler``: ``atexit`` covers plain
    interpreter exit; ``CommonServer.on_stop`` hooks run before the server's
    lingering-child check, so the worker is stopped by its owner during a
    graceful stop instead of tripping the "process may hang" warning. Lazy
    import: this tool sits below ``odoo.service``, and the hook is only
    needed when a server is running.
    """
    global _cleanup_registered  # noqa: PLW0603  # one-shot lazy registration
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
    """Shut down the persistent node worker if one is running.

    The worker is deliberately long-lived (spawning node per module would cost
    more than the lexing), but it is a child of the Odoo process, so anything
    that audits leftover children sees it. ``BaseCase`` does exactly that at
    class teardown and logged "A child process was found, terminating it:
    node-MainThread" once per browser-test class; call this first, like
    ``close_sass_compiler``, so the worker is stopped by its owner rather than
    reported as a leak.
    """
    _worker.close()


def lex_module(src: str) -> dict[str, Any] | None:
    """Lex one ES module source through the persistent worker.

    :param src: JS source text
    :return: ``{"names": [...], "hasDefault": bool, "starFrom": [...],
        "imports": [{"n": spec, "kind": "named|default|star|side"}]}``,
        or ``None`` when unavailable — callers MUST fall back to the
        regex extractor.
    """
    return _worker.request(src)

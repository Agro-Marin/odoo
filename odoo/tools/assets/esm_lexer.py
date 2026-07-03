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

import contextlib
import json
import logging
import os
import select
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any

import odoo
from odoo.libs.asset_log import get_asset_logger, log_event

_lexer_log = get_asset_logger("lexer")

_WORKER_SCRIPT = Path(__file__).parent / "js" / "esm_lexer_worker.mjs"

# Per-request budget.  Lexing is sub-millisecond; the timeout only exists
# so a wedged worker degrades to the regex path instead of pinning a
# server worker.  Generous because the FIRST request also pays node
# startup + WASM init.
_REQUEST_TIMEOUT_S = 10.0


class _LexerWorker:
    """One persistent worker subprocess with respawn-once semantics."""

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._counter = 0
        self._disabled = False
        self._lock = threading.Lock()

    def _spawn(self) -> subprocess.Popen | None:
        node = shutil.which("node")
        if not node:
            return None
        odoo_root = Path(odoo.__path__[0]).parent
        try:
            return subprocess.Popen(
                [node, str(_WORKER_SCRIPT)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                # node resolves ``es-module-lexer`` against the Odoo
                # root's node_modules (same install that provides esbuild).
                cwd=odoo_root,
            )
        except OSError:
            return None

    def _kill(self) -> None:
        proc, self._proc = self._proc, None
        if proc is not None:
            with contextlib.suppress(OSError):
                proc.kill()

    def request(self, src: str) -> dict[str, Any] | None:
        """Lex one module source; ``None`` means "use the regex fallback"."""
        if self._disabled or os.name != "posix":
            return None
        with self._lock:
            # One respawn: a worker killed mid-request (OOM, operator)
            # recovers transparently; two consecutive spawn failures mean
            # the environment can't run it — disable for the process.
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
                try:
                    proc.stdin.write(json.dumps({"id": request_id, "src": src}) + "\n")
                    proc.stdin.flush()
                    # Ping-pong means the stdout buffer is empty before
                    # each request, so a raw fd select is a faithful
                    # readiness signal despite Python-level buffering.
                    ready, _, _ = select.select(
                        [proc.stdout], [], [], _REQUEST_TIMEOUT_S
                    )
                    if not ready:
                        raise TimeoutError("lexer worker timed out")
                    line = proc.stdout.readline()
                    if not line:
                        raise EOFError("lexer worker closed stdout")
                    response = json.loads(line)
                    if response.get("id") != request_id:
                        raise ValueError("lexer worker desynchronized")
                except Exception as exc:
                    log_event(
                        _lexer_log,
                        logging.WARNING,
                        "worker_request_failed",
                        err=type(exc).__name__,
                        attempt=_attempt + 1,
                    )
                    self._kill()
                    continue
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


def lex_module(src: str) -> dict[str, Any] | None:
    """Lex one ES module source through the persistent worker.

    :param src: JS source text
    :return: ``{"names": [...], "hasDefault": bool, "starFrom": [...],
        "imports": [{"n": spec, "kind": "named|default|star|side"}]}``,
        or ``None`` when unavailable — callers MUST fall back to the
        regex extractor.
    """
    return _worker.request(src)

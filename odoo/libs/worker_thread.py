"""Typed view of the per-request bookkeeping Odoo attaches to worker threads.

Odoo stores the identity of the work a thread is doing — the database, the
acting user, the URL, timing counters — as attributes on the
``threading.Thread`` object itself, and reads them back from the logger
(:mod:`odoo.logutils`), the profiler and the server watchdog. Nothing declared
that set anywhere, so every reader defends itself with ``hasattr`` /
``getattr(..., default)`` and no type checker can see the attributes at all.

This module declares the contract once. It does **not** move the state:
:func:`current_worker_thread` returns the very object
``threading.current_thread()`` returns, only typed, so readers that have not
adopted it keep working untouched and adoption can proceed file by file.

The attributes are declared as present because that is what
``Application._reset_thread_state`` guarantees for the duration of a request.
Outside one — a bare interpreter thread, or before the first reset — they are
absent, which is why unconverted readers guard.
"""

from __future__ import annotations

import threading
from typing import Protocol, cast


class WorkerThread(Protocol):
    """The bookkeeping a thread carries while serving a request or job.

    :param dbname: database being served, absent when none is bound.
    :param uid: acting user, ``None`` before authentication.
    :param url: the URL being served, absent until routing has resolved it.
    :param query_count: SQL statements issued so far.
    :param query_time: seconds spent in SQL so far.
    :param perf_t0: wall-clock start, for the perf log line.
    :param cursor_mode: ``"ro"``, ``"rw"`` or ``"ro->rw"`` once a cursor is open.
    :param rpc_model_method: ``model.method`` being dispatched, for the log line.
    """

    dbname: str
    uid: int | None
    url: str
    query_count: int
    query_time: float
    perf_t0: float
    cursor_mode: str | None
    rpc_model_method: str


def current_worker_thread() -> WorkerThread:
    """The current thread, typed as carrying Odoo's per-request bookkeeping."""
    return cast("WorkerThread", threading.current_thread())

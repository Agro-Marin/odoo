"""The per-thread context Odoo hangs off :class:`threading.Thread`.

Typed in one place so the rest of the tree can read and write it without
every access being an ``attr-defined`` error against a ``Thread`` that
declares none of these names.
"""

from __future__ import annotations

import threading
from typing import Protocol, cast


class WorkerThread(Protocol):
    """The state Odoo attaches to :class:`threading.Thread` instances.

    Odoo carries per-thread request/cron context as plain attributes on the
    thread object rather than in a :class:`threading.local`, because the prefork
    and threaded servers both need to read another thread's context (the watcher
    prints ``type`` and ``start_time`` for every live worker). This Protocol is
    the only declaration of that vocabulary; without it every read is an
    ``attr-defined`` error, because ``Thread`` declares none of it.

    **Every member here is optional in practice**, and ``dbname`` visibly so:
    ``ir_cron`` and ``ir_job`` bind it around a job and ``del`` it afterwards
    (``ir_cron.py:266``, ``ir_job.py:586``), restoring any previous value. So a
    reader that has not itself set the attribute must use ``getattr(t, ..., d)``
    rather than trust the declaration -- the Protocol describes the vocabulary,
    not a guarantee that any given thread has been through the code that binds
    it. Declaring them as non-optional is deliberate: it keeps the *setter* side
    honest, and a reader reaching for a name not in this list is the case worth
    catching.
    """

    dbname: str
    uid: int | None
    url: str
    query_count: int
    query_time: float
    perf_t0: float
    cursor_mode: str | None
    rpc_model_method: str

    #: Which server loop owns the thread -- ``"cron"`` / ``"job"`` / ``"http"``.
    #: Set by ThreadedServer.cron_spawn / job_spawn and read by the watcher.
    type: str

    #: ``time.monotonic()`` when the thread began its current unit of work, or
    #: ``None`` between units. The threaded server's watchdog reads it to find
    #: threads that have overrun.
    start_time: float | None

    #: The profiler's saved ExecutionContext, swapped in and out around a
    #: profiled block (``tools/profiler.py``).
    exec_context: object


def as_worker_thread(thread: threading.Thread) -> WorkerThread:
    """View *thread* as a :class:`WorkerThread`.

    For the sites that bind this state onto a thread that is not the caller --
    the server spawning a cron or job worker, ``model.py`` stamping the dispatch
    context. ``cast`` rather than a wrapper: the attributes really do live on
    the ``Thread`` object, and interposing anything would change where.
    """
    return cast("WorkerThread", thread)


def current_worker_thread() -> WorkerThread:
    """View the calling thread as a :class:`WorkerThread`."""
    return as_worker_thread(threading.current_thread())

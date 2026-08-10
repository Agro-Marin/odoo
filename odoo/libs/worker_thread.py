from __future__ import annotations

import threading
from typing import Protocol, cast


class WorkerThread(Protocol):
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
    return cast("WorkerThread", thread)


def current_worker_thread() -> WorkerThread:
    return as_worker_thread(threading.current_thread())

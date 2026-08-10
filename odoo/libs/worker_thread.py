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

    type: str

    start_time: float | None

    exec_context: object


def as_worker_thread(thread: threading.Thread) -> WorkerThread:
    return cast("WorkerThread", thread)


def current_worker_thread() -> WorkerThread:
    return as_worker_thread(threading.current_thread())

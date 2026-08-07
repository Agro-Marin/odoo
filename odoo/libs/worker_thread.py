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


def current_worker_thread() -> WorkerThread:
    return cast("WorkerThread", threading.current_thread())

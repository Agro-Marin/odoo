from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = [
    "WorkerThread",
    "as_worker_thread",
    "current_worker_thread",
    "working_on_database",
]


class WorkerThread(Protocol):
    dbname: str | None
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


_ABSENT = object()


@contextmanager
def working_on_database(db_name: str) -> Iterator[None]:
    # The sentinel is what separates "the attribute was not set" from "it was
    # set to None" -- `http.helpers.dispatch_rpc` sets `thread.dbname = None`
    # outright, and restoring by `getattr(..., None)` would delete it instead of
    # putting the None back.
    worker = as_worker_thread(threading.current_thread())
    previous = getattr(worker, "dbname", _ABSENT)
    worker.dbname = db_name
    try:
        yield
    finally:
        if previous is _ABSENT:
            if hasattr(worker, "dbname"):
                del worker.dbname
        else:
            worker.dbname = previous

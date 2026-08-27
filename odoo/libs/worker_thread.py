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


@contextmanager
def working_on_database(db_name: str) -> Iterator[None]:
    """Mark this thread as working on ``db_name`` for as long as the block runs.

    The marker is what the log formatter prefixes every line with, so a worker
    that polls several databases in turn has to put back whatever was there --
    including the absence of an attribute, which is not the same as ``None``.
    """
    # Through this module's own typed view, not the bare `Thread`: `dbname` is
    # an attribute this fork bolts on, and `as_worker_thread` is the whole
    # reason the file exists. Writing it on `threading.Thread` here made the
    # accessor something only OTHER modules had to use -- two `attr-defined`
    # errors, in the module that publishes the fix for them.
    worker = as_worker_thread(threading.current_thread())
    previous = getattr(worker, "dbname", None)
    worker.dbname = db_name
    try:
        yield
    finally:
        if previous is None:
            if hasattr(worker, "dbname"):
                del worker.dbname
        else:
            worker.dbname = previous

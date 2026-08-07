__all__ = ["disabling_gc", "gc_info", "gc_set_timing"]

import contextlib
import gc
import logging
from time import thread_time_ns as _gc_time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Generator

_logger = logging.getLogger("gc")
_gc_start: int = 0
_gc_init_stats: list[dict[str, int]] = gc.get_stats()
_gc_timings: list[int] = [0, 0, 0]


def _to_ms(ns: float) -> float:
    return round(ns / 1_000_000, 2)


def _timing_gc_callback(event: str, info: dict[str, Any]) -> None:
    if _gc_time is None:
        return
    global _gc_start  # noqa: PLW0603  gc callbacks run on the collecting thread and own this state
    gen = info["generation"]
    if event == "start":
        _gc_start = _gc_time()
        if gen == 2 and _logger.isEnabledFor(logging.DEBUG):
            _logger.debug("info %s, starting collection of gen2", gc_info())
    else:
        timing = _gc_time() - _gc_start
        _gc_timings[gen] += timing
        _gc_start = 0
        if gen > 0:
            _logger.debug("collected %s in %.2fms", info, _to_ms(timing))


def gc_set_timing(*, enable: bool) -> None:
    if _timing_gc_callback in gc.callbacks:
        if enable:
            return
        gc.callbacks.remove(_timing_gc_callback)
    elif enable:
        global _gc_init_stats, _gc_timings  # noqa: PLW0603  gc callback state, as above
        _gc_init_stats = gc.get_stats()
        _gc_timings = [0, 0, 0]
        gc.callbacks.append(_timing_gc_callback)


def gc_info() -> dict[str, Any]:
    stats = gc.get_stats()
    times = []
    cumulative_time = sum(_gc_timings) or 1
    for info, info_init, time in zip(stats, _gc_init_stats, _gc_timings, strict=False):
        count = info["collections"] - info_init["collections"]
        times.append(
            {
                "avg_time_ms": _to_ms(time / count) if count > 0 else 0.0,
                "time_ms": _to_ms(time),
                "share": round(time / cumulative_time, 3),
            }
        )
    return {
        "cumulative_time": _to_ms(cumulative_time),
        "time": times if _timing_gc_callback in gc.callbacks else (),
        "count": stats,
        "thresholds": (gc.get_count(), gc.get_threshold()),
    }


@contextlib.contextmanager
def disabling_gc() -> Generator[bool]:
    if not gc.isenabled():
        yield False
        return
    gc.disable()
    _logger.debug("disabled, counts %s", gc.get_count())
    try:
        yield True
    finally:
        counts = gc.get_count()
        gc.enable()
        _logger.debug("enabled, counts %s", counts)

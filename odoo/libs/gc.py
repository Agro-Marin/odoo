__all__ = ["disabling_gc", "freeze_survivors", "gc_set_timing", "thaw"]

import contextlib
import gc
import logging
from time import thread_time_ns as _gc_time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Generator

_logger = logging.getLogger("odoo.gc")
_gc_start: int = 0
_gc_init_stats: list[dict[str, int]] = gc.get_stats()
_gc_timings: list[int] = [0, 0, 0]


def _to_ms(ns: float) -> float:
    return round(ns / 1_000_000, 2)


def _record_gc_timing(event: str, info: dict[str, Any]) -> None:
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
    if _record_gc_timing in gc.callbacks:
        if enable:
            return
        gc.callbacks.remove(_record_gc_timing)
    elif enable:
        global _gc_init_stats, _gc_timings  # noqa: PLW0603  gc callback state, as above
        _gc_init_stats = gc.get_stats()
        _gc_timings = [0, 0, 0]
        gc.callbacks.append(_record_gc_timing)


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
        "time": times if _record_gc_timing in gc.callbacks else (),
        "count": stats,
        "thresholds": (gc.get_count(), gc.get_threshold()),
    }


def freeze_survivors() -> int:
    # Long-lived objects (a registry's models, fields and compiled caches) are
    # otherwise re-examined by every collection: a gen-1 pass over a warm server
    # took ~250 ms and stalled every request thread. Collect first, so garbage
    # is not frozen with them.
    started = _gc_time()
    gc.collect()
    gc.freeze()
    frozen = gc.get_freeze_count()
    _logger.debug("froze %d objects in %.2fms", frozen, _to_ms(_gc_time() - started))
    return frozen


def thaw() -> None:
    # A frozen object is never collected, so anything dropped after a freeze --
    # a removed registry -- must be thawed or it stays in memory for good.
    gc.unfreeze()


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

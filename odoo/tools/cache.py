import functools
import logging
import os
import signal
import sys
import threading
import time
import typing
import warnings
from collections import defaultdict
from collections.abc import Callable, Collection, Iterable, Mapping
from inspect import Parameter, signature
from typing import Any

C = typing.TypeVar("C", bound=Callable)

if typing.TYPE_CHECKING:
    from odoo.libs.lru import LRU
    from odoo.models import BaseModel

unsafe_eval = eval  # noqa: S307  # eval used intentionally to compile cache-key getters

_logger = logging.getLogger(__name__)
_logger_lock = threading.RLock()
_logger_state: typing.Literal["wait", "abort", "run"] = "wait"


class ormcache_counter:
    """Statistic counters for cache entries."""

    __slots__ = [
        "cache_name",
        "err",
        "gen_time",
        "hit",
        "miss",
        "tx_err",
        "tx_hit",
        "tx_miss",
    ]

    def __init__(self) -> None:
        self.hit: int = 0
        self.miss: int = 0
        self.err: int = 0
        self.gen_time: float = 0.0
        self.cache_name: str = ""
        self.tx_hit: int = 0
        self.tx_miss: int = 0
        self.tx_err: int = 0

    @property
    def ratio(self) -> float:
        return 100.0 * self.hit / (self.hit + self.miss or 1)

    @property
    def tx_ratio(self) -> float:
        return 100.0 * self.tx_hit / (self.tx_hit + self.tx_miss or 1)

    @property
    def tx_calls(self) -> int:
        return self.tx_hit + self.tx_miss


_COUNTERS: defaultdict[tuple[str, Callable], ormcache_counter] = defaultdict(
    ormcache_counter
)
"""Statistic counters, mapping (dbname, method) to counter."""


def prune_counters(db_name: str) -> None:
    """Drop the ormcache stat counters for a deleted database.

    ``_COUNTERS`` is keyed by ``(db_name, method)`` and would otherwise grow
    unbounded on a process that creates and drops many databases. Called from
    ``Registry.delete``.
    """
    for cache_key in [k for k in _COUNTERS if k[0] == db_name]:
        del _COUNTERS[cache_key]


# Per-transaction hit/miss statistics toggle.
#
# Raw hit/miss/error counters, cache sizes and generation time are always
# collected -- a couple of integer increments per call. The per-transaction
# stats (the "TX Hit Ratio" and "TX Call" columns dumped by log_ormcache_stats
# on SIGUSR1) are OFF by default: on the hottest cache path they hash every
# cache-key element into a per-cursor set, roughly doubling the cost of a hit
# (~225 vs ~215 ns/op measured) and growing an unbounded _ormcache_lookups set
# per transaction. Enable only when you need the per-transaction dedup ratio,
# via the environment before start-up::
#
#     ODOO_ORMCACHE_TX_STATS=1
#
# or at runtime before sending SIGUSR1::
#
#     import odoo.tools.cache as c
#     c._TX_STATS_ENABLED = True
#
# The lookup closure reads this flag on every call, so a runtime flip takes
# effect immediately (no restart, no re-decoration).
_TX_STATS_ENABLED: bool = os.environ.get(
    "ODOO_ORMCACHE_TX_STATS", ""
).strip().lower() in ("1", "true", "yes", "on")


class ormcache:
    """LRU cache decorator for model methods.
    The parameters are strings that represent expressions referring to the
    signature of the decorated method, and are used to compute a cache key::

        @ormcache("model_name", "mode")
        def _compute_domain(self, model_name, mode="read"): ...

    For backward compatibility, the decorator supports the named parameter
    `skiparg`::

        @ormcache(skiparg=1)
        def _compute_domain(self, model_name, mode="read"): ...

    Methods implementing this decorator should never return a Recordset,
    because the underlying cursor will eventually be closed and raise a
    `psycopg.InterfaceError`.
    """

    key: Callable[..., tuple]

    def __init__(
        self,
        *args: str,
        cache: str = "default",
        skiparg: int | None = None,
        **kwargs: Any,
    ) -> None:
        self.args = args
        self.skiparg = skiparg
        self.cache_name = cache
        if skiparg is not None:
            warnings.warn(
                "Deprecated since 19.0, ormcache(skiparg) will be removed",
                DeprecationWarning,
                stacklevel=2,
            )

    def __call__(self, method: C) -> C:
        assert not hasattr(self, "method"), "ormcache is already bound to a method"
        self.method = method
        self.determine_key()
        assert self.key is not None, "ormcache.key not initialized"

        # Close over constants to eliminate attribute lookups from the hot
        # path.  These are fixed for the lifetime of the decorated method.
        _key = self.key
        _method = method
        _cache_name = self.cache_name
        _counters = _COUNTERS
        _monotonic = time.monotonic
        _warn = _logger.warning

        @functools.wraps(method)
        def lookup(*args, **kwargs):
            model = args[0]
            pool = model.pool
            d = pool._Registry__caches[_cache_name]
            key = _key(*args, **kwargs)
            counter = _counters[pool.db_name, _method]
            counter.cache_name = _cache_name

            if not _TX_STATS_ENABLED:
                # Fast path: always-on raw counters only. The per-transaction
                # dedup stats (tx_hit/tx_miss) are skipped -- see _TX_STATS_ENABLED.
                try:
                    r = d[key]
                    counter.hit += 1
                    return r
                except KeyError:
                    counter.miss += 1
                except TypeError:
                    _warn("cache lookup error on %r", key, exc_info=True)
                    counter.err += 1
                    return _method(*args, **kwargs)
            else:
                # Full path: additionally collect per-transaction dedup stats.
                # get() + conditional set is faster than setdefault() when the
                # key usually exists (>99%).
                cr_cache = model.env.cr.cache
                tx_lookups = cr_cache.get("_ormcache_lookups")
                if tx_lookups is None:
                    tx_lookups = set()
                    cr_cache["_ormcache_lookups"] = tx_lookups

                tx_first = False
                try:
                    # store hashes, not the key itself, so we don't keep hard
                    # references that prevent cached objects from being collected.
                    # An unhashable key element raises TypeError here and routes to
                    # the uncached fallback below (like the d[key] miss), instead of
                    # crashing the call before the try/except can catch it.
                    tx_key = tuple(map(hash, key))
                    tx_first = tx_key not in tx_lookups
                    if tx_first:
                        tx_lookups.add(tx_key)
                    r = d[key]
                    counter.hit += 1
                    counter.tx_hit += tx_first
                    return r
                except KeyError:
                    counter.miss += 1
                    counter.tx_miss += tx_first
                except TypeError:
                    _warn("cache lookup error on %r", key, exc_info=True)
                    counter.err += 1
                    # the error is the event to count; ``tx_first`` is still
                    # False here because the raising line runs before it is set.
                    counter.tx_err += 1
                    return _method(*args, **kwargs)

            # Snapshot the clear-generation before computing: if the cache is
            # cleared (invalidated) while ``_method`` runs, storing the value
            # would re-cache pre-invalidation data that survives until the next
            # unrelated clear. Skip the store in that case; the value returned
            # to this caller is still correct, it is just not cached.
            generation = d.generation
            start = _monotonic()
            value = _method(*args, **kwargs)
            counter.gen_time += _monotonic() - start
            if d.generation == generation:
                d[key] = value
            return value

        lookup.__cache__ = self  # type: ignore[attr-defined]
        return lookup

    def add_value(self, *args: Any, cache_value: Any = None, **kwargs: Any) -> None:
        model: BaseModel = args[0]
        d: LRU = model.pool._Registry__caches[self.cache_name]  # type: ignore[attr-defined]
        key = self.key(*args, **kwargs)
        d[key] = cache_value

    def determine_key(self) -> None:
        """Determine the function that computes a cache key from arguments."""
        assert self.method is not None
        if self.skiparg is not None:
            # backward-compatible function that uses self.skiparg
            self.key = lambda *args, **kwargs: (
                args[0]._name,
                self.method,
                *args[self.skiparg :],
            )
            return
        # build a string that represents function code and evaluate it
        args = ", ".join(
            # remove annotations because lambdas can't be type-annotated,
            str(params.replace(annotation=Parameter.empty))
            for params in signature(self.method).parameters.values()
        )
        values = ["self._name", "method", *self.args]
        code = f"lambda {args}: ({''.join(a for arg in values for a in (arg, ','))})"
        self.key = unsafe_eval(code, {"method": self.method})


class ormcache_context(ormcache):
    """Variant of :class:`ormcache` with an extra ``keys`` parameter that
    defines a sequence of dictionary keys. Those keys are looked up in the
    ``context`` parameter and combined into the cache key made by
    :class:`ormcache`.
    """

    def __init__(
        self, *args: str, keys: tuple[str, ...], skiparg: None = None, **kwargs: Any
    ) -> None:
        assert skiparg is None, "ormcache_context() no longer supports skiparg"
        warnings.warn(
            "Since 19.0, use ormcache directly, context values are available as `self.env.context.get`",
            DeprecationWarning,
            stacklevel=2,
        )
        self.keys = keys
        super().__init__(*args, **kwargs)

    def determine_key(self) -> None:
        assert self.method is not None
        sign = signature(self.method)
        cont_expr = (
            "(context or {})" if "context" in sign.parameters else "self.env.context"
        )
        keys_expr = "tuple(%s.get(k) for k in %r)" % (cont_expr, self.keys)
        self.args += (keys_expr,)
        super().determine_key()


def log_ormcache_stats(
    sig: int | None = None,
    frame: Any = None,
) -> None:
    # collect and log data in a separate thread to avoid blocking the main thread
    # and avoid using logging module directly in the signal handler
    # https://docs.python.org/3/library/logging.html#thread-safety
    global _logger_state  # noqa: PLW0603
    with _logger_lock:
        if _logger_state != "wait":
            # send the signal again to stop the logging thread
            _logger_state = "abort"
            return
        _logger_state = "run"

    def check_continue_logging() -> bool:
        if _logger_state == "run":
            return True
        _logger.info("Stopping logging ORM cache stats")
        return False

    class StatsLine:
        def __init__(self, method: Callable, counter: ormcache_counter) -> None:
            self.sz_entries_sum: int = 0
            self.sz_entries_max: int = 0
            self.nb_entries: int = 0
            self.counter = counter
            self.method = method

    def _log_ormcache_stats() -> None:
        """Log statistics of ormcache usage by database, model, and method."""
        from odoo.modules.registry import Registry

        try:
            # {dbname: {method: StatsLine}}
            cache_stats: defaultdict[str, dict[Callable, StatsLine]] = defaultdict(dict)
            # {dbname: (cache_name, entries, count, total_size)}
            cache_usage: defaultdict[str, list[tuple[str, int, int, int]]] = (
                defaultdict(list)
            )

            # browse the values in cache
            registries = Registry.registries.snapshot
            class_slots = {}
            for i, (dbname, registry) in enumerate(registries.items(), start=1):
                if not check_continue_logging():
                    return
                _logger.info(
                    "Processing database %s (%d/%d)", dbname, i, len(registries)
                )
                db_cache_stats = cache_stats[dbname]
                db_cache_usage = cache_usage[dbname]
                for cache_name, cache in registry._Registry__caches.items():
                    cache_total_size = 0
                    for cache_key, cache_value in cache.snapshot.items():
                        method = cache_key[1]
                        stats = db_cache_stats.get(method)
                        if stats is None:
                            stats = db_cache_stats[method] = StatsLine(
                                method, _COUNTERS[dbname, method]
                            )
                        stats.nb_entries += 1
                        if not show_size:
                            continue
                        size = get_cache_size(
                            (cache_key, cache_value),
                            cache_info=method.__qualname__,
                            class_slots=class_slots,
                        )
                        cache_total_size += size
                        stats.sz_entries_sum += size
                        stats.sz_entries_max = max(stats.sz_entries_max, size)
                    db_cache_usage.append(
                        (cache_name, len(cache), cache.count, cache_total_size)
                    )

            # add counters that have no values in cache
            for (
                (
                    dbname,
                    method,
                ),
                counter,
            ) in _COUNTERS.copy().items():  # copy to avoid concurrent modification
                if not check_continue_logging():
                    return
                db_cache_stats = cache_stats[dbname]
                stats = db_cache_stats.get(method)
                if stats is None:
                    db_cache_stats[method] = StatsLine(method, counter)

            # Output the stats
            log_msgs = ["Caches stats:"]
            if not _TX_STATS_ENABLED:
                # The TX columns below stay at 0 / 100% unless per-transaction
                # stats collection is enabled (ODOO_ORMCACHE_TX_STATS=1); say so
                # rather than let the reader mistake it for a perfect ratio.
                log_msgs.append(
                    "(TX Hit Ratio / TX Call disabled — set ODOO_ORMCACHE_TX_STATS=1"
                    " to collect per-transaction stats)"
                )
            size_column_info = (
                (f"{'Memory %':>10},{'Memory SUM':>12},{'Memory MAX':>12},")
                if show_size
                else ""
            )
            column_info = (
                f"{'Cache Name':>25},"
                f"{'Entry':>7},"
                f"{size_column_info}"
                f"{'Hit':>6},"
                f"{'Miss':>6},"
                f"{'Err':>6},"
                f"{'Gen Time [s]':>13},"
                f"{'Hit Ratio':>10},"
                f"{'TX Hit Ratio':>13},"
                f"{'TX Call':>8},"
                "  Method"
            )

            for dbname, db_cache_stats in sorted(
                cache_stats.items(), key=lambda k: k[0] or "~"
            ):
                if not check_continue_logging():
                    return
                log_msgs.append(f"Database {dbname or '<no_db>'}:")
                log_msgs.extend(
                    f" * {cache_name}: {entries}/{count}{' (' if cache_total_size else ''}{cache_total_size}{' bytes)' if cache_total_size else ''}"
                    for cache_name, entries, count, cache_total_size in cache_usage[
                        dbname
                    ]
                )
                log_msgs.append("Details:")

                # sort by -sz_entries_sum and method_name
                db_cache_stat = sorted(
                    db_cache_stats.items(),
                    key=lambda k: (-k[1].sz_entries_sum, k[0].__name__),
                )
                sz_entries_all = sum(stat.sz_entries_sum for _, stat in db_cache_stat)
                log_msgs.append(column_info)
                for method, stat in db_cache_stat:
                    size_data = (
                        (
                            f"{stat.sz_entries_sum / (sz_entries_all or 1) * 100:9.1f}%,"
                            f"{stat.sz_entries_sum:12d},"
                            f"{stat.sz_entries_max:12d},"
                        )
                        if show_size
                        else ""
                    )
                    log_msgs.append(
                        f"{stat.counter.cache_name:>25},"
                        f"{stat.nb_entries:7d},"
                        f"{size_data}"
                        f"{stat.counter.hit:6d},"
                        f"{stat.counter.miss:6d},"
                        f"{stat.counter.err:6d},"
                        f"{stat.counter.gen_time:13.3f},"
                        f"{stat.counter.ratio:9.1f}%,"
                        f"{stat.counter.tx_ratio:12.1f}%,"
                        f"{stat.counter.tx_calls:8d},"
                        f"  {method.__qualname__}"
                    )
            _logger.info("\n".join(log_msgs))
        except Exception:
            _logger.exception("error while logging ormcache statistics")
        finally:
            global _logger_state  # noqa: PLW0603
            with _logger_lock:
                _logger_state = "wait"

    show_size = False
    # ``None`` is the manual entry point (e.g. from the odoo shell); treat it
    # like SIGUSR1 so a direct call actually logs instead of leaving the state
    # machine stuck in "run" (which would make every later signal abort).
    if sig in (None, signal.SIGUSR1):
        threading.Thread(
            target=_log_ormcache_stats, name="odoo.signal.log_ormcache_stats"
        ).start()
    elif sig == signal.SIGUSR2:
        show_size = True
        threading.Thread(
            target=_log_ormcache_stats,
            name="odoo.signal.log_ormcache_stats_with_size",
        ).start()
    else:
        # Unknown signal: no worker thread will run its ``finally`` to reset the
        # state, so reset it here or the feature bricks until process restart.
        with _logger_lock:
            _logger_state = "wait"


def get_cache_size(
    obj: Any,
    *,
    cache_info: str = "",
    seen_ids: set[int] | None = None,
    class_slots: dict[int, Iterable[str]] | None = None,
) -> int:
    """A non-thread-safe recursive object size estimator"""
    from odoo.api import Environment
    from odoo.models import BaseModel

    if seen_ids is None:
        # count internal constants as 0 bytes
        seen_ids = set(map(id, (None, False, True)))
    if class_slots is None:
        class_slots = {}  # {class_id: combined_slots}
    total_size = 0
    objects = [obj]

    while objects:
        cur_obj = objects.pop()
        if id(cur_obj) in seen_ids:
            continue

        if cache_info and isinstance(cur_obj, (BaseModel, Environment)):
            _logger.error("%s is cached by %s", cur_obj, cache_info)
            continue

        seen_ids.add(id(cur_obj))
        total_size += sys.getsizeof(cur_obj)

        if hasattr(cur_obj, "__slots__"):
            cur_obj_cls = type(cur_obj)
            attributes = class_slots.get(id(cur_obj_cls))
            if attributes is None:
                class_slots[id(cur_obj_cls)] = attributes = tuple(
                    {
                        (f"_{cls.__name__}{attr}" if attr.startswith("__") else attr)
                        for cls in cur_obj_cls.mro()
                        for attr in getattr(cls, "__slots__", ())
                    }
                )
            objects.extend(getattr(cur_obj, attr, None) for attr in attributes)
        if hasattr(cur_obj, "__dict__"):
            objects.append(cur_obj.__dict__)

        if isinstance(cur_obj, Mapping):
            objects.extend(cur_obj.values())
            objects.extend(cur_obj.keys())
        elif isinstance(cur_obj, Collection) and not isinstance(
            cur_obj, (str, bytes, bytearray)
        ):
            objects.extend(cur_obj)

    return total_size

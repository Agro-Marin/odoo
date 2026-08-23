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
from collections.abc import Callable, Collection, Mapping
from inspect import Parameter, signature
from typing import Any

from .constants import REGISTRY_CACHES

C = typing.TypeVar("C", bound=Callable)

if typing.TYPE_CHECKING:
    from odoo.libs.lru import LRU
    from odoo.models import BaseModel

unsafe_eval = eval  # noqa: S307  ormcache key expressions built from code, not user input

_logger = logging.getLogger(__name__)

#: Reserved parameter-name prefix; see `ormcache.determine_key`.
_RESERVED = "__ormcache_"
_METHOD_NAME = f"{_RESERVED}method"
_logger_lock = threading.RLock()
_logger_state: typing.Literal["wait", "abort", "run"] = "wait"


class ormcache_counter:
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


def prune_counters(db_name: str) -> None:
    for cache_key in [k for k in _COUNTERS if k[0] == db_name]:
        del _COUNTERS[cache_key]


_TX_STATS_ENABLED: bool = os.environ.get(
    "ODOO_ORMCACHE_TX_STATS", ""
).strip().lower() in ("1", "true", "yes", "on")


def _render_signature(method: Callable) -> tuple[str, dict[str, Any]]:
    rendered: list[str] = []
    arg_globals: dict[str, Any] = {}
    params = list(signature(method).parameters.values())
    prev_kind = None
    for index, param in enumerate(params):
        if (
            prev_kind == Parameter.POSITIONAL_ONLY
            and param.kind != Parameter.POSITIONAL_ONLY
        ):
            rendered.append("/")
        if param.kind == Parameter.KEYWORD_ONLY and prev_kind not in (
            Parameter.VAR_POSITIONAL,
            Parameter.KEYWORD_ONLY,
        ):
            rendered.append("*")

        if param.kind == Parameter.VAR_POSITIONAL:
            rendered.append(f"*{param.name}")
        elif param.kind == Parameter.VAR_KEYWORD:
            rendered.append(f"**{param.name}")
        elif param.default is Parameter.empty:
            rendered.append(param.name)
        else:
            placeholder = f"{_RESERVED}default_{index}"
            arg_globals[placeholder] = param.default
            rendered.append(f"{param.name}={placeholder}")
        prev_kind = param.kind

    if prev_kind == Parameter.POSITIONAL_ONLY:
        rendered.append("/")
    return ", ".join(rendered), arg_globals


class ormcache:
    key: Callable[..., tuple]

    def __init__(
        self,
        *args: str,
        cache: str = "default",
        skiparg: int | None = None,
    ) -> None:
        self.args = args
        self.skiparg = skiparg
        if cache not in REGISTRY_CACHES:
            raise ValueError(
                f"@ormcache(cache={cache!r}): unknown cache. Valid buckets: "
                f"{', '.join(sorted(REGISTRY_CACHES))}"
            )
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
            d = pool.ormcache_lrus[_cache_name]
            key = _key(*args, **kwargs)
            counter = _counters[pool.db_name, _method]
            counter.cache_name = _cache_name

            if not _TX_STATS_ENABLED:
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
                cr_cache = model.env.cr.cache
                tx_lookups = cr_cache.get("_ormcache_lookups")
                if tx_lookups is None:
                    tx_lookups = set()
                    cr_cache["_ormcache_lookups"] = tx_lookups

                tx_first = False
                try:
                    # hash(key), not the key itself: the set must not pin the
                    # cached objects alive for the transaction. A per-element
                    # hash tuple did the same job while colliding more.
                    tx_key = hash(key)
                    tx_first = tx_key not in tx_lookups
                    if tx_first:
                        tx_lookups.add(tx_key)
                    r = d[key]
                    counter.hit += 1
                    counter.tx_hit += int(tx_first)
                    return r
                except KeyError:
                    counter.miss += 1
                    counter.tx_miss += int(tx_first)
                except TypeError:
                    _warn("cache lookup error on %r", key, exc_info=True)
                    counter.err += 1
                    counter.tx_err += 1
                    return _method(*args, **kwargs)

            generation = d.generation
            start = _monotonic()
            value = _method(*args, **kwargs)
            counter.gen_time += _monotonic() - start
            if d.generation == generation:
                d[key] = value
            return value

        lookup.__cache__ = self
        return lookup

    def add_value(
        self,
        *args: Any,
        cache_value: Any = None,
        generation: int | None = None,
        **kwargs: Any,
    ) -> None:
        model: BaseModel = args[0]
        d: LRU = model.pool.ormcache_lrus[self.cache_name]
        key = self.key(*args, **kwargs)
        if generation is not None and d.generation != generation:
            return
        d[key] = cache_value

    def generation_of(self, model: BaseModel) -> int:
        return model.pool.ormcache_lrus[self.cache_name].generation

    def determine_key(self) -> None:
        assert self.method is not None
        if self.skiparg is not None:
            self.key = lambda *args, **kwargs: (
                args[0]._name,
                self.method,
                *args[self.skiparg :],
            )
            return
        args, arg_globals = _render_signature(self.method)
        parameters = signature(self.method).parameters
        first_param = next(iter(parameters), "self")
        # The key expression names the decorated function, and each defaulted
        # parameter, through a global. A parameter sharing one of those names
        # would shadow it, and the cache would silently key on the argument
        # instead. The whole `_ormcache_` prefix is reserved so that one check
        # covers the method name and every generated default alike.
        if colliding := sorted(p for p in parameters if p.startswith(_RESERVED)):
            msg = (
                f"@ormcache cannot decorate {self.method.__qualname__}: its "
                f"parameter(s) {', '.join(colliding)} use the reserved "
                f"{_RESERVED!r} prefix and would shadow the cache key."
            )
            raise ValueError(msg)
        values = [f"{first_param}._name", _METHOD_NAME, *self.args]
        code = f"lambda {args}: ({''.join(a for arg in values for a in (arg, ','))})"
        self.key = unsafe_eval(code, {_METHOD_NAME: self.method, **arg_globals})


class ormcache_context(ormcache):
    def __init__(self, *args: str, keys: tuple[str, ...], skiparg: None = None) -> None:
        assert skiparg is None, "ormcache_context() no longer supports skiparg"
        warnings.warn(
            "Since 19.0, use ormcache directly, context values are available as `self.env.context.get`",
            DeprecationWarning,
            stacklevel=2,
        )
        self.keys = keys
        super().__init__(*args)

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
    show_size = sig == signal.SIGUSR2
    if sig not in (None, signal.SIGUSR1, signal.SIGUSR2):
        return

    global _logger_state  # noqa: PLW0603  process-wide cache-stats logging state
    with _logger_lock:
        if _logger_state != "wait":
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
        from odoo.modules.registry import Registry

        try:
            cache_stats: defaultdict[str, dict[Callable, StatsLine]] = defaultdict(dict)
            cache_usage: defaultdict[str, list[tuple[str, int, int, int]]] = (
                defaultdict(list)
            )

            registries = Registry.registries.snapshot
            class_slots: dict[type, tuple[str, ...]] = {}
            for i, (dbname, registry) in enumerate(registries.items(), start=1):
                if not check_continue_logging():
                    return
                _logger.info(
                    "Processing database %s (%d/%d)", dbname, i, len(registries)
                )
                db_cache_stats = cache_stats[dbname]
                db_cache_usage = cache_usage[dbname]
                for cache_name, cache in registry.ormcache_lrus.items():
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

            for (
                (
                    dbname,
                    method,
                ),
                counter,
            ) in _COUNTERS.copy().items():
                if not check_continue_logging():
                    return
                db_cache_stats = cache_stats[dbname]
                stats = db_cache_stats.get(method)
                if stats is None:
                    db_cache_stats[method] = StatsLine(method, counter)

            log_msgs = ["Caches stats:"]
            if not _TX_STATS_ENABLED:
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
            global _logger_state  # noqa: PLW0603  process-wide cache-stats logging state
            with _logger_lock:
                _logger_state = "wait"

    threading.Thread(
        target=_log_ormcache_stats,
        name=(
            "odoo.signal.log_ormcache_stats_with_size"
            if show_size
            else "odoo.signal.log_ormcache_stats"
        ),
    ).start()


def get_cache_size(
    obj: Any,
    *,
    cache_info: str = "",
    seen_ids: set[int] | None = None,
    class_slots: dict[type, tuple[str, ...]] | None = None,
) -> int:
    from odoo.api import Environment
    from odoo.models import BaseModel

    if seen_ids is None:
        seen_ids = set(map(id, (None, False, True)))
    if class_slots is None:
        class_slots = {}
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
            attributes = class_slots.get(cur_obj_cls)
            if attributes is None:
                class_slots[cur_obj_cls] = attributes = tuple(
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

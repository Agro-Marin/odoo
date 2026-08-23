import threading
import typing
from collections import OrderedDict
from collections.abc import Iterable, Iterator, MutableMapping

from .iteration.sentinel import SENTINEL

__all__ = ["LRU"]


class LRU[K, V](MutableMapping[K, V]):
    """A bounded, thread-safe LRU mapping.

    One ``OrderedDict``, not a values dict beside an ordering dict.  Two maps
    can disagree, and the read path is the one operation too hot to lock: as
    ``self._ordering[key] = self._ordering.pop(key, None)`` it left a window in
    which the key was in ``_values`` and in neither position of ``_ordering``.
    Everything that used to defend against that window -- a repair loop in
    ``__setitem__``, ``except RuntimeError: continue`` in two places, a victim
    search that could fall back to evicting the key just inserted, and a
    reconciliation pass in ``snapshot`` -- is gone with the second map, because
    there is no longer a second structure to fall out of step with.

    ``move_to_end`` and ``popitem`` are single C calls, so the write path holds
    no Python-level iterator over the map.  ``next(iter(ordering), key)``, the
    expression they replace, raises ``RuntimeError`` under concurrent readers.
    """

    __slots__ = ("_count", "_generation", "_lock", "_map")

    def __init__(self, count: int, pairs: Iterable[tuple[K, V]] = ()) -> None:
        if count <= 0:
            raise ValueError(f"LRU count must be positive, got {count!r}")
        self._count = count
        self._generation = 0
        self._lock = threading.RLock()
        self._map: OrderedDict[K, V] = OrderedDict()

        for key, value in pairs:
            self[key] = value

    @property
    def count(self) -> int:
        return self._count

    @count.setter
    def count(self, count: int) -> None:
        if count <= 0:
            raise ValueError(f"LRU count must be positive, got {count!r}")
        with self._lock:
            self._count = count
            self._trim()

    def _trim(self) -> None:
        """Evict from the front until the map fits.  The caller holds the lock."""
        map_ = self._map
        count = self._count
        while len(map_) > count:
            map_.popitem(last=False)

    def __contains__(self, key: object) -> bool:
        return key in self._map

    def __getitem__(self, key: K) -> V:
        value = self._map[key]
        # Evicted between the lookup and the bump: the value is still the one
        # this reader asked for, only its recency is now moot.  Not
        # `contextlib.suppress`, which SIM105 asks for: this is the hottest
        # read in the ORM cache, and suppress costs 157ns per call against
        # try/except's 27ns when nothing raises.
        try:  # noqa: SIM105  see above
            self._map.move_to_end(key)
        except KeyError:
            pass
        return value

    def __setitem__(self, key: K, value: V) -> None:
        with self._lock:
            map_ = self._map
            existing = key in map_
            map_[key] = value
            if existing:
                map_.move_to_end(key)
            else:
                self._trim()

    def __delitem__(self, key: K) -> None:
        self.pop(key)

    def __len__(self) -> int:
        return len(self._map)

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}"
            f"(count={self._count}, size={len(self._map)}, gen={self._generation})"
        )

    def __iter__(self) -> Iterator[K]:
        return iter(self.snapshot)

    @property
    def snapshot(self) -> dict[K, V]:
        # dict() over an OrderedDict is a single C call, so it cannot observe a
        # concurrent move_to_end half-applied.
        with self._lock:
            return dict(self._map)

    @typing.overload
    def pop(self, key: K, /) -> V: ...
    @typing.overload
    def pop(self, key: K, /, default: V) -> V: ...
    @typing.overload
    def pop[T](self, key: K, /, default: T) -> V | T: ...

    def pop(self, key: K, /, default: typing.Any = SENTINEL) -> typing.Any:
        with self._lock:
            if default is SENTINEL:
                return self._map.pop(key)
            return self._map.pop(key, default)

    def clear(self) -> None:
        with self._lock:
            self._generation += 1
            self._map.clear()

    @property
    def generation(self) -> int:
        return self._generation

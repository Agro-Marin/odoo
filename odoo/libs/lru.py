import threading
import typing
from collections import OrderedDict
from collections.abc import Iterable, Iterator, MutableMapping

from .iteration.sentinel import SENTINEL

__all__ = ["LRU"]


class LRU[K, V](MutableMapping[K, V]):
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
        map_ = self._map
        count = self._count
        while len(map_) > count:
            map_.popitem(last=False)

    def __contains__(self, key: object) -> bool:
        return key in self._map

    def __getitem__(self, key: K) -> V:
        value = self._map[key]
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

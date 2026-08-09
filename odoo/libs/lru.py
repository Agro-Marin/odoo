import threading
import typing
from collections.abc import Iterable, Iterator, MutableMapping

from .iteration.sentinel import SENTINEL

__all__ = ["LRU"]


class LRU[K, V](MutableMapping[K, V]):
    __slots__ = ("_count", "_generation", "_lock", "_ordering", "_values")

    def __init__(self, count: int, pairs: Iterable[tuple[K, V]] = ()) -> None:
        if count <= 0:
            raise ValueError(f"LRU count must be positive, got {count!r}")
        self._count = count
        self._generation = 0
        self._lock = threading.RLock()
        self._values: dict[K, V] = {}
        self._ordering: dict[K, None] = {}

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
            while len(self._values) > count:
                try:
                    key = next(iter(self._ordering), None)
                except RuntimeError:
                    continue
                if key is None:
                    key = next(iter(self._values))
                self._values.pop(key, None)
                self._ordering.pop(key, None)

    def __contains__(self, key: object) -> bool:
        return key in self._values

    def __getitem__(self, key: K) -> V:
        val = self._values[key]
        self._ordering[key] = self._ordering.pop(key, None)
        return val

    def __setitem__(self, key: K, val: V) -> None:
        values = self._values
        ordering = self._ordering
        with self._lock:
            values[key] = val
            ordering[key] = ordering.pop(key, None)
            while True:
                if len(ordering) > len(values):
                    for k in ordering.copy():
                        if k not in values:
                            ordering.pop(k, None)
                if len(values) <= self._count:
                    break
                try:
                    key = next(iter(ordering), key)
                except RuntimeError:
                    continue
                values.pop(key, None)
                ordering.pop(key, None)

    def __delitem__(self, key: K) -> None:
        self.pop(key)

    def __len__(self) -> int:
        return len(self._values)

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}"
            f"(count={self._count}, size={len(self._values)}, gen={self._generation})"
        )

    def __iter__(self) -> Iterator[K]:
        return iter(self.snapshot)

    @property
    def snapshot(self) -> dict[K, V]:
        with self._lock:
            values = self._values
            result = {
                key: typing.cast("V", val)
                for key in self._ordering.copy()
                if (val := values.get(key, SENTINEL)) is not SENTINEL
            }
            if len(result) < len(values):
                result.update(values)
        return result

    @typing.overload
    def pop(self, key: K, /) -> V: ...
    @typing.overload
    def pop(self, key: K, /, default: V) -> V: ...
    @typing.overload
    def pop[T](self, key: K, /, default: T) -> V | T: ...

    def pop(self, key: K, /, default: typing.Any = SENTINEL) -> typing.Any:
        with self._lock:
            self._ordering.pop(key, None)
            if default is SENTINEL:
                return self._values.pop(key)
            return self._values.pop(key, default)

    def clear(self) -> None:
        with self._lock:
            self._generation += 1
            self._ordering.clear()
            self._values.clear()

    @property
    def generation(self) -> int:
        return self._generation

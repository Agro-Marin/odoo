"""Length-limited, thread-safe LRU (least recently used) mapping."""

import threading
import typing
from collections.abc import Iterable, Iterator, MutableMapping

from .iteration.sentinel import SENTINEL

__all__ = ["LRU"]


class LRU[K, V](MutableMapping[K, V]):
    """Implementation of a length-limited LRU map.

    The mapping is thread-safe, and internally uses a lock to avoid concurrency
    issues. However, access operations like ``lru[key]`` are fast and
    lock-free.
    """

    __slots__ = ("_count", "_generation", "_lock", "_ordering", "_values")

    def __init__(self, count: int, pairs: Iterable[tuple[K, V]] = ()) -> None:
        """Build an LRU holding at most ``count`` items, seeded with ``pairs``."""
        if count <= 0:
            raise ValueError(f"LRU count must be positive, got {count!r}")
        self._count = count
        # Monotonic clear counter. Readers that compute a value outside the lock
        # and then store it can snapshot this before computing and skip the
        # store if it changed, so a clear() landing mid-compute is not undone by
        # re-caching stale data. See odoo.tools.cache.ormcache.
        self._generation = 0
        self._lock = threading.RLock()
        self._values: dict[K, V] = {}
        #
        # The dict self._values contains the LRU items, while self._ordering
        # only keeps track of their order, the most recently used ones being
        # last. For performance reasons, we only use the lock when modifying
        # the LRU, while reading it is lock-free (and thus faster).
        #
        # This strategy may result in inconsistencies between self._values and
        # self._ordering. Indeed, concurrently accessed keys may be missing
        # from self._ordering, but will eventually be added. This could result
        # in keys being added back in self._ordering after their actual removal
        # from the LRU. This results in the following invariant:
        #
        #     self._values <= self._ordering | "keys being accessed"
        #
        self._ordering: dict[K, None] = {}

        # Initialize
        for key, value in pairs:
            self[key] = value

    @property
    def count(self) -> int:
        """Return the maximum number of items the LRU keeps."""
        return self._count

    @count.setter
    def count(self, count: int) -> None:
        if count <= 0:
            raise ValueError(f"LRU count must be positive, got {count!r}")
        with self._lock:
            self._count = count
            values = self._values
            ordering = self._ordering
            while len(values) > count:
                if len(ordering) > len(values):
                    for k in ordering.copy():
                        if k not in values:
                            ordering.pop(k, None)
                # Evict the least-recently-used key straight from ``_ordering``
                # (O(1) via ``next(iter(...))``).  ``self.popitem()`` went through
                # ``MutableMapping.popitem`` → ``next(iter(self))`` → ``snapshot``,
                # rebuilding a full ordered dict copy per evicted item (O(n²)).
                try:
                    lru_key = next(iter(ordering))
                except (StopIteration, RuntimeError):
                    break
                ordering.pop(lru_key, None)
                values.pop(lru_key, None)

    def __contains__(self, key: object) -> bool:
        """Return whether ``key`` is present in the LRU."""
        return key in self._values

    def __getitem__(self, key: K) -> V:
        """Return the value for ``key`` and mark it as most recently used."""
        val = self._values[key]
        # move key at the last position in self._ordering
        self._ordering[key] = self._ordering.pop(key, None)
        return val

    def __setitem__(self, key: K, val: V) -> None:
        """Store ``val`` under ``key``, evicting least recently used items over count."""
        values = self._values
        ordering = self._ordering
        with self._lock:
            values[key] = val
            ordering[key] = ordering.pop(key, None)
            while True:
                # if we have too many keys in ordering, filter them out
                if len(ordering) > len(values):
                    # (copy to avoid concurrent changes on ordering)
                    for k in ordering.copy():
                        if k not in values:
                            ordering.pop(k, None)
                # check if we have too many keys
                if len(values) <= self._count:
                    break
                # if so, pop the least recently used
                try:
                    # have a default in case of concurrent accesses
                    key = next(iter(ordering), key)
                except RuntimeError:
                    # ordering modified during iteration, retry
                    continue
                values.pop(key, None)
                ordering.pop(key, None)

    def __delitem__(self, key: K) -> None:
        """Remove ``key`` from the LRU."""
        self.pop(key)

    def __len__(self) -> int:
        """Return the number of items currently in the LRU."""
        return len(self._values)

    def __iter__(self) -> Iterator[K]:
        """Iterate over keys, least recently used first."""
        return iter(self.snapshot)

    @property
    def snapshot(self) -> dict[K, V]:
        """Return a copy of the LRU (ordered according to LRU first)."""
        with self._lock:
            values = self._values
            # build result in expected order (copy self._ordering to avoid concurrent changes)
            result = {
                key: val
                for key in self._ordering.copy()
                if (val := values.get(key, SENTINEL)) is not SENTINEL
            }
            if len(result) < len(values):
                # keys in value were missing from self._ordering, add them
                result.update(values)
        return result

    # Overloads mirror ``MutableMapping.pop`` (typeshed): with an explicit
    # ``default`` of any type T, the result is ``V | T`` and no KeyError is
    # raised; without it, the result is ``V`` or KeyError.
    @typing.overload
    def pop(self, key: K, /) -> V: ...
    @typing.overload
    def pop(self, key: K, /, default: V) -> V: ...
    @typing.overload
    def pop[T](self, key: K, /, default: T) -> V | T: ...

    def pop(self, key: K, /, default: typing.Any = SENTINEL) -> typing.Any:
        """Remove ``key`` and return its value, or ``default`` if it is absent.

        :raises KeyError: if ``key`` is absent and no ``default`` is given
        """
        with self._lock:
            self._ordering.pop(key, None)
            if default is SENTINEL:
                return self._values.pop(key)
            return self._values.pop(key, default)

    def clear(self) -> None:
        """Remove all items from the LRU."""
        with self._lock:
            self._generation += 1
            self._ordering.clear()
            self._values.clear()

    @property
    def generation(self) -> int:
        """Number of times this LRU has been cleared (see ``__init__``)."""
        return self._generation

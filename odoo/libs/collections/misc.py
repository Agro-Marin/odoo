"""Miscellaneous collection types and adapters."""

__all__ = ["Collector", "ReversedIterable", "StackMap"]

from collections.abc import Iterable, Iterator, MutableMapping, Reversible


class Collector[K, T](dict[K, tuple[T, ...]]):
    """A mapping from keys to tuples.

    This implements a relation, and can be seen as a space optimization
    for ``defaultdict(tuple)``.
    """

    __slots__ = ()

    def __getitem__(self, key: K) -> tuple[T, ...]:
        """Return the tuple stored at ``key``, or an empty tuple if absent."""
        return self.get(key, ())

    def __setitem__(self, key: K, val: Iterable[T]) -> None:
        """Store ``val`` as a tuple at ``key``, removing the key if empty."""
        val = tuple(val)
        if val:
            super().__setitem__(key, val)
        else:
            super().pop(key, None)

    def add(self, key: K, val: T) -> None:
        """Append ``val`` to the tuple at ``key`` if not already present."""
        vals = self[key]
        if val not in vals:
            self[key] = vals + (val,)

    def discard_keys_and_values(self, excludes: Iterable[K]) -> None:
        """Drop the given keys, and remove their values wherever they occur."""
        # Materialize once: ``excludes`` is scanned twice (as keys, then as a
        # membership test per value).  A generator would be exhausted by the
        # first pass, silently removing nothing on the second; a list makes the
        # per-value ``in`` test O(n) instead of O(1).
        excludes = frozenset(excludes)
        for key in excludes:
            self.pop(key, None)
        for key, vals in list(self.items()):
            self[key] = tuple(val for val in vals if val not in excludes)


class StackMap[K, T](MutableMapping[K, T]):
    """A stack of mappings behaving as a single mapping.

    Used to implement nested scopes. The lookups search the stack from
    top to bottom, and returns the first value found. Mutable operations
    modify the topmost mapping only.
    """

    __slots__ = ["_maps"]

    def __init__(self, m: MutableMapping[K, T] | None = None) -> None:
        """Initialize the stack with ``m`` as its single mapping, if given."""
        self._maps: list[MutableMapping[K, T]] = [] if m is None else [m]

    def __getitem__(self, key: K) -> T:
        """Return the value for ``key`` from the topmost mapping that has it."""
        for mapping in reversed(self._maps):
            try:
                return mapping[key]
            except KeyError:
                pass
        raise KeyError(key)

    def __setitem__(self, key: K, val: T) -> None:
        """Set ``key`` to ``val`` in the topmost mapping."""
        self._maps[-1][key] = val

    def __delitem__(self, key: K) -> None:
        """Delete ``key`` from the topmost mapping."""
        del self._maps[-1][key]

    def __iter__(self) -> Iterator[K]:
        """Iterate over the distinct keys present in any mapping."""
        return iter({key for mapping in self._maps for key in mapping})

    def __len__(self) -> int:
        """Return the number of distinct keys across all mappings."""
        return sum(1 for key in self)

    def __str__(self) -> str:
        """Return a readable representation of the stack of mappings."""
        return f"<StackMap {self._maps}>"

    def pushmap(self, m: MutableMapping[K, T] | None = None) -> None:
        """Push ``m`` (or a new empty mapping) onto the top of the stack."""
        self._maps.append({} if m is None else m)

    def popmap(self) -> MutableMapping[K, T]:
        """Pop and return the topmost mapping from the stack."""
        return self._maps.pop()


class ReversedIterable[T](Reversible[T]):
    """An iterable implementing the reversal of another iterable."""

    __slots__ = ["iterable"]

    def __init__(self, iterable: Reversible[T]) -> None:
        """Wrap ``iterable`` so that iteration yields it in reverse."""
        self.iterable = iterable

    def __iter__(self) -> Iterator[T]:
        """Iterate over the wrapped iterable in reverse order."""
        return reversed(self.iterable)

    def __reversed__(self) -> Iterator[T]:
        """Iterate over the wrapped iterable in its original order."""
        return iter(self.iterable)

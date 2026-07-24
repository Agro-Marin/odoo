"""Insertion-order-preserving set collections."""

__all__ = ["LastOrderedSet", "OrderedSet"]

import itertools
from collections.abc import Iterable, Iterator, MutableSet
from functools import reduce
from typing import Self


class OrderedSet[T](MutableSet[T]):
    """A set collection that remembers the elements first insertion order."""

    __slots__ = ["_map"]

    def __init__(self, elems: Iterable[T] = ()) -> None:
        """Initialize the set from an iterable of elements."""
        self._map: dict[T, None] = dict.fromkeys(elems)

    def __contains__(self, elem: object) -> bool:
        """Return whether the set contains ``elem``."""
        return elem in self._map

    def __iter__(self) -> Iterator[T]:
        """Return an iterator over the elements in insertion order."""
        return iter(self._map)

    def __len__(self) -> int:
        """Return the number of elements in the set."""
        return len(self._map)

    def add(self, elem: T) -> None:
        """Add ``elem`` to the set, keeping its original insertion order."""
        self._map[elem] = None

    def discard(self, elem: T) -> None:
        """Remove ``elem`` from the set if it is present."""
        self._map.pop(elem, None)

    def update(self, elems: Iterable[T]) -> None:
        """Add all elements of ``elems`` to the set."""
        self._map.update(zip(elems, itertools.repeat(None)))

    def difference_update(self, elems: Iterable[T]) -> None:
        """Remove all elements of ``elems`` from the set."""
        # inline discard to avoid method dispatch per element
        _pop = self._map.pop
        for elem in elems:
            _pop(elem, None)

    def __repr__(self) -> str:
        """Return a string representation of the set."""
        return f"{type(self).__name__}({list(self)!r})"

    def intersection(self, *others: Iterable[T]) -> OrderedSet[T]:
        """Return a new set with the elements common to this set and all ``others``."""
        return reduce(OrderedSet.__and__, others, self)

    def copy(self) -> Self:
        """Return a shallow copy of the set.

        Uses ``object.__new__`` + ``dict.copy()`` instead of iterating
        ``self`` to avoid triggering Python-level callbacks (e.g. GC
        ``__del__`` / WeakSet ``_remove``) that can mutate ``_map`` while
        it is being read.  This matters when an ``OrderedSet`` is used as
        the backing store for a ``weakref.WeakSet``: Python 3.14 changed
        ``WeakSet.__iter__`` to call ``self.data.copy()`` before iteration,
        and the GC can fire ``_remove`` callbacks during a Python-level
        iteration of ``_map``, raising
        ``RuntimeError: dictionary changed size during iteration``.
        """
        instance = object.__new__(type(self))
        instance._map = self._map.copy()
        return instance


class LastOrderedSet[T](OrderedSet[T]):
    """A set collection that remembers the elements last insertion order."""

    def add(self, elem: T) -> None:
        """Add ``elem`` to the set, moving it to the last insertion position."""
        self.discard(elem)
        super().add(elem)

    def update(self, elems: Iterable[T]) -> None:
        """Add all ``elems``, moving each to the last insertion position."""
        # Overrides ``OrderedSet.update`` (``dict.update``, which keeps the
        # position of already-present keys) so re-adding an existing element
        # moves it to the end, matching this class's last-insertion-order
        # contract.
        for elem in elems:
            self.add(elem)

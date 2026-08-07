__all__ = ["LastOrderedSet", "OrderedSet"]

import itertools
from collections.abc import Iterable, Iterator, MutableSet
from functools import reduce
from typing import Self


class OrderedSet[T](MutableSet[T]):
    __slots__ = ["_map"]

    def __init__(self, elems: Iterable[T] = ()) -> None:
        self._map: dict[T, None] = dict.fromkeys(elems)

    def __contains__(self, elem: object) -> bool:
        return elem in self._map

    def __iter__(self) -> Iterator[T]:
        return iter(self._map)

    def __len__(self) -> int:
        return len(self._map)

    def add(self, elem: T) -> None:
        self._map[elem] = None

    def discard(self, elem: T) -> None:
        self._map.pop(elem, None)

    def update(self, elems: Iterable[T]) -> None:
        self._map.update(zip(elems, itertools.repeat(None)))

    def difference_update(self, elems: Iterable[T]) -> None:
        _pop = self._map.pop
        for elem in elems:
            _pop(elem, None)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({list(self)!r})"

    def intersection(self, *others: Iterable[T]) -> OrderedSet[T]:
        if not others:
            return self.copy()
        return reduce(OrderedSet.__and__, others, self)

    def copy(self) -> Self:
        instance = object.__new__(type(self))
        instance._map = self._map.copy()
        return instance


class LastOrderedSet[T](OrderedSet[T]):
    __slots__ = ()

    def add(self, elem: T) -> None:
        self.discard(elem)
        super().add(elem)

    def update(self, elems: Iterable[T]) -> None:
        for elem in elems:
            self.add(elem)
